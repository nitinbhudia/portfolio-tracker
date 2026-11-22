"""Trade journal: your notes per trade, the context the prices give, plan vs reality, and what works (engine/journal.py)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.engine import benchmarks as BM
from app.engine import journal as J

from . import benchmarks as BMS
from . import groups as GS
from . import history as HS
from . import portfolio as P

TAGS = "journal_tags"
STARS = "journal_starred"  # stocks you marked ★ (stock keys, or "ticker:XYZ" for ideas on stocks you never traded)
INBOX_DAYS = 90  # trades this recent, without an entry, wait on the To journal list
TEXT_MAX = {"notes": 10000, "lesson": 2000}
_CACHE: dict = {}


def tags(db: Session) -> dict:
    row = db.get(m.Setting, TAGS)
    v = row.value if row else {}
    return {"reasons": v.get("reasons") or list(J.REASONS), "sell_reasons": v.get("sell_reasons") or list(J.SELL_REASONS)}


def set_tags(db: Session, reasons: list[str] | None, sell_reasons: list[str] | None) -> dict:
    def clean(xs):
        out = []
        for x in xs or []:
            x = str(x).strip()[:60]
            if x and x not in out:
                out.append(x)
        return out[:40]
    cur = tags(db)
    v = {"reasons": clean(reasons) if reasons is not None else cur["reasons"],
         "sell_reasons": clean(sell_reasons) if sell_reasons is not None else cur["sell_reasons"]}
    row = db.get(m.Setting, TAGS)
    if row is None:
        db.add(m.Setting(key=TAGS, value=v))
    else:
        row.value = v
    db.commit()
    return v


def stars(db: Session) -> set[str]:
    row = db.get(m.Setting, STARS)
    return set((row.value or {}).get("keys", [])) if row else set()


def set_star(db: Session, key: str, on: bool) -> dict:
    key = str(key or "").strip()[:250]
    if not key:
        raise P.BadRequest("which stock?")
    cur = stars(db)
    cur = cur | {key} if on else cur - {key}
    row = db.get(m.Setting, STARS)
    if row is None:
        db.add(m.Setting(key=STARS, value={"keys": sorted(cur)}))
    else:
        row.value = {"keys": sorted(cur)}
    db.commit()
    return {"starred": sorted(cur)}


def _decorate(db: Session, rows: list[dict]) -> list[dict]:
    """Things that change without a new upload: your stars and sectors."""
    from . import whatif as WS
    st, sec = stars(db), WS.confirmed_sectors(db)
    for r in rows:
        r["starred"] = r["stock_key"] in st
        r["sector"] = sec.get(r["stock_key"])
    return rows


def _entry(e: m.JournalEntry | None) -> dict | None:
    if e is None:
        return None
    return {"reasons": e.reasons or [], "target": e.target, "stop": e.stop, "horizon_days": e.horizon_days,
            "confidence": e.confidence, "sell_reason": e.sell_reason, "lesson": e.lesson, "notes": e.notes,
            "skipped": e.skipped, "updated_at": e.updated_at.isoformat() if e.updated_at else None}


def _written(e: dict | None) -> bool:
    return bool(e and (e["reasons"] or e["target"] or e["stop"] or e["horizon_days"] or e["confidence"] or e["sell_reason"]
                       or e["lesson"] or e["notes"]))


def _closes(db: Session, pool: str, ticker: str | None) -> list[tuple[date, float]]:
    rows = HS._series(db, f"csv:{pool}") or (HS._series(db, ticker) if ticker else [])
    return [(d, c) for d, c, _ in rows]


def _splits(db: Session, ticker: str | None) -> list[date]:
    return [d for d, _, s in (HS._series(db, ticker) if ticker else []) if abs(s - 1) > 1e-9]


def _build(db: Session) -> dict:
    st = P._need(db)
    key = (id(st), db.scalar(select(func.count()).select_from(m.StockPrice)), db.scalar(select(func.max(m.JournalEntry.updated_at))),
           db.scalar(select(func.count()).select_from(m.JournalEntry)), db.get(m.Setting, "sale_groups") and str(db.get(m.Setting, "sale_groups").value))
    if _CACHE.get("key") == key:
        return _CACHE["value"]
    trades = st["rb"].trades
    keys = J.trade_keys(trades)
    entries = {e.key: _entry(e) for e in db.scalars(select(m.JournalEntry))}
    tickers = st["tickers"]
    spx_s = BMS.series(db).get("spx")
    spx = list(zip(spx_s.dates, spx_s.closes)) if spx_s else []
    group_of = {s["id"]: s["group"] for s in GS.view(db)["sales"]}
    sales = {s.id: s for s in st["sales"]}
    open_lots = {lot.buy_id: lot for lot in st["lots"]}
    today = date.today()
    series: dict[str, list] = {}
    splits: dict[str, list] = {}
    rows = []
    for t in trades:
        ticker = tickers.get(t.stock_key) if t.currency == "USD" else None
        if t.pool not in series:
            series[t.pool] = _closes(db, t.pool, ticker)
            splits[t.pool] = _splits(db, ticker)
        closes = series[t.pool]
        k = keys[t.id]
        e = entries.get(k)
        row = {"key": k, "id": t.id, "kind": t.kind, "date": t.date.isoformat(), "stock": t.stock, "stock_key": t.stock_key,
               "pool": t.pool, "currency": t.currency, "pence": t.scale == 0.01, "shares": t.shares, "price": t.price,
               "broker": t.broker, "source": t.source, "ticker": ticker, "entry": e,
               "status": "done" if _written(e) else "skipped" if e and e["skipped"] else "todo"}
        if t.kind == "buy":
            row["from_high_pct"] = J.from_high(closes, t.date, t.price)
            row["market"] = J.market_trend(spx, t.date)
            lot = open_lots.get(t.id)
            row["open_shares"] = lot.shares if lot else 0.0
            if lot and not any(t.date < d <= today for d in splits[t.pool]):
                row["since"] = J.excursion(closes, t.date, today, t.price)
        else:
            s = sales.get(t.id)
            if s is not None:
                shares = sum(mt.shares for mt in s.matches) or 1.0
                days = round(sum(mt.shares * mt.days_held for mt in s.matches) / shares) if s.matches else None
                first = min((mt.buy_date for mt in s.matches), default=t.date)
                avg_buy = sum(mt.shares * mt.buy_price for mt in s.matches) / shares if s.matches else None
                idx = BM.sale_vs_index(spx_s, s, st["rates"]) if spx_s else None
                exc = None
                if avg_buy and not any(first < d <= t.date for d in splits[t.pool]):
                    exc = J.excursion(closes, first, t.date, avg_buy)
                buys = [keys[mt.buy_id] for mt in s.matches if mt.buy_id in keys]
                big = max(s.matches, key=lambda mt: mt.shares).buy_id if s.matches else None
                plan_e = entries.get(keys.get(big)) if big else None
                row.update({"gain_usd": s.gain_usd, "gain_pct": s.gain_pct, "days": days, "avg_buy_price": avg_buy,
                            "spx_gain_usd": idx, "vs_spx_usd": s.gain_usd - idx if s.gain_usd is not None and idx is not None else None,
                            "excursion": exc, "buy_keys": buys, "group": group_of.get(t.id),
                            "reasons": sorted({r for b in buys for r in ((entries.get(b) or {}).get("reasons") or [])}),
                            "confidence": (plan_e or {}).get("confidence"),
                            "plan": J.plan_check(plan_e or {}, t.price, days, exc) if plan_e else []})
        rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["kind"]), reverse=True)
    out = {"rows": rows, "by_key": {r["key"]: r for r in rows}, "by_id": {r["id"]: r["key"] for r in rows}}
    _CACHE.update(key=key, value=out)
    return out


def _since() -> date:
    return date.today() - timedelta(days=INBOX_DAYS)


def view(db: Session) -> dict:
    b = _build(db)
    rows = _decorate(db, b["rows"])
    since = _since().isoformat()
    todo = [r for r in rows if r["status"] == "todo" and r["date"] >= since]
    return {"rows": rows, "tags": tags(db), "inbox": [r["key"] for r in todo], "inbox_days": INBOX_DAYS,
            "counts": {"trades": len(rows), "done": sum(r["status"] == "done" for r in rows),
                       "skipped": sum(r["status"] == "skipped" for r in rows), "todo_recent": len(todo),
                       "todo_older": sum(1 for r in rows if r["status"] == "todo" and r["date"] < since)}}


def detail(db: Session, key: str) -> dict:
    b = _build(db)
    r = b["by_key"].get(key)
    if r is None:
        raise P.NotFound("That trade isn't in your current data (was the workbook changed?).")
    _decorate(db, [r])
    out = {**r, "fibonacci": _fibonacci(r)}
    if r["kind"] == "sell":
        out["buys"] = [b["by_key"][k] for k in r.get("buy_keys", []) if k in b["by_key"]]
    else:
        out["sales"] = [x for x in b["rows"] if x["kind"] == "sell" and key in (x.get("buy_keys") or [])]
    return out


def _fibonacci(r: dict) -> dict | None:
    """The nearest Fibonacci level on the trade day, from Research (US stocks it has prices for)."""
    if not r.get("ticker"):
        return None
    try:
        from research.db.session import SessionLocal
        from research.market_data.service import find_real_listing
        from research.services import analysis as an
        with SessionLocal() as rdb:
            lst = find_real_listing(rdb, r["ticker"])
            if lst is None:
                return None
            a = an.analyse_listing(rdb, lst.id, as_of=date.fromisoformat(r["date"]), include_series=False)
        fib = a.get("fibonacci") or {}
        if fib.get("status") != "ok":
            return None
        return {"listing_id": lst.id, "nearest": fib.get("nearest"), "direction": fib.get("direction"),
                "swing_high": fib.get("swing_high"), "swing_low": fib.get("swing_low")}
    except Exception:  # noqa: BLE001  (context only: the entry works without it)
        return None


def _num(v, field: str, lo: float | None = None, hi: float | None = None, integer: bool = False):
    if v in (None, ""):
        return None
    try:
        x = int(v) if integer else float(v)
    except (TypeError, ValueError) as e:
        raise P.BadRequest(f"{field} must be a number") from e
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise P.BadRequest(f"{field} must be between {lo:g} and {hi:g}")
    return x


def save(db: Session, key: str, d: dict) -> dict:
    b = _build(db)
    r = b["by_key"].get(key)
    if r is None:
        raise P.NotFound("That trade isn't in your current data (was the workbook changed?).")
    e = db.get(m.JournalEntry, key) or m.JournalEntry(key=key, kind=r["kind"])
    if r["kind"] == "buy":
        e.reasons = [str(x).strip()[:60] for x in (d.get("reasons") or []) if str(x).strip()][:10]
        e.target = _num(d.get("target"), "target", 0)
        e.stop = _num(d.get("stop"), "stop", 0)
        e.horizon_days = _num(d.get("horizon_days"), "time frame (days)", 1, 36500, integer=True)
        e.confidence = _num(d.get("confidence"), "confidence", 1, 5, integer=True)
    else:
        e.sell_reason = (str(d.get("sell_reason") or "").strip()[:100]) or None
        e.lesson = (str(d.get("lesson") or "").strip()[:TEXT_MAX["lesson"]]) or None
    e.notes = (str(d.get("notes") or "").strip()[:TEXT_MAX["notes"]]) or None
    e.skipped = bool(d.get("skipped", False)) and not _written(_entry(e))
    e.updated_at = datetime.now(timezone.utc)
    db.merge(e)
    db.commit()
    return detail(db, key)


def skip(db: Session, keys: list[str] | None = None, older: bool = False) -> dict:
    """Take trades off the To journal list without writing anything (keys, or every unwritten trade older than the list)."""
    b = _build(db)
    if older:
        since = _since().isoformat()
        keys = [r["key"] for r in b["rows"] if r["status"] == "todo" and r["date"] < since]
    for k in keys or []:
        r = b["by_key"].get(k)
        if r is None or r["status"] == "done":
            continue
        e = db.get(m.JournalEntry, k) or m.JournalEntry(key=k, kind=r["kind"])
        e.skipped = True
        e.updated_at = datetime.now(timezone.utc)
        db.merge(e)
    db.commit()
    return view(db)


def stats(db: Session) -> dict:
    b = _build(db)
    _decorate(db, b["rows"])
    sales = [{"sector": r.get("sector"), "starred": r.get("starred"), "gain_usd": r.get("gain_usd"), "gain_pct": r.get("gain_pct"), "days": r.get("days"), "reasons": r.get("reasons") or [],
              "group": r.get("group"), "confidence": r.get("confidence"), "plan": r.get("plan") or [],
              "sell_reason": (r["entry"] or {}).get("sell_reason")} for r in b["rows"] if r["kind"] == "sell" and "gain_usd" in r]
    out = J.stats(sales)
    exc = [r for r in b["rows"] if r["kind"] == "sell" and r.get("excursion") and r.get("gain_pct") is not None]
    gave = [r for r in exc if r["excursion"]["best_pct"] - r["gain_pct"] >= 15]
    out["left_on_table"] = {"sales": len(exc), "gave_back_15": len(gave),
                            "examples": [{"key": r["key"], "stock": r["stock"], "date": r["date"], "best_pct": r["excursion"]["best_pct"],
                                          "gain_pct": r["gain_pct"]} for r in sorted(gave, key=lambda r: r["gain_pct"] - r["excursion"]["best_pct"])[:5]]}
    lessons = [{"key": r["key"], "stock": r["stock"], "date": r["date"], "lesson": r["entry"]["lesson"]}
               for r in b["rows"] if r["entry"] and r["entry"].get("lesson")]
    out["lessons"] = lessons[:50]
    return out


def export_csv(db: Session) -> str:
    rows = _build(db)["rows"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "kind", "stock", "currency", "shares", "price", "broker", "reasons", "target", "stop", "time_frame_days",
                "confidence", "sell_reason", "lesson", "notes", "gain_usd", "gain_pct", "days_held", "vs_sp500_usd", "best_pct",
                "worst_pct", "plan_checks", "group"])
    for r in rows:
        e = r["entry"] or {}
        exc = r.get("excursion") or {}
        w.writerow([r["date"], r["kind"], r["stock"], r["currency"], r["shares"], r["price"], r["broker"], "; ".join(e.get("reasons") or r.get("reasons") or []),
                    e.get("target"), e.get("stop"), e.get("horizon_days"), e.get("confidence"), e.get("sell_reason"), e.get("lesson"), e.get("notes"),
                    r.get("gain_usd"), r.get("gain_pct"), r.get("days"), r.get("vs_spx_usd"), exc.get("best_pct"), exc.get("worst_pct"),
                    " | ".join(c["text"] for c in r.get("plan") or []), r.get("group")])
    return buf.getvalue()


def _invalidate() -> None:
    _CACHE.clear()
