"""Real market data (Tiingo, US end-of-day) — tracking, refresh, and budget control.

Real listings live in namespace "real" and never share rows with the synthetic demo.
Prices used by the engine are Tiingo's split/dividend-adjusted OHLCV; raw close/volume
and corporate-action fields are stored alongside.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from research.core.calendars import US_MICS, us_holidays
from research.core.config import settings
from research.db import models as m

from .tiingo import PROVIDER, MarketDataError, TiingoClient, dec, to_tiingo_symbol

HISTORY_YEARS = 5
HOURLY_BUDGET = 45   # Tiingo free: 50/hour — keep a safety margin
DAILY_BUDGET = 950   # Tiingo free: 1,000/day
OVERLAP_DAYS = 7

# US market benchmarks tracked with real data (ETF proxies for the indices).
BENCHMARK_PROXIES = {"SPX": ("SPY", "ARCX", "S&P 500"), "NDX": ("QQQ", "XNAS", "Nasdaq-100"),
                     "DJI": ("DIA", "ARCX", "Dow Jones Industrial Average"), "RUT": ("IWM", "ARCX", "Russell 2000")}
TIINGO_EXCHANGES = {"NASDAQ": "XNAS", "NYSE": "XNYS", "NYSE ARCA": "ARCX", "NYSE MKT": "XASE",
                    "AMEX": "XASE", "BATS": "BATS", "NYSE NAT": "XNYS"}
US_EXCHANGE_NAMES = {"XNAS": "Nasdaq", "XNYS": "New York Stock Exchange", "ARCX": "NYSE Arca",
                     "XASE": "NYSE American", "BATS": "Cboe BZX"}
IBKR_US = {"NASDAQ": "XNAS", "NYSE": "XNYS", "ARCA": "ARCX", "AMEX": "XASE", "BATS": "BATS"}

ET = ZoneInfo("America/New_York")


def configured() -> bool:
    return bool(settings.tiingo_api_key and settings.tiingo_api_key.get_secret_value())


def default_client() -> TiingoClient:
    if not configured():
        raise MarketDataError("not_configured", "TIINGO_API_KEY is not set in .env. Add it and restart the app.")
    return TiingoClient(settings.tiingo_api_key.get_secret_value())


def last_completed_session(now: datetime | None = None) -> date:
    """Most recent US trading day whose end-of-day data should be available (after ~18:00 ET)."""
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    d = now.date() if now.time() >= time(18, 0) else now.date() - timedelta(days=1)
    hol = us_holidays()
    while not np.is_busday(np.datetime64(d, "D"), holidays=hol):
        d -= timedelta(days=1)
    return d


# --------------------------------------------------------------------------- tracked symbols

def _user_symbols(db: Session) -> list[str]:
    row = db.get(m.AppSetting, "tracked_symbols")
    return list(row.value_json or []) if row else []


def _save_user_symbols(db: Session, syms: list[str]) -> None:
    row = db.get(m.AppSetting, "tracked_symbols")
    if row is None:
        db.add(m.AppSetting(key="tracked_symbols", value_json=sorted(set(syms))))
    else:
        row.value_json = sorted(set(syms))


def broker_us_targets(db: Session) -> list[dict]:
    from research.broker.service import last_success
    run = last_success(db)
    if run is None:
        return []
    out = {}
    for p in db.scalars(select(m.BrokerPositionRow).where(m.BrokerPositionRow.sync_run_id == run.id)).all():
        mic = IBKR_US.get((p.listing_exchange or "").upper())
        if mic and p.currency == "USD":
            out[(to_tiingo_symbol(p.symbol), mic)] = {"ticker": p.symbol, "mic": mic, "name": p.description,
                                                      "isin": p.isin, "origin": "ibkr"}
    return list(out.values())


def all_targets(db: Session) -> list[dict]:
    t = [{"ticker": sym, "mic": mic, "name": f"{name} ETF proxy", "isin": None, "origin": "benchmark"}
         for sym, mic, name in BENCHMARK_PROXIES.values()]
    from research.data.sectors import US as US_SECTORS
    t += [{"ticker": e.ticker, "mic": e.mic, "name": e.name, "isin": None, "origin": "sector", "tracks": f"{e.sector} sector",
           "sector": e.sector} for e in US_SECTORS.etfs]
    t += broker_us_targets(db)
    for lst in db.scalars(select(m.Listing).where(m.Listing.namespace == "real",
                                                  m.Listing.exchange_mic.in_(US_MICS))).all():  # EU listings use EODHD
        if lst.ticker in _user_symbols(db):
            t.append({"ticker": lst.ticker, "mic": lst.exchange_mic, "name": lst.instrument.name, "isin": lst.instrument.isin, "origin": "user"})
    seen, out = set(), []
    for x in t:
        k = (to_tiingo_symbol(x["ticker"]), x["mic"])
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def find_real_listing(db: Session, ticker: str, mic: str | None = None) -> m.Listing | None:
    q = select(m.Listing).where(m.Listing.namespace == "real",
                                m.Listing.provider_symbol == to_tiingo_symbol(ticker))
    if mic:
        q = q.where(m.Listing.exchange_mic == mic)
    return db.scalar(q.limit(1))


def ensure_listing(db: Session, ticker: str, mic: str, name: str | None, isin: str | None,
                   is_benchmark: bool = False, tracks: str | None = None, asset_class: str | None = None,
                   sector: str | None = None) -> m.Listing:
    lst = find_real_listing(db, ticker, mic)
    if lst:
        return lst
    if db.get(m.Exchange, mic) is None:
        db.add(m.Exchange(mic=mic, name=US_EXCHANGE_NAMES.get(mic, mic), timezone="America/New_York",
                          currency="USD", close_time="16:00"))
        db.flush()
    inst = db.scalar(select(m.Instrument).where(m.Instrument.isin == isin)) if isin else None
    if inst is None:
        inst = m.Instrument(isin=isin, name=name or ticker,
                            asset_class=asset_class or ("etf" if is_benchmark else "stock"),
                            sector=sector, tracks=tracks, is_holdable=True)
        db.add(inst)
        db.flush()
    lst = m.Listing(instrument_id=inst.id, exchange_mic=mic, ticker=ticker, currency="USD",
                    is_benchmark=is_benchmark, namespace="real", provider_symbol=to_tiingo_symbol(ticker))
    db.add(lst)
    db.flush()
    return lst


# --------------------------------------------------------------------------- budget

def requests_used(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    def count(since):
        return db.scalar(select(func.count()).select_from(m.ProviderRequest)
                         .where(m.ProviderRequest.provider == PROVIDER, m.ProviderRequest.at >= since)) or 0
    return {"last_hour": count(now - timedelta(hours=1)), "last_day": count(now - timedelta(days=1)),
            "hourly_budget": HOURLY_BUDGET, "daily_budget": DAILY_BUDGET}


def _budget_ok(db: Session) -> bool:
    u = requests_used(db)
    return u["last_hour"] < HOURLY_BUDGET and u["last_day"] < DAILY_BUDGET


def _log(db: Session, symbol: str, ok: bool) -> None:
    db.add(m.ProviderRequest(provider=PROVIDER, symbol=symbol, ok=ok, at=datetime.now(timezone.utc)))
    db.commit()


def _call(db: Session, symbol: str, fn):
    try:
        res = fn()
    except MarketDataError:
        _log(db, symbol, False)
        raise
    _log(db, symbol, True)
    return res


# --------------------------------------------------------------------------- refresh

def _last_bar_date(db: Session, listing_id: int) -> date | None:
    return db.scalar(select(func.max(m.PriceBar.date)).where(m.PriceBar.listing_id == listing_id))


def _store(db: Session, listing_id: int, bars, replace_from: date | None) -> int:
    if replace_from is None:
        db.execute(delete(m.PriceBar).where(m.PriceBar.listing_id == listing_id))
    else:
        db.execute(delete(m.PriceBar).where(m.PriceBar.listing_id == listing_id, m.PriceBar.date >= replace_from))
    now = datetime.now(timezone.utc)
    for b in bars:
        db.add(m.PriceBar(listing_id=listing_id, interval="1d", date=b.date, open=dec(b.open), high=dec(b.high),
                          low=dec(b.low), close=dec(b.close), adj_close=dec(b.close), volume=b.volume,
                          adjustment="split_dividend", raw_close=dec(b.raw_close), raw_volume=b.raw_volume,
                          div_cash=dec(b.div_cash), split_factor=dec(b.split_factor), source=PROVIDER,
                          is_synthetic=False, is_delayed=False, delay_minutes=0, ingested_at=now))
    db.flush()
    return len(bars)


def _closed(bars, session_day: date):
    """Drop any bar dated after the last completed session (a provider may return today's partial bar)."""
    return [b for b in bars if b.date <= session_day]


def refresh_listing(db: Session, client: TiingoClient, lst: m.Listing, today_session: date, force: bool = False) -> dict:
    """Update one listing. force=True re-downloads the full history even if it looks up to date
    (useful if the provider corrected data). Still respects the request budget."""
    sym = lst.provider_symbol or to_tiingo_symbol(lst.ticker)
    last = _last_bar_date(db, lst.id)
    if force:
        last = None
    elif last is not None and last >= today_session:
        return {"status": "up_to_date", "bars_added": 0, "last_date": last.isoformat()}
    if not _budget_ok(db):
        return {"status": "skipped_budget", "bars_added": 0, "last_date": last.isoformat() if last else None,
                "message": "Free-plan request budget reached for now. The rest will update on the next refresh."}
    full_start = today_session - timedelta(days=int(365.25 * HISTORY_YEARS))
    if last is None:
        bars = _closed(_call(db, sym, lambda: client.daily(sym, full_start)), today_session)
        n = _store(db, lst.id, bars, None)
        mode = "full"
    else:
        start = last - timedelta(days=OVERLAP_DAYS)
        bars = _closed(_call(db, sym, lambda: client.daily(sym, start)), today_session)
        new = [b for b in bars if b.date > last]
        if any(b.div_cash > 0 or b.split_factor != 1.0 for b in new) and _budget_ok(db):
            # A dividend/split changes the whole adjusted history: re-download it.
            bars = _closed(_call(db, sym, lambda: client.daily(sym, full_start)), today_session)
            n = _store(db, lst.id, bars, None)
            mode = "full (corporate action)"
        else:
            if bars:
                _store(db, lst.id, bars, start)
            n = len(new)
            mode = "incremental"
    db.commit()
    from research.services.analysis import persist_latest
    persist_latest(db, lst.id)
    db.commit()
    new_last = _last_bar_date(db, lst.id)
    return {"status": "updated" if n else "no_new_data", "bars_added": n, "mode": mode,
            "last_date": new_last.isoformat() if new_last else None}


def refresh_all(db: Session, client: TiingoClient | None = None, only: list[str] | None = None, force: bool = False) -> dict:
    client = client or default_client()
    session_day = last_completed_session()
    results = []
    for t in all_targets(db):
        if only and to_tiingo_symbol(t["ticker"]) not in {to_tiingo_symbol(o) for o in only}:
            continue
        proxy_for = next((name for _, (s, _, name) in BENCHMARK_PROXIES.items() if s == t["ticker"]), None)
        lst = ensure_listing(db, t["ticker"], t["mic"], t["name"], t["isin"],
                             is_benchmark=t["origin"] == "benchmark", tracks=proxy_for or t.get("tracks"),
                             asset_class="etf" if t["origin"] in ("benchmark", "sector") else None,
                             sector=t.get("sector"))
        db.commit()
        try:
            r = refresh_listing(db, client, lst, session_day, force=force)
        except MarketDataError as e:
            db.rollback()
            r = {"status": "failed", "error_code": e.code, "message": e.message, "bars_added": 0}
            if e.code in ("auth", "not_configured"):
                results.append({"ticker": t["ticker"], "origin": t["origin"], "listing_id": lst.id, **r})
                break
        results.append({"ticker": t["ticker"], "origin": t["origin"], "listing_id": lst.id, **r})
    row = db.get(m.AppSetting, "market_data_last_refresh")
    stamp = {"at": datetime.now(timezone.utc).isoformat(), "session": session_day.isoformat(),
             "updated": sum(r["status"] == "updated" for r in results),
             "failed": sum(r["status"] == "failed" for r in results)}
    if row is None:
        db.add(m.AppSetting(key="market_data_last_refresh", value_json=stamp))
    else:
        row.value_json = stamp
    db.commit()
    return {"session": session_day.isoformat(), "results": results, "usage": requests_used(db)}


def refresh_one(db: Session, listing_id: int, force: bool = False, client: TiingoClient | None = None) -> dict:
    lst = db.get(m.Listing, listing_id)
    if lst is None:
        raise MarketDataError("not_found", f"Listing {listing_id} not found.")
    if lst.namespace != "real":
        raise MarketDataError("synthetic", "This is synthetic demo data; there is nothing to download. "
                                           "Real prices come from Tiingo (US) and EODHD (Europe).")
    from . import eu_service
    if eu_service.is_eu_listing(lst):
        return eu_service.refresh_one(db, lst, force=force)
    client = client or default_client()
    try:
        r = refresh_listing(db, client, lst, last_completed_session(), force=force)
    except MarketDataError as e:
        db.rollback()
        return {"ticker": lst.ticker, "listing_id": lst.id, "status": "failed", "error_code": e.code,
                "message": e.message, "bars_added": 0, "usage": requests_used(db)}
    return {"ticker": lst.ticker, "listing_id": lst.id, **r, "usage": requests_used(db)}


def add_symbol(db: Session, ticker: str, client: TiingoClient | None = None) -> dict:
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 12 or not all(c.isalnum() or c in ".- " for c in ticker):
        raise MarketDataError("bad_symbol", "Enter a US ticker such as MSFT or BRK.B.")
    client = client or default_client()
    existing = find_real_listing(db, ticker)
    if existing is None:
        if not _budget_ok(db):
            raise MarketDataError("budget", "Free-plan request budget reached. Try again later.")
        meta = _call(db, ticker, lambda: client.meta(ticker))
        mic = TIINGO_EXCHANGES.get((meta.exchange_code or "").upper())
        if mic is None:
            raise MarketDataError("unsupported_exchange",
                                  f"{ticker} trades on '{meta.exchange_code or 'unknown'}'. Only US exchange-listed stocks/ETFs are supported.")
        existing = ensure_listing(db, ticker, mic, meta.name, None)
        db.commit()
    syms = _user_symbols(db)
    if existing.ticker not in syms:
        _save_user_symbols(db, syms + [existing.ticker])
        db.commit()
    r = refresh_listing(db, client, existing, last_completed_session())
    return {"ticker": existing.ticker, "listing_id": existing.id, **r}


def remove_symbol(db: Session, ticker: str) -> None:
    _save_user_symbols(db, [s for s in _user_symbols(db) if s != ticker.strip().upper()])
    db.commit()


def status(db: Session) -> dict:
    rows = []
    for t in all_targets(db):
        lst = find_real_listing(db, t["ticker"], t["mic"])
        last = _last_bar_date(db, lst.id) if lst else None
        n = db.scalar(select(func.count()).select_from(m.PriceBar).where(m.PriceBar.listing_id == lst.id)) if lst else 0
        rows.append({"ticker": t["ticker"], "exchange": t["mic"], "origin": t["origin"],
                     "listing_id": lst.id if lst else None, "bars": n, "last_date": last.isoformat() if last else None})
    lr = db.get(m.AppSetting, "market_data_last_refresh")
    return {"provider": PROVIDER, "configured": configured(), "expected_session": last_completed_session().isoformat(),
            "tracked": rows, "usage": requests_used(db), "last_refresh": lr.value_json if lr else None,
            "limits_note": "Tiingo free plan: 50 requests/hour, 1,000/day, 500 symbols/month, personal use only."}


def real_listing_for_position(db: Session, p: m.BrokerPositionRow) -> m.Listing | None:
    """The real-data listing (Tiingo US or EODHD Europe) for an IBKR position, if one exists."""
    exch = (p.listing_exchange or "").upper()
    mic = IBKR_US.get(exch)
    if mic and p.currency == "USD":
        return find_real_listing(db, p.symbol, mic)
    from . import eu_service
    mic = eu_service.IBKR_EU.get(exch)
    return eu_service.find_listing(db, p.symbol, mic) if mic else None
