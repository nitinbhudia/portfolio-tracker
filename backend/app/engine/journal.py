"""Trade journal: what you wrote about each trade, and what the prices say happened (pure functions, no I/O).

One entry per trade (a buy or a sale). Entries are keyed by what the trade *is* (kind, date, stock, currency, shares,
price), not by its sheet row, so they stay attached when you re-upload the workbook and rows move. Two identical
trades on the same day are told apart by their order.

Filled in automatically, for every trade, with or without notes:
- at a buy: how far the price was below its 1-year high, and whether the S&P 500 was above its 200-day average;
- at a sale: the gain, days held, the gain the same money made in the S&P 500 over the same days, and the best and worst
  point while you held it (from daily closes);
- plan vs reality, when the buy's entry has a target, a stop or a time frame.
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta

REASONS = ["Fibonacci bounce", "Breakout", "Dip buy", "Momentum", "Earnings", "Alpha pick", "Long-term hold",
           "Idea from others"]
SELL_REASONS = ["Hit target", "Hit stop", "Idea no longer holds", "Took profit early", "Needed the cash",
                "Nervous / market fall", "Rebalance", "Better idea elsewhere"]
STOP_SLACK = 0.02     # a sale within 2% of the stop counts as "sold at the stop"
TARGET_SLACK = 0.02


def trade_keys(trades) -> dict[str, str]:
    """trade id (sheet row based, changes when rows move) -> stable journal key."""
    seen: dict[str, int] = {}
    out = {}
    for t in sorted(trades, key=lambda t: (t.date, t.kind, t.stock_key, t.currency, t.shares, t.price, t.row)):
        base = f"{t.kind}|{t.date.isoformat()}|{t.stock_key}|{t.currency}|{round(t.shares, 6):g}|{round(t.price, 6):g}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out[t.id] = f"{base}|{n}"
    return out


def _window(closes: list[tuple[date, float]], a: date, b: date) -> list[tuple[date, float]]:
    ds = [d for d, _ in closes]
    return closes[bisect.bisect_left(ds, a): bisect.bisect_right(ds, b)]


def from_high(closes: list[tuple[date, float]], d: date, price: float) -> float | None:
    """% below the highest close of the year before `d` (0 = at the high)."""
    w = _window(closes, d - timedelta(days=365), d)
    if len(w) < 20:
        return None
    hi = max(c for _, c in w)
    return (price / hi - 1) * 100 if hi > 0 else None


def market_trend(spx: list[tuple[date, float]], d: date) -> dict | None:
    """S&P 500 on day `d`: above or below its 200-day average, and its change over the 3 months before."""
    w = _window(spx, d - timedelta(days=320), d)
    if len(w) < 150:
        return None
    last = w[-1][1]
    avg = sum(c for _, c in w[-200:]) / len(w[-200:])
    m3 = _window(spx, d - timedelta(days=92), d)
    return {"above_200d": last >= avg, "vs_200d_pct": (last / avg - 1) * 100,
            "change_3m_pct": (last / m3[0][1] - 1) * 100 if m3 else None}


def excursion(closes: list[tuple[date, float]], a: date, b: date, ref: float) -> dict | None:
    """Best and worst close between `a` and `b`, as % from `ref` (the buy price)."""
    w = _window(closes, a, b)
    if len(w) < 2 or ref <= 0:
        return None
    hi = max(w, key=lambda x: x[1])
    lo = min(w, key=lambda x: x[1])
    return {"best_pct": (hi[1] / ref - 1) * 100, "best_date": hi[0].isoformat(), "best_price": hi[1],
            "worst_pct": (lo[1] / ref - 1) * 100, "worst_date": lo[0].isoformat(), "worst_price": lo[1]}


def plan_check(plan: dict, sell_price: float | None, days: int | None, exc: dict | None) -> list[dict]:
    """Compare a sale with the plan written at the buy: target, stop, expected holding time (days)."""
    out: list[dict] = []
    target, stop, horizon = plan.get("target"), plan.get("stop"), plan.get("horizon_days")
    best = exc["best_price"] if exc else None
    worst = exc["worst_price"] if exc else None
    if stop and sell_price is not None:
        if sell_price < stop * (1 - STOP_SLACK):
            out.append({"code": "below_stop", "good": False, "text": f"Sold at {sell_price:g}, below your stop of {stop:g}."})
        elif sell_price <= stop * (1 + STOP_SLACK):
            out.append({"code": "at_stop", "good": True, "text": f"Sold at your stop ({stop:g}) as planned."})
        elif worst is not None and worst < stop:
            out.append({"code": "stop_crossed", "good": False,
                        "text": f"The price went below your stop ({stop:g}, low {worst:g}) and you kept holding."})
    if target and sell_price is not None:
        if sell_price >= target * (1 - TARGET_SLACK):
            out.append({"code": "at_target", "good": True, "text": f"Reached your target of {target:g}."})
        elif best is not None and best >= target:
            out.append({"code": "gave_back", "good": False,
                        "text": f"The price reached your target ({target:g}, high {best:g}) but you sold lower, at {sell_price:g}."})
        else:
            out.append({"code": "before_target", "good": None, "text": f"Sold before your target of {target:g}."})
    if horizon and days is not None:
        if days > horizon * 1.5:
            out.append({"code": "held_longer", "good": None, "text": f"Held {days} days; you planned about {horizon}."})
        elif days < horizon * 0.5:
            out.append({"code": "sold_sooner", "good": None, "text": f"Sold after {days} days; you planned about {horizon}."})
    return out


def _bucket_days(d: int | None) -> str:
    if d is None:
        return "unknown"
    return "under 1 month" if d < 31 else "1–6 months" if d < 183 else "6–12 months" if d < 366 else "over 1 year"


def stats(sales: list[dict]) -> dict:
    """What works: sales grouped by buy reason, sale group, confidence, sell reason and holding time.
    Each sale dict: gain_usd, gain_pct, days, reasons (list), group, confidence, sell_reason, plan (list of checks)."""
    def agg(key_fn) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for s in sales:
            for k in key_fn(s):
                groups.setdefault(k, []).append(s)
        rows = []
        for k, xs in groups.items():
            done = [x for x in xs if x["gain_usd"] is not None]
            pcts = [x["gain_pct"] for x in done if x["gain_pct"] is not None]
            days = [x["days"] for x in done if x["days"] is not None]
            rows.append({"label": k, "sales": len(xs), "wins": sum(x["gain_usd"] > 0 for x in done),
                         "win_rate": sum(x["gain_usd"] > 0 for x in done) / len(done) * 100 if done else None,
                         "avg_gain_pct": sum(pcts) / len(pcts) if pcts else None,
                         "total_gain_usd": sum(x["gain_usd"] for x in done),
                         "avg_days": sum(days) / len(days) if days else None})
        return sorted(rows, key=lambda r: (-r["sales"], r["label"]))
    checks = [c for s in sales for c in s.get("plan") or []]
    return {
        "by_reason": agg(lambda s: s["reasons"] or ["(no reason written)"]),
        "by_group": agg(lambda s: [s["group"] or "Not grouped"]),
        "by_confidence": agg(lambda s: [f"{s['confidence']} of 5" if s.get("confidence") else "(not rated)"]),
        "by_sell_reason": agg(lambda s: [s["sell_reason"] or "(no reason written)"]),
        "by_holding": agg(lambda s: [_bucket_days(s["days"])]),
        "plan": {"sales_with_plan": sum(1 for s in sales if s.get("plan")),
                 "followed": sum(1 for c in checks if c["good"] is True),
                 "broke": sum(1 for c in checks if c["good"] is False),
                 "by_code": {code: sum(1 for c in checks if c["code"] == code) for code in sorted({c["code"] for c in checks})}},
        "journaled_sales": sum(1 for s in sales if s["reasons"] or s["sell_reason"]),
        "sales": len(sales),
    }


# ---------------------------------------------------------------- ideas: price levels to watch

NEAR_PCT = 3.0


def check_levels(levels: list[dict], bars: list[tuple[date, float, float, float]], fired: set[tuple[str, str]],
                 near_pct: float = NEAR_PCT, hit_from: date | None = None) -> list[dict]:
    """New triggers for an idea. levels: [{label, price}]; bars: (date, high, low, close), oldest first: the last close
    before the idea was written, then every day since; fired: (label, kind) already triggered. A level is *hit* when a
    day's range touches it (days from `hit_from` on), and *near* when a close is within near_pct % of it (before it's
    hit; the latest close when you write the idea counts). Each fires once per level."""
    out = []
    for lv in levels:
        p = lv.get("price")
        if not p or p <= 0:
            continue
        label = lv.get("label") or f"{p:g}"
        hit = near = None
        for d, hi, lo, close in bars:
            if hit is None and lo <= p <= hi and (hit_from is None or d >= hit_from):
                hit = (d, close)
            if near is None and abs(close / p - 1) * 100 <= near_pct:
                near = (d, close)
        if hit and (label, "hit") not in fired:
            out.append({"label": label, "level": p, "kind": "hit", "date": hit[0], "price": hit[1]})
        if near and (label, "near") not in fired and (label, "hit") not in fired and (not hit or near[0] < hit[0]):
            out.append({"label": label, "level": p, "kind": "near", "date": near[0], "price": near[1]})
    return out


def distances(levels: list[dict], price: float | None) -> list[dict]:
    """Each level with how far today's price is from it (% of today's price; negative = level below)."""
    return [{**lv, "distance_pct": (lv["price"] / price - 1) * 100 if price and lv.get("price") else None} for lv in levels]
