"""European end-of-day prices via EODHD (PHASE_2B_TASK.md §1).

Real EU listings live in namespace "real" with provider_symbol like "SAP.XETRA". The engine
uses adjusted OHLC (O/H/L scaled by adjusted_close / close); raw close is stored alongside.
Because adjusted history changes with every dividend or split, a change in the adjustment
factor on overlapping bars triggers a full re-download (as EODHD's documentation advises).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from research.core.calendars import eu_holidays
from research.core.config import settings
from research.db import models as m

from .eodhd import EODHD_EXCHANGES, PROVIDER, UNVERIFIED_SUFFIXES, EodhdClient, eodhd_symbol
from .tiingo import MarketDataError, dec

HISTORY_YEARS = 5
OVERLAP_DAYS = 7
MINUTE_BUDGET = 900          # EODHD: 1,000 requests/minute
PUBLISH_DELAY = timedelta(hours=3)  # EODHD: "each stock exchange 2-3 hours after the market closes"
FACTOR_TOLERANCE = 1e-6
USER_KEY = "tracked_eu_symbols"

IBKR_EU = {"AEB": "XAMS", "IBIS": "XETR", "IBIS2": "XETR", "EBS": "XSWX", "LSE": "XLON", "LSEETF": "XLON", "SBF": "XPAR"}
EXCHANGE_INFO = {  # used only if the exchange row doesn't exist yet
    "XETR": ("Xetra", "Europe/Berlin", "EUR", "17:30"),
    "XAMS": ("Euronext Amsterdam", "Europe/Amsterdam", "EUR", "17:30"),
    "XSWX": ("SIX Swiss Exchange", "Europe/Zurich", "CHF", "17:30"),
    "XLON": ("London Stock Exchange", "Europe/London", "GBP", "16:30"),
    "XPAR": ("Euronext Paris", "Europe/Paris", "EUR", "17:30"),
}
# Exchange names as they appear in iShares holdings files -> MIC (only exchanges priced via EODHD)
HOLDINGS_EXCHANGES = {"Xetra": "XETR", "Deutsche Boerse Xetra": "XETR", "London Stock Exchange": "XLON",
                      "Euronext Amsterdam": "XAMS", "SIX Swiss Exchange": "XSWX", "Nyse Euronext - Euronext Paris": "XPAR"}


def configured() -> bool:
    return bool(settings.eodhd_api_key and settings.eodhd_api_key.get_secret_value())


def default_client() -> EodhdClient:
    if not configured():
        raise MarketDataError("not_configured", "EODHD_API_KEY is not set in .env. Add it and restart the app.")
    return EodhdClient(settings.eodhd_api_key.get_secret_value())


def last_completed_session(mic: str, now: datetime | None = None) -> date:
    """Latest trading day of `mic` whose EODHD end-of-day bar should be published."""
    _, tzname, _, close = EXCHANGE_INFO[mic]
    tz = ZoneInfo(tzname)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    hh, mm = (int(x) for x in close.split(":"))
    published = datetime.combine(local.date(), time(hh, mm), tzinfo=tz) + PUBLISH_DELAY
    d = local.date() if local >= published else local.date() - timedelta(days=1)
    hol = eu_holidays(mic)
    while not np.is_busday(np.datetime64(d, "D"), holidays=hol):
        d -= timedelta(days=1)
    return d


# --------------------------------------------------------------------------- tracking

def _user_symbols(db: Session) -> list[dict]:
    row = db.get(m.AppSetting, USER_KEY)
    return list(row.value_json or []) if row else []


def _save_user_symbols(db: Session, items: list[dict]) -> None:
    uniq = {(x["ticker"], x["mic"]): x for x in items}
    val = sorted(uniq.values(), key=lambda x: (x["mic"], x["ticker"]))
    row = db.get(m.AppSetting, USER_KEY)
    if row is None:
        db.add(m.AppSetting(key=USER_KEY, value_json=val))
    else:
        row.value_json = val


def broker_eu_targets(db: Session) -> list[dict]:
    from research.broker.service import last_success
    run = last_success(db)
    if run is None:
        return []
    out = {}
    for p in db.scalars(select(m.BrokerPositionRow).where(m.BrokerPositionRow.sync_run_id == run.id)).all():
        mic = IBKR_EU.get((p.listing_exchange or "").upper())
        if mic:
            out[(p.symbol.upper(), mic)] = {"ticker": p.symbol.upper(), "mic": mic, "name": p.description,
                                            "isin": p.isin, "currency": p.currency, "origin": "ibkr"}
    return list(out.values())


def all_targets(db: Session) -> list[dict]:
    from research.data.sectors import EU, EU_BENCHMARK
    t = [{"ticker": e.ticker, "mic": e.mic, "name": e.name, "isin": e.isin, "currency": "EUR", "origin": "sector",
          "asset_class": "etf", "sector": None if e is EU_BENCHMARK else e.sector} for e in (EU_BENCHMARK, *EU.etfs)]
    t += broker_eu_targets(db)
    t += [{**x, "name": None, "isin": None, "currency": None, "origin": "user"} for x in _user_symbols(db)]
    seen, out = set(), []
    for x in t:
        k = (x["ticker"], x["mic"])
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def find_listing(db: Session, ticker: str, mic: str) -> m.Listing | None:
    return db.scalar(select(m.Listing).where(m.Listing.namespace == "real", m.Listing.exchange_mic == mic,
                                             m.Listing.provider_symbol == eodhd_symbol(ticker, mic)).limit(1))


def ensure_listing(db: Session, ticker: str, mic: str, name: str | None, isin: str | None,
                   currency: str | None, asset_class: str = "stock", sector: str | None = None) -> m.Listing:
    lst = find_listing(db, ticker, mic)
    if lst:
        return lst
    ex = db.get(m.Exchange, mic)
    if ex is None:
        n, tz, ccy, close = EXCHANGE_INFO[mic]
        ex = m.Exchange(mic=mic, name=n, timezone=tz, currency=ccy, close_time=close)
        db.add(ex)
        db.flush()
    inst = db.scalar(select(m.Instrument).where(m.Instrument.isin == isin)) if isin else None
    if inst is None:
        inst = m.Instrument(isin=isin, name=name or ticker, asset_class=asset_class, sector=sector, tracks=None, is_holdable=True)
        db.add(inst)
        db.flush()
    lst = m.Listing(instrument_id=inst.id, exchange_mic=mic, ticker=ticker.upper(), currency=currency or ex.currency,
                    is_benchmark=False, namespace="real", provider_symbol=eodhd_symbol(ticker, mic))
    db.add(lst)
    db.flush()
    return lst


# --------------------------------------------------------------------------- budget

def requests_used(db: Session) -> dict:
    now = datetime.now(timezone.utc)

    def count(since):
        return db.scalar(select(func.count()).select_from(m.ProviderRequest)
                         .where(m.ProviderRequest.provider == PROVIDER, m.ProviderRequest.at >= since)) or 0
    return {"last_minute": count(now - timedelta(minutes=1)), "last_day": count(now - timedelta(days=1)),
            "minute_budget": MINUTE_BUDGET, "daily_budget": settings.eodhd_daily_budget}


def _budget_ok(db: Session) -> bool:
    u = requests_used(db)
    return u["last_minute"] < MINUTE_BUDGET and u["last_day"] < settings.eodhd_daily_budget


def _call(db: Session, symbol: str, fn):
    ok = False
    try:
        res = fn()
        ok = True
        return res
    finally:
        db.add(m.ProviderRequest(provider=PROVIDER, symbol=symbol[:32], ok=ok, at=datetime.now(timezone.utc)))
        db.commit()


# --------------------------------------------------------------------------- refresh

def _store(db: Session, listing_id: int, bars, replace_from: date | None) -> None:
    q = delete(m.PriceBar).where(m.PriceBar.listing_id == listing_id)
    if replace_from is not None:
        q = q.where(m.PriceBar.date >= replace_from)
    db.execute(q)
    now = datetime.now(timezone.utc)
    for b in bars:
        db.add(m.PriceBar(listing_id=listing_id, interval="1d", date=b.date, open=dec(b.open), high=dec(b.high),
                          low=dec(b.low), close=dec(b.close), adj_close=dec(b.close), volume=b.volume,
                          adjustment="split_dividend", raw_close=dec(b.raw_close), raw_volume=None,
                          div_cash=None, split_factor=None, source=PROVIDER, is_synthetic=False,
                          is_delayed=False, delay_minutes=0, ingested_at=now))
    db.flush()


def _factor_changed(db: Session, listing_id: int, bars) -> bool:
    """True if any overlapping stored bar's adjustment factor (close / raw_close) differs."""
    new = {b.date: b.close / b.raw_close for b in bars}
    for pb in db.scalars(select(m.PriceBar).where(m.PriceBar.listing_id == listing_id,
                                                  m.PriceBar.date.in_(list(new)))).all():
        if pb.raw_close and abs(float(pb.close) / float(pb.raw_close) - new[pb.date]) > FACTOR_TOLERANCE * max(1.0, new[pb.date]):
            return True
    return False


def refresh_listing(db: Session, client: EodhdClient, lst: m.Listing, force: bool = False,
                    now: datetime | None = None) -> dict:
    session_day = last_completed_session(lst.exchange_mic, now)
    sym = lst.provider_symbol
    last = db.scalar(select(func.max(m.PriceBar.date)).where(m.PriceBar.listing_id == lst.id))
    if force:
        last = None
    elif last is not None and last >= session_day:
        return {"status": "up_to_date", "bars_added": 0, "last_date": last.isoformat()}
    if not _budget_ok(db):
        return {"status": "skipped_budget", "bars_added": 0, "last_date": last.isoformat() if last else None,
                "message": "EODHD request budget reached for now (EODHD_DAILY_BUDGET). The rest will update later."}
    full_start = session_day - timedelta(days=int(365.25 * HISTORY_YEARS))
    closed = lambda bars: [b for b in bars if b.date <= session_day]  # noqa: E731 - never store an unfinished session
    if last is None:
        bars = closed(_call(db, sym, lambda: client.daily(sym, full_start)))
        _store(db, lst.id, bars, None)
        n, mode = len(bars), "full"
    else:
        start = last - timedelta(days=OVERLAP_DAYS)
        bars = closed(_call(db, sym, lambda: client.daily(sym, start)))
        if _factor_changed(db, lst.id, bars) and _budget_ok(db):
            bars = closed(_call(db, sym, lambda: client.daily(sym, full_start)))
            _store(db, lst.id, bars, None)
            n, mode = len([b for b in bars if b.date > last]), "full (corporate action)"
        else:
            if bars:
                _store(db, lst.id, bars, start)
            n, mode = len([b for b in bars if b.date > last]), "incremental"
    db.commit()
    from research.services.analysis import persist_latest
    persist_latest(db, lst.id)
    db.commit()
    new_last = db.scalar(select(func.max(m.PriceBar.date)).where(m.PriceBar.listing_id == lst.id))
    return {"status": "updated" if n else "no_new_data", "bars_added": n, "mode": mode,
            "last_date": new_last.isoformat() if new_last else None}


def refresh_all(db: Session, client: EodhdClient | None = None, force: bool = False, now: datetime | None = None) -> dict:
    client = client or default_client()
    results = []
    for t in all_targets(db):
        lst = ensure_listing(db, t["ticker"], t["mic"], t["name"], t["isin"], t["currency"],
                             t.get("asset_class", "stock"), t.get("sector"))
        db.commit()
        try:
            r = refresh_listing(db, client, lst, force=force, now=now)
        except MarketDataError as e:
            db.rollback()
            r = {"status": "failed", "error_code": e.code, "message": e.message, "bars_added": 0}
        results.append({"ticker": t["ticker"], "exchange": t["mic"], "symbol": lst.provider_symbol,
                        "origin": t["origin"], "listing_id": lst.id, **r})
        if r.get("error_code") in ("auth", "not_configured", "plan_limit"):
            break
    stamp = {"at": datetime.now(timezone.utc).isoformat(),
             "updated": sum(r["status"] == "updated" for r in results),
             "failed": sum(r["status"] == "failed" for r in results)}
    row = db.get(m.AppSetting, "eodhd_last_refresh")
    if row is None:
        db.add(m.AppSetting(key="eodhd_last_refresh", value_json=stamp))
    else:
        row.value_json = stamp
    db.commit()
    return {"results": results, "usage": requests_used(db)}


def is_eu_listing(lst: m.Listing) -> bool:
    return lst.namespace == "real" and lst.exchange_mic in EODHD_EXCHANGES


def refresh_one(db: Session, lst: m.Listing, force: bool = False, client: EodhdClient | None = None) -> dict:
    client = client or default_client()
    try:
        r = refresh_listing(db, client, lst, force=force)
    except MarketDataError as e:
        db.rollback()
        return {"ticker": lst.ticker, "listing_id": lst.id, "status": "failed", "error_code": e.code,
                "message": e.message, "bars_added": 0, "usage": requests_used(db)}
    return {"ticker": lst.ticker, "listing_id": lst.id, **r, "usage": requests_used(db)}


def add_symbol(db: Session, ticker: str, mic: str, client: EodhdClient | None = None) -> dict:
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 12 or not all(c.isalnum() or c in ".- " for c in ticker):
        raise MarketDataError("bad_symbol", "Enter a ticker such as ASML, SAP or NESN.")
    if mic not in EODHD_EXCHANGES:
        raise MarketDataError("unsupported_exchange", f"Choose one of: {', '.join(EODHD_EXCHANGES)}.")
    client = client or default_client()
    lst = ensure_listing(db, ticker, mic, None, None, None)
    db.commit()
    try:
        r = refresh_listing(db, client, lst)
    except MarketDataError:
        # Don't keep an empty listing for a symbol EODHD doesn't know.
        if not db.scalar(select(m.PriceBar.id).where(m.PriceBar.listing_id == lst.id).limit(1)):
            db.delete(lst)
            db.commit()
        raise
    _save_user_symbols(db, _user_symbols(db) + [{"ticker": ticker, "mic": mic}])
    db.commit()
    return {"ticker": ticker, "exchange": mic, "symbol": lst.provider_symbol, "listing_id": lst.id, **r}


def remove_symbol(db: Session, ticker: str, mic: str) -> None:
    _save_user_symbols(db, [x for x in _user_symbols(db) if (x["ticker"], x["mic"]) != (ticker.upper(), mic)])
    db.commit()


def status(db: Session) -> dict:
    rows = []
    for t in all_targets(db):
        lst = find_listing(db, t["ticker"], t["mic"])
        last = db.scalar(select(func.max(m.PriceBar.date)).where(m.PriceBar.listing_id == lst.id)) if lst else None
        rows.append({"ticker": t["ticker"], "exchange": t["mic"], "symbol": eodhd_symbol(t["ticker"], t["mic"]),
                     "origin": t["origin"], "listing_id": lst.id if lst else None,
                     "last_date": last.isoformat() if last else None,
                     "expected_session": last_completed_session(t["mic"]).isoformat(),
                     "suffix_unverified": t["mic"] in UNVERIFIED_SUFFIXES})
    row = db.get(m.AppSetting, "eodhd_last_refresh")
    return {"provider": PROVIDER, "configured": configured(), "exchanges": EODHD_EXCHANGES,
            "unverified_suffixes": sorted(UNVERIFIED_SUFFIXES), "tracked": rows, "usage": requests_used(db),
            "last_refresh": row.value_json if row else None,
            "provenance": {"source": PROVIDER, "is_synthetic": False, "as_of": None, "exchange_timezone": "multiple",
                           "is_delayed": False, "delay_minutes": None, "stale": False, "data_type": "end_of_day"}}
