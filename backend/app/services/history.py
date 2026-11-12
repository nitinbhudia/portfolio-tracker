"""Daily price history for your stocks and the performance views built on it (P/L over time, value vs cost, monthly P/L).

Prices come from Tiingo (US tickers, free key in .env as TIINGO_API_KEY) or from a CSV you upload per stock (for listings
Tiingo doesn't cover, e.g. European ones). Tiingo's free plan allows about 50 requests an hour, so a full download runs in
the background and pauses for the hour when Tiingo says the limit is reached; progress is kept, so it resumes.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.engine import history as H
from app.engine import indexcsv as IC
from app.engine.fx import USER_AGENT

from . import portfolio as P
from .portfolio import BadRequest, NotFound

TIINGO = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
LEAD_DAYS = 7  # fetch a little before the first purchase
SETTING = "price_history_job"


class RateLimited(RuntimeError):
    pass


class TickerNotFound(RuntimeError):
    pass


class FetchError(RuntimeError):
    pass


def tiingo_key() -> str | None:
    return os.environ.get("TIINGO_API_KEY") or os.environ.get("TIINGO_TOKEN") or None


def fetch_tiingo(ticker: str, start: date, end: date, client: httpx.Client | None = None) -> list[tuple[date, float, float]]:
    """Daily unadjusted closes and split factors. Raises RateLimited, TickerNotFound or FetchError."""
    key = tiingo_key()
    if not key:
        raise FetchError("No Tiingo key: add TIINGO_API_KEY=… to the app's .env file and restart the app.")
    http = client or httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT})
    try:
        r = http.get(TIINGO.format(ticker=ticker.lower()), params={"startDate": start.isoformat(), "endDate": end.isoformat(),
                                                                    "format": "json", "resampleFreq": "daily"},
                     headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise FetchError(f"Couldn't reach Tiingo ({type(e).__name__}).") from e
    text = r.text[:300]
    if r.status_code == 429 or "allocation" in text.lower() and r.status_code >= 400:
        raise RateLimited(text or "rate limit")
    if r.status_code in (401, 403):
        raise FetchError("Tiingo rejected the key. Check TIINGO_API_KEY in the app's .env file.")
    if r.status_code == 404 or "not found" in text.lower() and r.status_code >= 400:
        raise TickerNotFound(f"Tiingo doesn't know the ticker {ticker}.")
    if r.status_code >= 400:
        raise FetchError(f"Tiingo answered {r.status_code}: {text}")
    try:
        rows = r.json()
    except ValueError as e:
        raise FetchError("Tiingo sent something that isn't price data.") from e
    if isinstance(rows, dict):  # an error message in a 200
        msg = str(rows.get("detail") or rows)
        if "allocation" in msg.lower() or "limit" in msg.lower():
            raise RateLimited(msg)
        raise TickerNotFound(msg) if "not found" in msg.lower() else FetchError(msg[:300])
    out = []
    for x in rows:
        try:
            out.append((date.fromisoformat(str(x["date"])[:10]), float(x["close"]), float(x.get("splitFactor") or 1.0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


FETCH = fetch_tiingo  # replaced in tests


# ---------------------------------------------------------------- what to fetch

def _valuation_end(db: Session, st) -> date:
    """The latest of: the workbook date, the last trade, the last price entered or downloaded (never in the future)."""
    cands = [P.as_of(st), max((t.date for t in st["rb"].trades), default=P.as_of(st))]
    cands += [d for d in (db.scalar(select(func.max(m.StockPrice.date))), db.scalar(select(func.max(m.Price.date)))) if d]
    return min(max(cands), date.today())


def pools(db: Session) -> list[dict]:
    """Every stock pool you have traded: dates held, ticker, and where its price history comes from."""
    st = P._need(db)
    end = date.today()
    info: dict[str, dict] = {}
    for t in st["rb"].trades:
        x = info.setdefault(t.pool, {"pool": t.pool, "stock": t.stock, "group_key": t.stock_key, "currency": t.currency,
                                     "pence": t.scale == 0.01, "first": t.date, "last": t.date, "shares": 0.0, "trades": []})
        x["first"], x["last"] = min(x["first"], t.date), max(x["last"], t.date)
        x["shares"] += t.shares if t.kind == "buy" else -t.shares
        x["trades"].append(t)
    tickers = st["tickers"]
    for x in info.values():
        x["open"] = x["shares"] > 1e-9
        x["ticker"] = tickers.get(x["group_key"]) if x["currency"] == "USD" else None
        x["need_from"] = x["first"] - timedelta(days=LEAD_DAYS)
        x["need_to"] = end if x["open"] else x["last"]
    return sorted(info.values(), key=lambda x: x["stock"].lower())


def _wanted(db: Session) -> dict[str, tuple[date, date]]:
    """ticker -> date range to fetch (several pools can share a ticker, e.g. names merged later)."""
    out: dict[str, tuple[date, date]] = {}
    for x in pools(db):
        if not x["ticker"]:
            continue
        a, b = out.get(x["ticker"], (x["need_from"], x["need_to"]))
        out[x["ticker"]] = (min(a, x["need_from"]), max(b, x["need_to"]))
    return out


def queue(db: Session) -> list[tuple[str, date, date]]:
    """(ticker, from, to) still to download."""
    done = {f.series: f for f in db.scalars(select(m.PriceFetch))}
    q = []
    for tk, (a, b) in sorted(_wanted(db).items()):
        f = done.get(tk)
        if f is None or f.status == "error" or f.fetched_from is None:
            q.append((tk, a, b))
        elif f.status == "not_found":
            continue
        elif f.fetched_from > a:
            q.append((tk, a, b))
        elif f.fetched_to < b - timedelta(days=1):
            q.append((tk, f.fetched_to - timedelta(days=5), b))
    return q


def _store(db: Session, series: str, rows: list[tuple[date, float, float]]) -> None:
    if not rows:
        return
    a, b = min(r[0] for r in rows), max(r[0] for r in rows)
    db.execute(delete(m.StockPrice).where(m.StockPrice.series == series, m.StockPrice.date >= a, m.StockPrice.date <= b))
    for d, c, s in rows:
        db.add(m.StockPrice(series=series, date=d, close=c, split=s))


def _mark(db: Session, series: str, status: str, a: date | None = None, b: date | None = None, msg: str | None = None):
    f = db.get(m.PriceFetch, series) or m.PriceFetch(series=series, status=status)
    db.add(f)
    f.status, f.message = status, msg
    if a is not None:
        f.fetched_from = min(f.fetched_from, a) if f.fetched_from else a
    if b is not None:
        f.fetched_to = max(f.fetched_to, b) if f.fetched_to else b
    if status == "ok":
        f.message = None


def _job(db: Session) -> dict:
    row = db.get(m.Setting, SETTING)
    return dict(row.value) if row else {}


def _set_job(db: Session, **kw) -> None:
    row = db.get(m.Setting, SETTING)
    v = dict(row.value) if row else {}
    v.update(kw)
    if row is None:
        db.add(m.Setting(key=SETTING, value=v))
    else:
        row.value = v
    db.commit()


def run_batch(db: Session, limit: int | None = None) -> dict:
    """Download what's missing, until done, the limit, or Tiingo's hourly cap. Returns a summary."""
    if not tiingo_key():
        raise BadRequest("Add your Tiingo key to the app's .env file (TIINGO_API_KEY=…) and restart the app.")
    q = queue(db)
    got, failed, errors_in_a_row = 0, 0, 0
    for tk, a, b in q[:limit] if limit else q:
        try:
            rows = FETCH(tk, a, b)
        except RateLimited:
            until = datetime.now(timezone.utc) + timedelta(minutes=61)
            _set_job(db, waiting_until=until.isoformat(), message="Tiingo's hourly limit reached; continuing after a pause.")
            return {"fetched": got, "failed": failed, "remaining": len(queue(db)), "waiting_until": until.isoformat()}
        except TickerNotFound as e:
            _mark(db, tk, "not_found", msg=str(e)[:300])
            failed += 1
        except FetchError as e:
            _mark(db, tk, "error", msg=str(e)[:300])
            failed += 1
            errors_in_a_row += 1
            db.commit()
            if errors_in_a_row >= 3:
                _set_job(db, message=str(e)[:300])
                break
            continue
        else:
            _store(db, tk, rows)
            _mark(db, tk, "ok", a, b)
            got += 1
        errors_in_a_row = 0
        db.commit()
    _set_job(db, waiting_until=None, message=None, last_run=datetime.now(timezone.utc).isoformat())
    _invalidate()
    return {"fetched": got, "failed": failed, "remaining": len(queue(db)), "waiting_until": None}


# ---------------------------------------------------------------- background download

_JOB = {"thread": None, "stop": threading.Event()}
SLEEP = time.sleep  # replaced in tests


def _worker():
    while not _JOB["stop"].is_set():
        db = m.SessionLocal()
        try:
            res = run_batch(db)
        except Exception as e:  # noqa: BLE001  (keep the reason for the status line, never crash the app)
            _set_job(db, running=False, message=f"Download stopped: {e}"[:300])
            db.close()
            return
        if res["waiting_until"] is None:
            _set_job(db, running=False)
            db.close()
            return
        until = datetime.fromisoformat(res["waiting_until"])
        db.close()
        while datetime.now(timezone.utc) < until and not _JOB["stop"].is_set():
            SLEEP(5)


def start_download(db: Session) -> dict:
    if not tiingo_key():
        raise BadRequest("Add your Tiingo key to the app's .env file (TIINGO_API_KEY=…) and restart the app.")
    t = _JOB["thread"]
    if t is None or not t.is_alive():
        _ensure_fx(db)
        _JOB["stop"].clear()
        _set_job(db, running=True, started=datetime.now(timezone.utc).isoformat(), message=None, waiting_until=None)
        t = threading.Thread(target=_worker, name="price-history", daemon=True)
        _JOB["thread"] = t
        t.start()
    return status(db)


def stop_download(db: Session) -> dict:
    _JOB["stop"].set()
    _set_job(db, running=False, waiting_until=None, message="Stopped. Progress is kept; start again to continue.")
    return status(db)


def _ensure_fx(db: Session) -> None:
    """Bring exchange rates up to date, so foreign positions can be valued day by day."""
    st = P._need(db)
    curs = sorted({t.currency for t in st["rb"].trades} - {"USD", "EUR"})
    last = db.scalar(select(func.max(m.FxRate.date)).where(m.FxRate.currency == "USD"))
    if last is None or last < date.today() - timedelta(days=3):
        P.ensure_fx_for(db, curs, last or min(t.date for t in st["rb"].trades))


# ---------------------------------------------------------------- CSV per stock, tickers

def upload_csv(db: Session, pool: str, data: bytes) -> dict:
    if pool not in {x["pool"] for x in pools(db)}:
        raise NotFound(f"'{pool}' isn't one of your stocks")
    try:
        rows = IC.parse(data.decode("utf-8-sig", errors="replace"))
    except IC.CsvError as e:
        raise BadRequest(str(e)) from e
    series = f"csv:{pool}"
    db.execute(delete(m.StockPrice).where(m.StockPrice.series == series))
    _store(db, series, [(d, v, 1.0) for d, v in rows])
    _mark(db, series, "ok", rows[0][0], rows[-1][0])
    db.commit()
    _invalidate()
    return {"pool": pool, "rows": len(rows), "first": rows[0][0].isoformat(), "last": rows[-1][0].isoformat()}


def delete_csv(db: Session, pool: str) -> dict:
    db.execute(delete(m.StockPrice).where(m.StockPrice.series == f"csv:{pool}"))
    f = db.get(m.PriceFetch, f"csv:{pool}")
    if f:
        db.delete(f)
    db.commit()
    _invalidate()
    return status(db)


def set_ticker(db: Session, group_key: str, ticker: str | None) -> dict:
    st = P._need(db)
    names = {t.stock_key: t.stock for t in st["rb"].trades}
    if group_key not in names:
        raise NotFound(f"'{group_key}' isn't one of your stocks")
    g = db.get(m.StockGroup, group_key)
    if g is None:  # keep the name you see, only add the ticker
        g = m.StockGroup(group_key=group_key, display_name=names[group_key])
        db.add(g)
    t = (ticker or "").strip().upper()
    if t and not all(c.isalnum() or c in ".-" for c in t):
        raise BadRequest("A ticker has letters, digits, '.' or '-' only (e.g. BRK-B).")
    g.ticker = t or None
    db.commit()
    P._invalidate()
    _invalidate()
    return {"group_key": group_key, "ticker": g.ticker}


# ---------------------------------------------------------------- status and views

def _series_info(db: Session) -> dict[str, dict]:
    rows = db.execute(select(m.StockPrice.series, func.count(), func.min(m.StockPrice.date), func.max(m.StockPrice.date))
                      .group_by(m.StockPrice.series)).all()
    return {s: {"days": n, "first": a.isoformat(), "last": b.isoformat()} for s, n, a, b in rows}


def _series(db: Session, name: str) -> list[tuple[date, float, float]]:
    return [(r.date, r.close, r.split) for r in db.scalars(select(m.StockPrice).where(m.StockPrice.series == name)
                                                           .order_by(m.StockPrice.date))]


def _checks(x: dict, rows: list[tuple[date, float, float]]) -> list[str]:
    """Warnings: a split while you held the stock, or trade prices far from the downloaded closes (wrong ticker?)."""
    out = []
    held_to = date.today() if x["open"] else x["last"]
    splits = [(d, s) for d, _, s in rows if abs(s - 1) > 1e-9 and x["first"] <= d <= held_to]
    for d, s in splits:
        out.append(f"Split {s:g}-for-1 on {d.isoformat()} while you held it: check the share count in your sheet.")
    closes = {d: c for d, c, _ in rows}
    ratios = []
    for t in x["trades"]:
        c = closes.get(t.date)
        if c:
            ratios.append(t.price / c)
    if len(ratios) >= 1:
        ratios.sort()
        med = ratios[len(ratios) // 2]
        if not 0.7 <= med <= 1.3:
            out.append(f"Your trade prices are about {med:.2f}× the downloaded closes: check the ticker (or a split).")
    return out


def status(db: Session) -> dict:
    ps = pools(db)
    info = _series_info(db)
    fetches = {f.series: f for f in db.scalars(select(m.PriceFetch))}
    rows = []
    for x in ps:
        csv = info.get(f"csv:{x['pool']}")
        tk = info.get(x["ticker"]) if x["ticker"] else None
        f = fetches.get(x["ticker"]) if x["ticker"] else None
        if csv:
            src, cov = "csv", csv
        elif tk:
            src, cov = "tiingo", tk
        else:
            src, cov = "trades", None
        series = f"csv:{x['pool']}" if csv else x["ticker"] if tk else None
        warnings = _checks(x, _series(db, series)) if series else []
        rows.append({"pool": x["pool"], "stock": x["stock"], "group_key": x["group_key"], "currency": x["currency"],
                     "pence": x["pence"], "open": x["open"], "first_trade": x["first"].isoformat(),
                     "last_trade": x["last"].isoformat(), "ticker": x["ticker"] if x["currency"] == "USD" else None,
                     "ticker_allowed": x["currency"] == "USD", "source": src, "coverage": cov,
                     "fetch_status": f.status if f else None, "fetch_message": f.message if f else None, "warnings": warnings})
    job = _job(db)
    t = _JOB["thread"]
    return {"key": bool(tiingo_key()), "running": bool(t and t.is_alive()), "waiting_until": job.get("waiting_until"),
            "message": job.get("message"), "last_run": job.get("last_run"), "queue": len(queue(db)) if tiingo_key() else None,
            "pools": rows,
            "counts": {"pools": len(rows), "open": sum(r["open"] for r in rows),
                       "tiingo": sum(r["source"] == "tiingo" for r in rows), "csv": sum(r["source"] == "csv" for r in rows),
                       "trades_only": sum(r["source"] == "trades" for r in rows),
                       "open_trades_only": sum(r["source"] == "trades" and r["open"] for r in rows),
                       "no_ticker_usd": sum(r["ticker_allowed"] and not r["ticker"] for r in rows),
                       "warnings": sum(bool(r["warnings"]) for r in rows)},
            "setup": "Get a free key at tiingo.com, add TIINGO_API_KEY=… to the .env file in the app's folder, restart the app."}


ODD_IGNORED = "odd_trades_ignored"


def ignore_odd(db: Session, items: list[dict]) -> dict:
    """Mark flagged trades as correct (e.g. a real 5× move); keyed by trade and price, so a changed row is checked again."""
    row = db.get(m.Setting, ODD_IGNORED)
    ids = set((row.value or {}).get("ids", [])) if row else set()
    ids |= {f"{x['id']}@{float(x['price']):g}" for x in items}
    if row is None:
        db.add(m.Setting(key=ODD_IGNORED, value={"ids": sorted(ids)}))
    else:
        row.value = {"ids": sorted(ids)}
    db.commit()
    _invalidate()
    return {"ignored": len(ids)}


def rename_trades(db: Session, ids: list[str], name: str) -> dict:
    """Give several sheet trades another stock name at once (sales first, so a sale never waits on its renamed purchase)."""
    from . import entries as E
    if not ids:
        raise BadRequest("Choose at least one trade.")
    for tid in sorted(ids, key=lambda i: (0 if i.startswith("S") else 1, i)):
        E.correct(db, tid, {"name": name})
    _invalidate()
    return {"renamed": len(ids), "name": name.strip()}


_CACHE: dict = {}


def _invalidate() -> None:
    _CACHE.clear()


def performance(db: Session) -> dict:
    st = P._need(db)
    key = (id(st), db.scalar(select(func.count()).select_from(m.StockPrice)), db.scalar(select(func.count()).select_from(m.Price)),
           db.scalar(select(func.max(m.Price.id))))
    if _CACHE.get("key") == key:
        return _CACHE["value"]
    ps = pools(db)
    entered: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for pr in db.scalars(select(m.Price)):
        entered[pr.pool].append((pr.date, pr.price))
    cur = P.current_prices(db, st)
    lines = {}
    sources = {}
    for x in ps:
        pts = [(t.date, t.price) for t in x["trades"]] + entered.get(x["pool"], [])
        if x["pool"] in cur:
            pts.append((cur[x["pool"]]["date"], cur[x["pool"]]["price"]))
        hist = _series(db, f"csv:{x['pool']}")
        sources[x["pool"]] = "csv" if hist else None
        if not hist and x["ticker"]:
            hist = _series(db, x["ticker"])
            sources[x["pool"]] = "tiingo" if hist else None
        lines[x["pool"]] = H.price_line([(d, c) for d, c, _ in hist], pts)
    end = _valuation_end(db, st)
    series = H.build(st["rb"].trades, st["sales"], st["rates"], lines, end)
    ignored = set((db.get(m.Setting, ODD_IGNORED).value or {}).get("ids", [])) if db.get(m.Setting, ODD_IGNORED) else set()
    odd = [x for x in H.odd_trades(st["rb"].trades) if f"{x['id']}@{x['price']:g}" not in ignored]
    out = {"as_of": end.isoformat(), **series, "months": H.months(series), "odd_trades": odd,
           "estimated_now_pct": (series["estimated"][-1] / series["value"][-1] * 100) if series["value"] and series["value"][-1] else None,
           "note": ("Open positions are valued each day at that day's close where a price history exists (Tiingo or your CSV); "
                    "otherwise at the last known trade or entered price, carried forward (marked as estimated). Closed = "
                    "realised FIFO gains. USD at each day's ECB rate. Before tax; dividends not included.")}
    _CACHE.update(key=key, value=out)
    return out
