from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, UploadFile
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from research.broker import service as broker
from research.market_data import service as md
from research.market_data.tiingo import MarketDataError
from research.broker.ibkr_flex import parse_flex_statement
from research.core.config import settings as app_settings
from research.db import models as m
from research.db.session import get_db
from research.engine.swings import SENSITIVITY_PRESETS, resolve_k
from research.services import analysis as an
from research.services.overview import overview
from research.services.portfolio import SUPPORTED_BASE, merge_provenance, value_portfolio

router = APIRouter(prefix="/api")

DEFAULTS = {"base_currency": "USD", "default_sensitivity": "medium", "theme": "system", "holdings_source": "tracker"}
HOLDINGS_SOURCES = ("tracker", "synthetic", "ibkr_flex")  # tracker = your open positions in Portfolio Tracker
BROKER_SOURCES = ("tracker", "ibkr_flex")  # real holdings imported as a broker-style snapshot


def get_settings(db: Session) -> dict:
    s = dict(DEFAULTS)
    for row in db.scalars(select(m.AppSetting)).all():
        s[row.key] = row.value_json
    return s


def sync_tracker(db: Session, force: bool = False) -> dict | None:
    """Bring Research's holdings in line with Portfolio Tracker's open positions (only when they changed)."""
    from research.broker import tracker as tr
    from research.broker.base import BrokerError
    from research.market_data.service import find_real_listing
    try:
        pos, tickers = tr.read_tracker()
    except BrokerError as e:
        return {"status": "skipped", "error_code": e.code, "message": e.message}
    fp = tr.fingerprint(pos, tickers)
    row = db.get(m.AppSetting, "tracker_fingerprint")
    if not force and row is not None and row.value_json == fp and broker.last_success(db) is not None \
            and broker.last_success(db).source == tr.SOURCE:
        return {"status": "up_to_date"}

    def mic_for(t):
        lst = find_real_listing(db, t)
        return lst.exchange_mic if lst else None
    snap = tr.snapshot_from_positions(pos, tickers, mic_for)
    out = broker.run_sync(db, lambda: snap, source=tr.SOURCE, enforce_cooldown=False)
    if out.get("status") == "success":
        if row is None:
            db.add(m.AppSetting(key="tracker_fingerprint", value_json=fp))
        else:
            row.value_json = fp
        db.commit()
    return out


@router.get("/health")
def health(db: Session = Depends(get_db)):
    n = db.scalar(select(m.Listing.id).limit(1))
    if get_settings(db)["holdings_source"] == "tracker":
        sync_tracker(db)
    return {"status": "ok", "seeded": n is not None, "holdings_source": get_settings(db)["holdings_source"],
            "provenance": {"source": "synthetic", "is_synthetic": True, "as_of": None,
                           "exchange_timezone": None, "is_delayed": False, "delay_minutes": 0,
                           "stale": False}}


@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    return {"settings": get_settings(db), "options": {
        "base_currency": list(SUPPORTED_BASE), "default_sensitivity": list(SENSITIVITY_PRESETS),
        "theme": ["system", "light", "dark"], "holdings_source": list(HOLDINGS_SOURCES)}}


class SettingsIn(BaseModel):
    base_currency: str | None = None
    default_sensitivity: str | None = None
    theme: str | None = None
    holdings_source: str | None = None

    @field_validator("holdings_source")
    @classmethod
    def _src(cls, v):
        if v is not None and v not in HOLDINGS_SOURCES:
            raise ValueError(f"must be one of {HOLDINGS_SOURCES}")
        return v

    @field_validator("base_currency")
    @classmethod
    def _ccy(cls, v):
        if v is not None and v not in SUPPORTED_BASE:
            raise ValueError(f"must be one of {SUPPORTED_BASE}")
        return v

    @field_validator("default_sensitivity")
    @classmethod
    def _sens(cls, v):
        if v is not None:
            resolve_k(v)
        return v

    @field_validator("theme")
    @classmethod
    def _theme(cls, v):
        if v is not None and v not in ("system", "light", "dark"):
            raise ValueError("must be system, light or dark")
        return v


@router.put("/settings")
def write_settings(body: SettingsIn, db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_none=True).items():
        row = db.get(m.AppSetting, k)
        if row:
            row.value_json = v
        else:
            db.add(m.AppSetting(key=k, value_json=v))
    db.commit()
    return read_settings(db)


@router.get("/listings")
def listings(db: Session = Depends(get_db)):
    out, provs = [], []
    for lst in db.scalars(select(m.Listing).order_by(m.Listing.namespace, m.Listing.id)).all():
        bars = an.load_bars(db, lst.id)
        p = an.provenance(lst, bars.df)
        provs.append(p)
        out.append({**an.listing_dict(lst), "provenance": p})
    return {"listings": out, "provenance": merge_provenance(provs)}


@router.get("/listings/find")
def find_listing(ticker: str, db: Session = Depends(get_db)):
    """The Research listing with real prices for a ticker, for links from Portfolio Tracker's pages (never the demo data)."""
    from research.market_data.service import to_tiingo_symbol
    t = ticker.strip().upper()
    lst = db.scalar(select(m.Listing).where(m.Listing.namespace == "real",
                                            (m.Listing.provider_symbol == to_tiingo_symbol(t)) | (m.Listing.ticker == t)).limit(1))
    if lst is None:
        raise an.NotFound(f"Research has no real price history for {t} yet")
    return {"listing_id": lst.id, "ticker": lst.ticker, "namespace": "real"}


@router.get("/listings/{listing_id}")
def listing(listing_id: int, db: Session = Depends(get_db)):
    lst = db.get(m.Listing, listing_id)
    if lst is None:
        raise an.NotFound(f"listing {listing_id} not found")
    return {**an.listing_dict(lst), "provenance": an.provenance(lst, an.load_bars(db, listing_id).df)}


@router.get("/listings/{listing_id}/bars")
def bars(listing_id: int, from_: date | None = Query(None, alias="from"), to: date | None = None,
         db: Session = Depends(get_db)):
    b = an.load_bars(db, listing_id, to)
    df = b.df
    if from_ is not None and not df.empty:
        df = df[df["date"] >= from_]
    return {"listing": an.listing_dict(b.listing), "provenance": an.provenance(b.listing, b.df),
            "bars": [{"date": r["date"].isoformat(), "open": r["open"], "high": r["high"],
                      "low": r["low"], "close": r["close"], "volume": an._f(r["volume"])}
                     for r in df.to_dict("records")]}


@router.get("/listings/{listing_id}/analysis")
def analysis(listing_id: int, as_of: date | None = None, sensitivity: str | None = None,
             interval: str = "1d", db: Session = Depends(get_db)):
    sens = sensitivity or get_settings(db)["default_sensitivity"]
    return an.analyse_listing(db, listing_id, as_of, sens, interval=interval)


@router.get("/portfolio")
def portfolio(base: str | None = None, source: str | None = None, db: Session = Depends(get_db)):
    s = get_settings(db)
    b = base or s["base_currency"]
    if b not in SUPPORTED_BASE:
        raise an.BadRequest(f"base currency must be one of {SUPPORTED_BASE}")
    if (source or s["holdings_source"]) in BROKER_SOURCES:
        return broker.value_broker_portfolio(db, b)
    return value_portfolio(db, b, s["default_sensitivity"])


@router.get("/overview")
def get_overview(base: str | None = None, db: Session = Depends(get_db)):
    s = get_settings(db)
    return overview(db, base or s["base_currency"], s["default_sensitivity"], s["holdings_source"])


# ---------------------------------------------------------------- IBKR (read-only)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/broker/ibkr-flex/status")
def ibkr_status(db: Session = Depends(get_db)):
    return {"configured": broker.flex_configured(),
            "query_id_masked": broker.mask_query_id(app_settings.ibkr_flex_query_id),
            "holdings_source": get_settings(db)["holdings_source"],
            "cooldown_seconds": app_settings.broker_sync_cooldown_seconds,
            "runs": broker.recent_runs(db)}


@router.post("/broker/ibkr-flex/sync")
def ibkr_sync(db: Session = Depends(get_db)):
    adapter = broker.default_flex_adapter()
    return broker.run_sync(db, adapter.fetch_snapshot, source="ibkr_flex")


@router.post("/broker/ibkr-flex/import")
async def ibkr_import(file: UploadFile, db: Session = Depends(get_db)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise an.BadRequest("File too large (max 20 MB).")
    return broker.run_sync(db, lambda: parse_flex_statement(content), source="ibkr_flex_file", enforce_cooldown=False)


# ---------------------------------------------------------------- real market data (Tiingo)

class SymbolIn(BaseModel):
    ticker: str


@router.get("/market-data/status")
def market_data_status(db: Session = Depends(get_db)):
    return md.status(db)


class RefreshIn(BaseModel):
    symbols: list[str] | None = None
    force: bool = False


@router.post("/market-data/refresh")
def market_data_refresh(body: RefreshIn | None = None, db: Session = Depends(get_db)):
    body = body or RefreshIn()
    out = md.refresh_all(db, only=body.symbols, force=body.force)
    return {**out, "alerts": evaluate_alerts(db)}


class ForceIn(BaseModel):
    force: bool = False


@router.post("/listings/{listing_id}/refresh")
def listing_refresh(listing_id: int, body: ForceIn | None = None, db: Session = Depends(get_db)):
    out = md.refresh_one(db, listing_id, force=(body or ForceIn()).force)
    return {**out, "alerts": evaluate_alerts(db)}


@router.post("/refresh")
def refresh_everything(db: Session = Depends(get_db)):
    """On-demand refresh: IBKR holdings (if that's the holdings source and it's configured)
    and Tiingo prices (if configured). Each step reports its own outcome; one failing doesn't block the other."""
    from research.broker.base import BrokerError
    out: dict = {"ibkr": None, "prices": None}
    s = get_settings(db)
    if s["holdings_source"] == "tracker":
        out["ibkr"] = sync_tracker(db, force=True)
    if s["holdings_source"] == "ibkr_flex":
        if broker.flex_configured():
            try:
                out["ibkr"] = broker.run_sync(db, broker.default_flex_adapter().fetch_snapshot, source="ibkr_flex")
            except BrokerError as e:
                out["ibkr"] = {"status": "skipped" if e.code == "cooldown" else "failed", "error_code": e.code, "message": e.message}
        else:
            out["ibkr"] = {"status": "skipped", "error_code": "not_configured", "message": "IBKR Flex is not configured."}
    if md.configured():
        try:
            r = md.refresh_all(db)
            res = r["results"]
            out["prices"] = {"status": "ok", "updated": sum(x["status"] == "updated" for x in res),
                             "up_to_date": sum(x["status"] == "up_to_date" for x in res),
                             "failed": sum(x["status"] == "failed" for x in res),
                             "skipped_budget": sum(x["status"] == "skipped_budget" for x in res),
                             "session": r["session"], "results": res, "usage": r["usage"]}
        except MarketDataError as e:
            out["prices"] = {"status": "failed", "error_code": e.code, "message": e.message}
    else:
        out["prices"] = {"status": "skipped", "error_code": "not_configured", "message": "Tiingo is not configured."}
    from research.market_data import eu_service
    if eu_service.configured():
        try:
            r = eu_service.refresh_all(db)
            res = r["results"]
            out["eu_prices"] = {"status": "ok", "updated": sum(x["status"] == "updated" for x in res),
                                "up_to_date": sum(x["status"] == "up_to_date" for x in res),
                                "failed": sum(x["status"] == "failed" for x in res),
                                "skipped_budget": sum(x["status"] == "skipped_budget" for x in res),
                                "results": res, "usage": r["usage"]}
        except MarketDataError as e:
            db.rollback()
            out["eu_prices"] = {"status": "failed", "error_code": e.code, "message": e.message}
    else:
        out["eu_prices"] = {"status": "skipped", "error_code": "not_configured", "message": "EODHD is not configured."}
    out["fx"] = _refresh_fx(db)
    out["alerts"] = evaluate_alerts(db)
    return out


@router.post("/market-data/symbols")
def market_data_add(body: SymbolIn, db: Session = Depends(get_db)):
    return md.add_symbol(db, body.ticker)


@router.delete("/market-data/symbols/{ticker}")
def market_data_remove(ticker: str, db: Session = Depends(get_db)):
    md.remove_symbol(db, ticker)
    return md.status(db)


@router.get("/screener")
def get_screener(namespace: str = "all", sensitivity: str | None = None, db: Session = Depends(get_db)):
    from research.services.screener import screener
    s = get_settings(db)
    sens = sensitivity or s["default_sensitivity"]
    try:
        resolve_k(sens)
    except ValueError as e:
        raise an.BadRequest(str(e)) from e
    return screener(db, sens, s["holdings_source"], namespace)


# ---------------------------------------------------------------- opportunity scanner + watchlist

def _sensitivity(db: Session, sensitivity: str | None) -> str:
    sens = sensitivity or get_settings(db)["default_sensitivity"]
    try:
        resolve_k(sens)
    except ValueError as e:
        raise an.BadRequest(str(e)) from e
    return sens


@router.get("/scanner")
def get_scanner(db: Session = Depends(get_db)):
    from research.services import scanner
    return scanner.latest_scan(db, get_settings(db)["holdings_source"])


class ScanIn(BaseModel):
    sensitivity: str | None = None


@router.post("/scanner/run")
def post_scanner_run(body: ScanIn | None = None, db: Session = Depends(get_db)):
    from research.services import scanner
    sens = _sensitivity(db, (body or ScanIn()).sensitivity)
    scanner.run_scan(db, sens)
    return scanner.latest_scan(db, get_settings(db)["holdings_source"])


def _check_note(v: str | None) -> str | None:
    if v is not None:
        v = v.strip() or None
    if v is not None and len(v) > 500:
        raise ValueError("note must be 500 characters or fewer")
    return v


class NoteIn(BaseModel):
    note: str | None = None
    _v = field_validator("note")(classmethod(lambda cls, v: _check_note(v)))


class WatchIn(NoteIn):
    listing_id: int


def _watchlist(db: Session) -> dict:
    from research.services import scanner
    s = get_settings(db)
    return scanner.watchlist(db, s["default_sensitivity"], s["holdings_source"])


@router.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    return _watchlist(db)


@router.post("/watchlist")
def post_watchlist(body: WatchIn, db: Session = Depends(get_db)):
    from research.services import scanner
    scanner.add_to_watchlist(db, body.listing_id, body.note)
    return _watchlist(db)


@router.patch("/watchlist/{listing_id}")
def patch_watchlist(listing_id: int, body: NoteIn, db: Session = Depends(get_db)):
    from research.services import scanner
    scanner.update_note(db, listing_id, body.note)
    return _watchlist(db)


@router.delete("/watchlist/{listing_id}")
def delete_watchlist(listing_id: int, db: Session = Depends(get_db)):
    from research.services import scanner
    scanner.remove_from_watchlist(db, listing_id)
    return _watchlist(db)


# ---------------------------------------------------------------- alerts (in-app)

def _alert_prov(db: Session) -> dict:
    from research.services import alerts
    return alerts._provenance([], alerts.last_evaluation(db))


def evaluate_alerts(db: Session) -> dict:
    """Evaluate alerts; never lets an alert failure break the caller (e.g. a price refresh)."""
    from research.services import alerts
    s = get_settings(db)
    try:
        return {"status": "ok", **alerts.evaluate(db, s["holdings_source"], s["default_sensitivity"])}
    except Exception as e:  # noqa: BLE001 - reported to the caller, logged, never raised
        db.rollback()
        import logging
        logging.getLogger("fibonacci_ai").exception("alert evaluation failed")
        return {"status": "failed", "message": f"Alert check failed: {type(e).__name__}"}


@router.get("/alerts")
def get_alerts(status: str = "all", db: Session = Depends(get_db)):
    from research.services import alerts
    if status not in ("all", "unread"):
        raise an.BadRequest("status must be 'all' or 'unread'")
    return alerts.list_alerts(db, status)


@router.get("/alerts/summary")
def alerts_summary(db: Session = Depends(get_db)):
    from research.services import alerts
    return {"unread": alerts.unread_count(db), "last_evaluation": alerts.last_evaluation(db), "provenance": _alert_prov(db)}


@router.post("/alerts/evaluate")
def alerts_evaluate(db: Session = Depends(get_db)):
    from research.services import alerts
    out = evaluate_alerts(db)
    return {**out, "unread": alerts.unread_count(db), "provenance": _alert_prov(db)}


@router.post("/alerts/read-all")
def alerts_read_all(db: Session = Depends(get_db)):
    from research.services import alerts
    n = alerts.mark_all_read(db)
    return {"marked": n, "unread": alerts.unread_count(db), "provenance": _alert_prov(db)}


@router.post("/alerts/{alert_id}/read")
def alerts_read(alert_id: int, db: Session = Depends(get_db)):
    from research.services import alerts
    alerts.mark_read(db, alert_id)
    return {"unread": alerts.unread_count(db), "provenance": _alert_prov(db)}


@router.get("/alerts/config")
def alerts_config(db: Session = Depends(get_db)):
    from research.engine.alerts import DEFAULT_CONFIG, LABELS, SMA_CHOICES
    from research.services import alerts
    from research.data.sectors import US
    from research.engine.rotation import CATEGORY_LABELS
    from research.engine.rrg import TIMEFRAMES
    return {"config": alerts.get_config(db), "defaults": DEFAULT_CONFIG, "labels": LABELS,
            "sma_choices": list(SMA_CHOICES),
            "rotation_options": {"timeframes": {k: v[0] for k, v in TIMEFRAMES.items()}, "benchmarks": list(US.benchmarks),
                                 "categories": CATEGORY_LABELS, "regions": {"us": "US sectors", "eu": "European sectors (vs EXSA)"}},
            "provenance": _alert_prov(db)}


@router.put("/alerts/config")
def alerts_config_put(body: dict, db: Session = Depends(get_db)):
    from research.services import alerts
    try:
        alerts.save_config(db, body)
    except ValueError as e:
        raise an.BadRequest(str(e)) from e
    return alerts_config(db)


# ---------------------------------------------------------------- real FX (ECB reference rates)

def _refresh_fx(db: Session) -> dict:
    from research.market_data import fx
    try:
        return fx.refresh(db)
    except MarketDataError as e:
        db.rollback()
        return {"status": "failed", "error_code": e.code, "message": e.message}


@router.get("/fx/status")
def fx_status(db: Session = Depends(get_db)):
    from research.market_data import fx
    return fx.status(db)


@router.post("/fx/refresh")
def fx_refresh(db: Session = Depends(get_db)):
    from research.market_data import fx
    return {"result": _refresh_fx(db), **fx.status(db)}


# ---------------------------------------------------------------- European prices (EODHD)

class EuSymbolIn(BaseModel):
    ticker: str
    exchange: str


@router.get("/market-data/eu/status")
def eu_status(db: Session = Depends(get_db)):
    from research.market_data import eu_service
    return eu_service.status(db)


@router.post("/market-data/eu/refresh")
def eu_refresh(body: ForceIn | None = None, db: Session = Depends(get_db)):
    from research.market_data import eu_service
    out = eu_service.refresh_all(db, force=(body or ForceIn()).force)
    return {**out, "alerts": evaluate_alerts(db), "provenance": eu_service.status(db)["provenance"]}


@router.post("/market-data/eu/symbols")
def eu_add(body: EuSymbolIn, db: Session = Depends(get_db)):
    from research.market_data import eu_service
    r = eu_service.add_symbol(db, body.ticker, body.exchange.upper())
    return {**r, "status_detail": eu_service.status(db)}


@router.delete("/market-data/eu/symbols/{exchange}/{ticker}")
def eu_remove(exchange: str, ticker: str, db: Session = Depends(get_db)):
    from research.market_data import eu_service
    eu_service.remove_symbol(db, ticker, exchange.upper())
    return eu_service.status(db)


# ---------------------------------------------------------------- backtesting (Phase 7)

class BacktestIn(BaseModel):
    listing_id: int
    strategy: str
    mode: str = "single"
    params: dict | None = None
    commission_bps: float = 5.0
    slippage_bps: float = 10.0
    holdout_pct: float = 0.2
    folds: int = 3


def _bt_prov() -> dict:
    return {"source": "engine", "is_synthetic": None, "as_of": None, "exchange_timezone": None,
            "is_delayed": None, "delay_minutes": None, "stale": False}


@router.get("/backtest/strategies")
def backtest_strategies():
    from research.services import backtest
    return {**backtest.strategies(), "provenance": _bt_prov()}


@router.post("/backtest/run")
def backtest_run(body: BacktestIn, db: Session = Depends(get_db)):
    from research.services import backtest
    return backtest.run(db, body.listing_id, body.strategy, body.mode, body.params, body.commission_bps,
                        body.slippage_bps, body.holdout_pct, body.folds, get_settings(db)["default_sensitivity"])


class RotationBacktestIn(BaseModel):
    region: str = "us"
    benchmark: str | None = None
    data: str = "auto"
    strategy: str
    mode: str = "single"
    params: dict | None = None
    commission_bps: float = 5.0
    slippage_bps: float = 10.0
    holdout_pct: float = 0.2
    folds: int = 2


@router.get("/backtest/rotation/strategies")
def rotation_backtest_strategies():
    from research.services import backtest
    return {**backtest.rotation_strategies(), "provenance": _bt_prov()}


@router.post("/backtest/rotation/run")
def rotation_backtest_run(body: RotationBacktestIn, db: Session = Depends(get_db)):
    from research.services import backtest
    return backtest.run_rotation(db, body.region, body.benchmark, body.data, body.strategy, body.mode, body.params,
                                 body.commission_bps, body.slippage_bps, body.holdout_pct, body.folds)


@router.get("/backtest/runs")
def backtest_runs(db: Session = Depends(get_db)):
    from research.services import backtest
    return backtest.list_runs(db)


@router.get("/backtest/runs/{run_id}")
def backtest_get(run_id: int, db: Session = Depends(get_db)):
    from research.services import backtest
    return backtest.get(db, run_id)


@router.delete("/backtest/runs/{run_id}")
def backtest_delete(run_id: int, db: Session = Depends(get_db)):
    from research.services import backtest
    backtest.delete(db, run_id)
    return backtest.list_runs(db)


# ---------------------------------------------------------------- sector rotation

def _sec_prov() -> dict:
    return {"source": "configuration", "is_synthetic": None, "as_of": None, "exchange_timezone": None,
            "is_delayed": None, "delay_minutes": None, "stale": False}


@router.get("/sectors")
def sectors_dashboard(benchmark: str | None = None, timeframe: str = "3m", data: str = "auto", region: str = "us",
                      db: Session = Depends(get_db)):
    from research.services import sectors
    return sectors.dashboard(db, region, benchmark, timeframe, data)


@router.get("/sectors/score-weights")
def sectors_weights(db: Session = Depends(get_db)):
    from research.engine import rotation
    from research.services import sectors
    return {"weights": sectors.get_weights(db), "defaults": rotation.DEFAULT_WEIGHTS, "labels": rotation.WEIGHT_LABELS,
            "provenance": _sec_prov()}


@router.put("/sectors/score-weights")
def sectors_weights_put(body: dict, db: Session = Depends(get_db)):
    from research.services import sectors
    try:
        sectors.save_weights(db, body)
    except ValueError as e:
        raise an.BadRequest(str(e)) from e
    return sectors_weights(db)


@router.get("/sectors/holdings")
def sectors_holdings_status(region: str = "us", db: Session = Depends(get_db)):
    from research.services import sectors
    return {"holdings": sectors.holdings_status(db, region), "provenance": {**_sec_prov(), "source": "issuer", "is_synthetic": False}}


@router.post("/sectors/holdings/refresh")
def sectors_holdings_refresh(ticker: str | None = None, region: str | None = None, db: Session = Depends(get_db)):
    from research.data.sectors import REGIONS, region_of
    from research.services import sectors
    if region is not None and region not in REGIONS:
        raise an.BadRequest(f"unknown region '{region}'")
    reg = region_of(ticker.upper()) if ticker else (REGIONS[region] if region else None)
    out = sectors.refresh_holdings(db, [ticker.upper()] if ticker else None, region_id=reg.id if reg else None)
    return {**out, "holdings": sectors.holdings_status(db, reg.id if reg else "us"),
            "provenance": {**_sec_prov(), "source": "issuer", "is_synthetic": False}}


@router.post("/sectors/{ticker}/constituents/download")
def sectors_constituents_download(ticker: str, db: Session = Depends(get_db)):
    from research.services import sectors
    out = sectors.download_constituents(db, ticker)
    return {**out, "alerts": evaluate_alerts(db), "provenance": {**_sec_prov(), "source": "tiingo", "is_synthetic": False}}


@router.get("/sectors/{ticker}")
def sectors_detail(ticker: str, benchmark: str | None = None, timeframe: str = "3m", data: str = "auto",
                   region: str = "us", db: Session = Depends(get_db)):
    from research.services import sectors
    return sectors.sector_detail(db, ticker, region, benchmark, timeframe, data)
