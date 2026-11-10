"""Analysis on top of FIFO (SPEC.md §5): trading statistics, months and years, money invested over time,
money-weighted returns (XIRR) and return on capital.

Limits, stated wherever these numbers are shown:
- the sheet only has *today's* prices, so past portfolio values (and the change in unrealised gain within a
  past year) can't be known: per-year figures use realised gains;
- fees and dividends are included once entered in the app; interest isn't.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .fifo import Lot, Sale

BUCKETS = (("up to 1 month", 0, 31), ("1–12 months", 31, 366), ("over 1 year", 366, 10**6))


# ---------------------------------------------------------------- XIRR

def xirr(flows: list[tuple[date, float]], lo: float = -0.9999, hi: float = 100.0) -> float | None:
    """Annual rate r with sum(cf / (1+r)^(days/365)) = 0. None if it doesn't exist (no sign change, too short)."""
    flows = sorted((d, v) for d, v in flows if abs(v) > 1e-9)
    if len(flows) < 2 or not (any(v < 0 for _, v in flows) and any(v > 0 for _, v in flows)):
        return None
    t0 = flows[0][0]
    ts = [((d - t0).days / 365.0, v) for d, v in flows]
    if ts[-1][0] < 1 / 365:
        return None

    def npv(r: float) -> float:
        return sum(v / (1.0 + r) ** t for t, v in ts)

    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):  # bisection: slow but always converges on a bracketed root
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7 or hi - lo < 1e-10:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- statistics

def _done(sales: list[Sale]) -> list[Sale]:
    return [s for s in sales if s.gain_usd is not None]


def statistics(sales: list[Sale]) -> dict:
    ss = _done(sales)
    wins = [s for s in ss if s.gain_usd > 0]
    losses = [s for s in ss if s.gain_usd < 0]
    gw, gl = sum(s.gain_usd for s in wins), sum(s.gain_usd for s in losses)

    def avg(xs):
        return sum(xs) / len(xs) if xs else None

    buckets = []
    for label, a, b in BUCKETS:
        bs = [s for s in ss if s.days_held is not None and a <= s.days_held < b]
        bw = [s for s in bs if s.gain_usd > 0]
        buckets.append({"label": label, "sales": len(bs), "gain_usd": sum(s.gain_usd for s in bs),
                        "win_rate_pct": len(bw) / len(bs) * 100 if bs else None,
                        "cost_usd": sum(s.cost_usd for s in bs),
                        "return_pct": sum(s.gain_usd for s in bs) / sum(s.cost_usd for s in bs) * 100 if bs and sum(s.cost_usd for s in bs) else None})
    ranked = sorted(ss, key=lambda s: s.gain_usd)
    brief = lambda s: {"id": s.id, "date": s.date.isoformat(), "stock": s.stock, "gain_usd": s.gain_usd,  # noqa: E731
                       "gain_pct": s.gain_pct, "days_held": s.days_held, "currency": s.currency}
    return {
        "sales": len(ss), "not_computed": len(sales) - len(ss), "wins": len(wins), "losses": len(losses),
        "breakeven": len(ss) - len(wins) - len(losses),
        "win_rate_pct": len(wins) / len(ss) * 100 if ss else None,
        "gross_wins_usd": gw, "gross_losses_usd": gl, "net_usd": gw + gl,
        "avg_win_usd": avg([s.gain_usd for s in wins]), "avg_loss_usd": avg([s.gain_usd for s in losses]),
        "avg_win_pct": avg([s.gain_pct for s in wins if s.gain_pct is not None]),
        "avg_loss_pct": avg([s.gain_pct for s in losses if s.gain_pct is not None]),
        "profit_factor": gw / -gl if gl else None,
        "expectancy_usd": (gw + gl) / len(ss) if ss else None,
        "avg_days_winners": avg([s.days_held for s in wins if s.days_held is not None]),
        "avg_days_losers": avg([s.days_held for s in losses if s.days_held is not None]),
        "fx_effect_usd": sum(s.fx_effect_usd or 0.0 for s in ss),
        "by_holding_period": buckets,
        "best_sales": [brief(s) for s in reversed(ranked[-5:])], "worst_sales": [brief(s) for s in ranked[:5]],
    }


# ---------------------------------------------------------------- months and years

def months(sales: list[Sale]) -> list[dict]:
    out: dict[str, dict] = {}
    for s in _done(sales):
        k = s.date.strftime("%Y-%m")
        m = out.setdefault(k, {"month": k, "sales": 0, "gain_usd": 0.0, "wins": 0, "proceeds_usd": 0.0})
        m["sales"] += 1
        m["gain_usd"] += s.gain_usd
        m["wins"] += s.gain_usd > 0
        m["proceeds_usd"] += s.proceeds_usd
    return [out[k] for k in sorted(out)]


@dataclass
class Point:
    date: date
    invested_usd: float  # cost (at buy-date rates) of the shares held after this day
    realised_cum_usd: float


def _month_ends(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        last = date(ny, nm, 1).toordinal() - 1
        out.append(min(date.fromordinal(last), end))
        y, m = ny, nm
    return out


def timeline(buys: list[tuple[date, float]], sales: list[Sale], end: date) -> list[Point]:
    """Month-end series of money invested in shares (FIFO cost of what is held) and cumulative realised gain.
    buys: (date, cost_usd) of every purchase in the results."""
    events: list[tuple[date, float, float]] = [(d, c, 0.0) for d, c in buys if c is not None]
    for s in _done(sales):
        events.append((s.date, -s.cost_usd, s.gain_usd))
    if not events:
        return []
    events.sort(key=lambda e: e[0])
    pts, i, inv, real = [], 0, 0.0, 0.0
    for me in _month_ends(events[0][0], max(end, events[-1][0])):
        while i < len(events) and events[i][0] <= me:
            inv += events[i][1]
            real += events[i][2]
            i += 1
        pts.append(Point(me, max(inv, 0.0), real))
    return pts


def years(sales: list[Sale], tl: list[Point], capital: list[tuple[date, float]] | None = None,
          dividends: list[tuple[date, float]] | None = None) -> list[dict]:
    """Per calendar year: realised gain, and realised gain ÷ average money invested in shares (month-ends).
    With dated deposits/withdrawals (USD, + in / − out): also realised gain ÷ (capital at the start of the year
    + money added during it), capital at start = net deposits so far + gains realised so far."""
    by: dict[int, dict] = {}
    for s in sales:
        y = by.setdefault(s.date.year, {"year": s.date.year, "sales": 0, "not_computed": 0, "gain_usd": 0.0, "wins": 0,
                                        "losses": 0, "cost_usd": 0.0, "proceeds_usd": 0.0})
        y["sales"] += 1
        if s.gain_usd is None:
            y["not_computed"] += 1
            continue
        y["gain_usd"] += s.gain_usd
        y["wins"] += s.gain_usd > 0
        y["losses"] += s.gain_usd < 0
        y["cost_usd"] += s.cost_usd
        y["proceeds_usd"] += s.proceeds_usd
    inv_by_year: dict[int, list[float]] = defaultdict(list)
    for p in tl:
        inv_by_year[p.date.year].append(p.invested_usd)
    for y in set(inv_by_year) - set(by):
        by[y] = {"year": y, "sales": 0, "not_computed": 0, "gain_usd": 0.0, "wins": 0, "losses": 0, "cost_usd": 0.0, "proceeds_usd": 0.0}
    div_by_year: dict[int, float] = defaultdict(float)
    for d, v in dividends or []:
        div_by_year[d.year] += v
    for y in set(div_by_year) - set(by):
        by[y] = {"year": y, "sales": 0, "not_computed": 0, "gain_usd": 0.0, "wins": 0, "losses": 0, "cost_usd": 0.0, "proceeds_usd": 0.0}
    out = []
    realised_before = 0.0
    for y in sorted(by):
        r = by[y]
        r["dividends_usd"] = div_by_year.get(y, 0.0)
        r["income_usd"] = r["gain_usd"] + r["dividends_usd"]
        avg_inv = sum(inv_by_year[y]) / len(inv_by_year[y]) if inv_by_year.get(y) else None
        r["avg_invested_usd"] = avg_inv
        r["return_on_invested_pct"] = (r["gain_usd"] + div_by_year.get(y, 0.0)) / avg_inv * 100 if avg_inv else None
        r["win_rate_pct"] = r["wins"] / (r["sales"] - r["not_computed"]) * 100 if r["sales"] - r["not_computed"] else None
        if capital:
            start = date(y, 1, 1)
            before = sum(v for d, v in capital if d < start)
            added = sum(v for d, v in capital if d.year == y and v > 0)
            base = before + realised_before + added
            r["capital_start_usd"] = before + realised_before
            r["capital_added_usd"] = added
            r["return_on_capital_pct"] = r["income_usd"] / base * 100 if base > 0 else None
        realised_before += r["income_usd"]
        out.append(r)
    return out


# ---------------------------------------------------------------- per stock

def per_stock(sales: list[Sale], lots: list[Lot], buys: list[dict], values: dict[str, dict],
              dividends: list[tuple[date, float, str]] | None = None) -> list[dict]:
    """buys: [{pool, stock, stock_key, currency, date, shares, price, cost_usd, row}] for every purchase in the
    results; values: pool -> {value_usd, unrealised_usd, price} from the open-positions view."""
    out: dict[str, dict] = {}

    def entry(pool: str, stock: str, key: str, cur: str) -> dict:
        return out.setdefault(pool, {"pool": pool, "stock": stock, "stock_key": key, "currency": cur, "buys": 0, "sells": 0,
                                     "shares_bought": 0.0, "shares_sold": 0.0, "bought_local": 0.0, "sold_local": 0.0,
                                     "bought_usd": 0.0, "realised_usd": 0.0, "realised_not_computed": 0, "open_shares": 0.0,
                                     "value_usd": None, "unrealised_usd": None, "first": None, "last": None, "dividends_usd": 0.0})

    for b in buys:
        e = entry(b["pool"], b["stock"], b["stock_key"], b["currency"])
        e["buys"] += 1
        e["shares_bought"] += b["shares"]
        e["bought_local"] += b["shares"] * b["price"]
        if b["cost_usd"] is not None:
            e["bought_usd"] += b["cost_usd"]
        e["first"] = min(filter(None, [e["first"], b["date"]]))
        e["last"] = max(filter(None, [e["last"], b["date"]]))
    for s in sales:
        e = entry(f"{s.stock_key}|{s.currency}", s.stock, s.stock_key, s.currency)
        e["sells"] += 1
        e["shares_sold"] += s.shares
        e["sold_local"] += s.shares * s.price
        if s.gain_usd is None:
            e["realised_not_computed"] += 1
        else:
            e["realised_usd"] += s.gain_usd
        e["last"] = max(filter(None, [e["last"], s.date]))
    for lot in lots:
        out[f"{lot.stock_key}|{lot.currency}"]["open_shares"] += lot.shares
    for d, v, key in dividends or []:
        pools = [k for k, e in out.items() if e["stock_key"] == key]
        if pools:
            out[sorted(pools, key=lambda k: -out[k]["bought_usd"])[0]]["dividends_usd"] += v
    rows = []
    for pool, e in out.items():
        v = values.get(pool)
        if v:
            e["value_usd"], e["unrealised_usd"] = v.get("value_usd"), v.get("unrealised_usd")
        e["avg_buy_price"] = e["bought_local"] / e["shares_bought"] if e["shares_bought"] else None
        e["avg_sell_price"] = e["sold_local"] / e["shares_sold"] if e["shares_sold"] else None
        e["total_usd"] = e["realised_usd"] + (e["unrealised_usd"] or 0.0) + e["dividends_usd"]
        e["total_return_pct"] = e["total_usd"] / e["bought_usd"] * 100 if e["bought_usd"] else None
        e["status"] = "open" if e["open_shares"] > 1e-9 else "closed"
        for k in ("first", "last"):
            e[k] = e[k].isoformat() if isinstance(e[k], date) else e[k]
        for k in ("bought_local", "sold_local"):
            e.pop(k)
        rows.append(e)
    return sorted(rows, key=lambda e: -e["total_usd"])


# ---------------------------------------------------------------- returns

def returns(buys: list[tuple[date, float]], sales: list[Sale], open_value_usd: float | None, open_cost_usd: float | None,
            as_of: date, capital: list[tuple[date, float]] | None, dividends: list[tuple[date, float]] | None = None) -> dict:
    ss = _done(sales)
    realised = sum(s.gain_usd for s in ss)
    divs = sum(v for _, v in dividends or [])
    unreal = (open_value_usd - open_cost_usd) if open_value_usd is not None and open_cost_usd is not None else None
    total = realised + (unreal or 0.0) + divs
    trade_flows = [(d, -c) for d, c in buys if c is not None] + [(s.date, s.proceeds_usd) for s in ss] + list(dividends or [])
    if open_value_usd:
        trade_flows.append((as_of, open_value_usd))
    out = {
        "realised_usd": realised, "unrealised_usd": unreal, "dividends_usd": divs, "total_gain_usd": total,
        "money_in_shares": {
            "xirr_pct": _pct(xirr(trade_flows)),
            "cost_of_shares_sold_usd": sum(s.cost_usd for s in ss),
            "return_on_cost_sold_pct": realised / sum(s.cost_usd for s in ss) * 100 if ss and sum(s.cost_usd for s in ss) else None,
            "explain": "Money-weighted annual return of your trades: every purchase is money in, every sale and dividend money "
                       "out, and the open positions count at today's value. Cash waiting in your accounts isn't included.",
        },
        "capital": None,
    }
    if capital:
        net = sum(v for _, v in capital)
        flows = [(d, -v) for d, v in capital]
        end_value = net + total
        flows.append((as_of, end_value))
        out["capital"] = {
            "deposits_usd": sum(v for _, v in capital if v > 0), "withdrawals_usd": -sum(v for _, v in capital if v < 0),
            "net_usd": net, "end_value_usd": end_value,
            "simple_return_pct": total / net * 100 if net > 0 else None,
            "xirr_pct": _pct(xirr(flows)),
            "explain": "Assumes everything you put in is still in your accounts (in shares or cash) and grew only by these "
                       "gains: before fees, dividends and interest.",
        }
    return out


def _pct(x: float | None) -> float | None:
    return None if x is None or math.isnan(x) else x * 100
