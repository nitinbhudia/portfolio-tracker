"""Index data (Stooq or uploaded CSV) and the comparison views."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.engine import benchmarks as BM

from . import portfolio as P
from .portfolio import BadRequest, NotFound

FETCH = BM.fetch_stooq  # replaced in tests
SETTING = "benchmark_symbols"
NOTE = ("Index prices exclude dividends (so do your gains unless you entered dividends). FTSE 100 is converted to USD at "
        "the ECB rate of each day, because your results are in USD. Your portfolio's day-by-day value isn't known (the sheet "
        "has no price history for your stocks), so the comparison uses your actual trades: the same dollars in the index "
        "over the same holding periods.")


def _symbols(db: Session) -> dict[str, str]:
    row = db.get(m.Setting, SETTING)
    saved = row.value if row else {}
    return {k: saved.get(k, v[1]) for k, v in BM.INDEXES.items()}


def _check(index_id: str) -> None:
    if index_id not in BM.INDEXES:
        raise NotFound(f"unknown index '{index_id}'")


def _store(db: Session, index_id: str, rows: list[tuple[date, float]]) -> None:
    db.execute(delete(m.IndexPrice).where(m.IndexPrice.index_id == index_id))
    db.add_all(m.IndexPrice(index_id=index_id, date=d, close=v) for d, v in rows)
    db.commit()
    cur = BM.INDEXES[index_id][2]
    if cur != "USD" and rows:
        P.ensure_fx_for(db, [cur], rows[0][0])
    P._invalidate()


def series(db: Session) -> dict[str, BM.Series]:
    out: dict[str, BM.Series] = {}
    for k, (_, _, cur) in BM.INDEXES.items():
        rows = db.execute(select(m.IndexPrice.date, m.IndexPrice.close).where(m.IndexPrice.index_id == k).order_by(m.IndexPrice.date)).all()
        if rows:
            out[k] = BM.Series(k, cur, [r[0] for r in rows], [r[1] for r in rows])
    return out


def status(db: Session) -> list[dict]:
    syms, ss = _symbols(db), series(db)
    return [{"id": k, "name": n, "symbol": syms[k], "currency": c, "points": len(ss[k].dates) if k in ss else 0,
             "first": ss[k].dates[0].isoformat() if k in ss else None, "last": ss[k].dates[-1].isoformat() if k in ss else None}
            for k, (n, _, c) in BM.INDEXES.items()]


def refresh(db: Session, ids: list[str] | None = None) -> dict:
    syms = _symbols(db)
    results = []
    for k in ids or list(BM.INDEXES):
        _check(k)
        try:
            rows = FETCH(syms[k])
            _store(db, k, rows)
            results.append({"id": k, "ok": True, "points": len(rows), "last": rows[-1][0].isoformat()})
        except BM.BenchmarkError as e:
            results.append({"id": k, "ok": False, "message": str(e)})
    return {"results": results, "indexes": status(db)}


def upload(db: Session, index_id: str, data: bytes) -> dict:
    _check(index_id)
    try:
        rows = BM.parse_csv(data.decode("utf-8", errors="replace"))
    except BM.BenchmarkError as e:
        raise BadRequest(str(e)) from e
    _store(db, index_id, rows)
    return {"results": [{"id": index_id, "ok": True, "points": len(rows), "last": rows[-1][0].isoformat()}], "indexes": status(db)}


def set_symbol(db: Session, index_id: str, symbol: str) -> dict:
    _check(index_id)
    sym = (symbol or "").strip()
    if not sym or len(sym) > 20:
        raise BadRequest("symbol must be 1–20 characters")
    row = db.get(m.Setting, SETTING)
    if row is None:
        db.add(m.Setting(key=SETTING, value={index_id: sym}))
    else:
        row.value = {**row.value, index_id: sym}
    db.commit()
    return {"indexes": status(db)}


def _sample(dates: list[date], max_points: int = 400) -> list[date]:
    if len(dates) <= max_points:
        return dates
    step = len(dates) / max_points
    picked = [dates[int(i * step)] for i in range(max_points)]
    return picked + ([dates[-1]] if picked[-1] != dates[-1] else [])


def _months_back(end: date, months: int) -> date:
    y, mth = end.year, end.month - months
    while mth <= 0:
        y, mth = y - 1, mth + 12
    import calendar
    return date(y, mth, min(end.day, calendar.monthrange(y, mth)[1]))


RANGES = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36, "5Y": 60}


def view(db: Session, start: str | None, end: str | None, range_key: str | None = None) -> dict:
    st = P._need(db)
    pos = P.positions(db)
    valuation = date.fromisoformat(pos["as_of"])
    rates = st["rates"]
    sales, lots = st["sales"], st["lots"]
    buys = [(b["date"], b["cost_usd"]) for b in P._buys(st)]
    first_trade = min([d for d, _ in buys] + [s.date for s in sales], default=valuation)
    try:
        b = date.fromisoformat(end) if end else valuation
        a = date.fromisoformat(start) if start else first_trade
    except ValueError as e:
        raise BadRequest("start and end must be dates (YYYY-MM-DD)") from e
    if range_key and range_key not in ("ALL", "CUSTOM"):
        if range_key == "YTD":
            a = date(min(b, valuation).year, 1, 1)
        elif range_key in RANGES:
            a = _months_back(min(b, valuation), RANGES[range_key])
        else:
            raise BadRequest(f"range must be one of {['ALL', 'YTD', *RANGES]}")
    if a > b:
        raise BadRequest("start must be before end")
    b = min(b, valuation)
    ss = series(db)
    all_time = a <= first_trade
    out_idx = []
    for k, (name, _, cur) in BM.INDEXES.items():
        s = ss.get(k)
        row = {"id": k, "name": name, "currency": cur, "available": s is not None}
        if s:
            la, lb = s.level(a), s.level(b)
            ua, ub = s.usd(a, rates), s.usd(b, rates)
            row["change_pct"] = (lb[1] / la[1] - 1) * 100 if la and lb else None
            row["change_usd_pct"] = (ub / ua - 1) * 100 if ua and ub else None
            row["from"], row["to"] = (la[0].isoformat() if la else None), (lb[0].isoformat() if lb else None)
            row["compare"] = BM.compare(s, sales, lots, rates, a, b, valuation)
            row["same_money"] = BM.same_money(s, buys, sales, rates, valuation, pos["totals"]["value_usd"]) if all_time else None
        out_idx.append(row)
    # chart 1: each index, USD, = 100 at the start of the period
    chart_dates = sorted({d for s in ss.values() for d in s.dates if a <= d <= b})
    chart_dates = _sample(chart_dates)
    lines = {}
    for k, s in ss.items():
        base = s.usd(a, rates) or next((s.usd(d, rates) for d in chart_dates if s.usd(d, rates)), None)
        lines[k] = [(round(v / base * 100, 3) if (v := s.usd(d, rates)) and base else None) for d in chart_dates]
    # chart 2: your cumulative realised gain vs the same dollars in each index (sales in the period)
    in_period = sorted((sa for sa in sales if a <= sa.date <= b and sa.gain_usd is not None), key=lambda x: (x.date, x.id))
    cum_dates, yours, idx_cum = [], [], {k: [] for k in ss}
    tot_y, tot_i = 0.0, {k: 0.0 for k in ss}
    for sa in in_period:
        tot_y += sa.gain_usd
        for k, s in ss.items():
            g = BM.sale_vs_index(s, sa, rates)
            tot_i[k] += g if g is not None else sa.gain_usd  # unpriced: count as equal, so it doesn't distort the gap
        if cum_dates and cum_dates[-1] == sa.date.isoformat():
            yours[-1] = tot_y
            for k in ss:
                idx_cum[k][-1] = tot_i[k]
        else:
            cum_dates.append(sa.date.isoformat())
            yours.append(tot_y)
            for k in ss:
                idx_cum[k].append(tot_i[k])
    return {"period": {"start": a.isoformat(), "end": b.isoformat(), "all_time": all_time, "first_trade": first_trade.isoformat(),
                       "valuation": valuation.isoformat()},
            "indexes": out_idx, "status": status(db),
            "index_chart": {"dates": [d.isoformat() for d in chart_dates], "lines": lines},
            "cumulative": {"dates": cum_dates, "yours": yours, "index": idx_cum},
            "open": {"unrealised_usd": pos["totals"]["unrealised_usd"], "value_usd": pos["totals"]["value_usd"]} if b >= valuation else None,
            "note": NOTE, "review_pending": st["rb"].accounting["review_pending"]}
