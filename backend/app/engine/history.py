"""Portfolio value and profit/loss day by day, from the FIFO results and daily prices.

For every business day from the first trade to the valuation date:
- open shares and open cost per pool follow the trades: a buy adds its shares and its USD cost (purchase-date rate,
  fees included, exactly like the FIFO engine); a sale removes its shares and the FIFO cost of the lots it used;
- market value = open shares × that day's price × that day's ECB rate;
- open P/L = market value − open cost; closed P/L = realised FIFO gains to date; total = open + closed.

Prices: a pool's daily history (Tiingo for US tickers, or an uploaded CSV) where there is one. Outside the history, or
for a pool without one, the last known price is carried forward from the trades themselves (buy and sale prices) and
prices entered in the app. Values priced that way are reported as "estimated" so charts can say how much is estimated.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .fifo import Sale
from .fx import Rates
from .rebuild import Trade

STALE_DAYS = 10  # a history price older than this counts as estimated (e.g. a gap or a delisting)


@dataclass
class PriceLine:
    """Step function of a pool's price (listing units): dates ascending, value carried forward."""
    dates: list[date]
    prices: list[float]
    real: list[bool]  # True = from a daily history, False = a trade price or a price entered in the app

    def at(self, d: date) -> tuple[float, bool] | None:
        i = bisect.bisect_right(self.dates, d) - 1
        if i < 0:
            return None
        return self.prices[i], self.real[i] and (d - self.dates[i]).days <= STALE_DAYS


def price_line(history: list[tuple[date, float]], points: list[tuple[date, float]]) -> PriceLine:
    """Merge a daily history with known points (trades, entered prices); history wins inside its own date range."""
    hist = sorted(history)
    lo, hi = (hist[0][0], hist[-1][0]) if hist else (None, None)
    merged: dict[date, tuple[float, bool]] = {}
    for d, p in sorted(points):
        if lo is None or d < lo or d > hi:
            merged[d] = (p, False)
    for d, p in hist:
        merged[d] = (p, True)
    ds = sorted(merged)
    return PriceLine(ds, [merged[d][0] for d in ds], [merged[d][1] for d in ds])


def business_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    if out and out[-1] != end:
        out.append(end)  # always value on the valuation date itself, even at a weekend
    return out


def build(trades: list[Trade], sales: list[Sale], rates: Rates, lines: dict[str, PriceLine], end: date,
          start: date | None = None) -> dict:
    """Daily series. `lines`: pool -> PriceLine (see price_line). Pools without one use their trade prices only."""
    if not trades:
        return {"dates": [], "value": [], "cost": [], "realised": [], "open_pl": [], "total": [], "sold_proceeds": [],
                "sold_cost": [], "estimated": [], "problems": []}
    first = min(t.date for t in trades)
    days = business_days(start or first, end)
    by_day: dict[date, list[Trade]] = defaultdict(list)
    meta: dict[str, tuple[str, float]] = {}
    for t in trades:
        by_day[t.date].append(t)
        meta[t.pool] = (t.currency, t.scale)
    sale_by_id = {s.id: s for s in sales}
    sales_by_day: dict[date, list[Sale]] = defaultdict(list)
    for s in sales:
        sales_by_day[s.date].append(s)
    # pools without a given line: trade prices only
    pts: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for t in trades:
        pts[t.pool].append((t.date, t.price))
    lines = dict(lines)
    for pool, p in pts.items():
        if pool not in lines:
            lines[pool] = price_line([], p)

    shares: dict[str, float] = defaultdict(float)
    cost: dict[str, float] = defaultdict(float)
    realised = proceeds = sold_cost = 0.0
    problems: set[str] = set()
    out = {k: [] for k in ("value", "cost", "realised", "open_pl", "total", "sold_proceeds", "sold_cost", "estimated")}
    pending = sorted(by_day)  # trade dates, consumed in order (also those before `start`)
    k = 0
    pending_sales = sorted(sales_by_day)
    j = 0

    def apply_until(d: date):
        nonlocal k, j, realised, proceeds, sold_cost
        while k < len(pending) and pending[k] <= d:
            for t in sorted(by_day[pending[k]], key=lambda t: (0 if t.kind == "buy" else 1, t.row)):
                if t.kind == "buy":
                    r = rates.usd(t.currency, t.date)
                    if r is None:
                        problems.add(f"{t.stock}: no exchange rate on {t.date}, cost left out")
                        continue
                    shares[t.pool] += t.shares
                    cost[t.pool] += (t.shares * t.price * t.scale + t.fee) * r.rate
                else:
                    s = sale_by_id.get(t.id)
                    shares[t.pool] = max(0.0, shares[t.pool] - t.shares)
                    if s is not None and s.cost_usd is not None:
                        cost[t.pool] -= s.cost_usd
                    if shares[t.pool] <= 1e-9:
                        shares[t.pool], cost[t.pool] = 0.0, 0.0
            k += 1
        while j < len(pending_sales) and pending_sales[j] <= d:
            for s in sales_by_day[pending_sales[j]]:
                if s.gain_usd is not None:
                    realised += s.gain_usd
                    proceeds += s.proceeds_usd or 0.0
                    sold_cost += s.cost_usd or 0.0
            j += 1

    last_fx: dict[str, float] = {}
    for d in days:
        apply_until(d)
        fx: dict[str, float | None] = {}
        value = est = 0.0
        for pool, n in shares.items():
            if n <= 1e-9:
                continue
            cur, scale = meta[pool]
            if cur not in fx:
                r = rates.usd(cur, d)
                if r is not None:
                    last_fx[cur] = r.rate
                fx[cur] = r.rate if r else last_fx.get(cur)  # rates not yet published: last known rate
            px = lines[pool].at(d)
            if px is None or fx[cur] is None:
                continue
            v = n * px[0] * scale * fx[cur]
            value += v
            if not px[1]:
                est += v
        c = sum(cost.values())
        out["value"].append(value)
        out["cost"].append(c)
        out["realised"].append(realised)
        out["open_pl"].append(value - c)
        out["total"].append(realised + value - c)
        out["sold_proceeds"].append(proceeds)
        out["sold_cost"].append(sold_cost)
        out["estimated"].append(est)
    return {"dates": [d.isoformat() for d in days], **out, "problems": sorted(problems)}


def odd_prices(trades: list[Trade], factor: float = 4.0, days: int = 30) -> list[str]:
    """Trades whose price is `factor`× away from the same stock's other trades within `days`: a move that size in a month
    usually means two different stocks written with the same name (or a missing split), which distorts the daily value."""
    by_pool: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_pool[t.pool].append(t)
    out = []
    for ts in by_pool.values():
        ts.sort(key=lambda t: (t.date, t.row))
        for i, t in enumerate(ts):
            near = [x.price for x in ts if x is not t and x.price > 0 and abs((x.date - t.date).days) <= days]
            if len(near) < 2 or t.price <= 0:
                continue
            near.sort()
            med = near[len(near) // 2]
            if t.price > med * factor or t.price < med / factor:
                out.append(f"{t.stock}: the {t.kind} on {t.date.isoformat()} (sheet row {t.row}) at {t.price:g} is far from its other trades "
                           f"(around {med:g}). Is it a different stock with a similar name? Correct the name on Data ▾ Trades.")
    return out


def months(series: dict) -> list[dict]:
    """Change in total P/L per calendar month (month-end to month-end), split into closed and open."""
    ends: dict[str, int] = {}
    for i, d in enumerate(series["dates"]):
        ends[d[:7]] = i
    out, prev = [], None
    for mth, i in ends.items():
        tot, rl, op, val = series["total"][i], series["realised"][i], series["open_pl"][i], series["value"][i]
        if prev is None:
            ch, base = tot, None
            dr, do = rl, op
        else:
            ch, base = tot - series["total"][prev], series["value"][prev]
            dr, do = rl - series["realised"][prev], op - series["open_pl"][prev]
        out.append({"month": mth, "change_usd": ch, "change_pct": ch / base * 100 if base else None,
                    "closed_usd": dr, "open_usd": do, "value_end_usd": val, "total_end_usd": tot})
        prev = i
    return out
