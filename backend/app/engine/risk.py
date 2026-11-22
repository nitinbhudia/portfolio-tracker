"""Risk of the portfolio you hold today (pure functions, no I/O).

Two kinds of answer:

- **Concentration and exposure** come from today's values only: how much rides on the biggest positions, the effective
  number of positions (1 / sum of squared weights), and the split by sector, currency and broker.
- **Market risk** replays the *current* holdings (today's weights) over a past window of daily USD closes (local close ×
  that day's ECB rate, adjusted for splits). That is the standard "how risky is what I own now" view: it is not your
  past performance (trades in the window are ignored). From those daily returns: annualised volatility, the deepest
  fall (maximum drawdown), the 1-day loss you'd exceed on 1 day in 20 (historical VaR 95%) and the average loss on those
  days (expected shortfall), beta and correlation to the S&P 500, each position's share of the risk, and correlations.

Positions without enough price history in the window are left out of market risk (listed, with their weight); the
market-drop estimate counts them with a beta of 1.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date

import numpy as np

TRADING_DAYS = 252
WINDOWS = {"6m": 126, "1y": 252, "3y": 756}
LARGE = 10.0          # % of the portfolio: a large position
VERY_LARGE = 20.0
SHOCKS = (-10.0, -20.0, -30.0)
MAX_CORR = 12         # biggest positions in the correlation grid
START_SLACK = 7       # a series may start up to this many trading days into the window
END_SLACK_DAYS = 10   # and end up to this many calendar days before its end


@dataclass
class Holding:
    key: str
    label: str
    value_usd: float
    sector: str | None = None
    currency: str = "USD"
    brokers: dict[str, float] = field(default_factory=dict)  # broker -> USD value


def _share(rows: dict[str, float], total: float) -> list[dict]:
    return [{"label": k, "value_usd": v, "pct": v / total * 100 if total else None}
            for k, v in sorted(rows.items(), key=lambda kv: -kv[1])]


def concentration(holdings: list[Holding]) -> dict:
    hs = sorted((h for h in holdings if h.value_usd > 0), key=lambda h: -h.value_usd)
    total = sum(h.value_usd for h in hs)
    w = [h.value_usd / total for h in hs] if total else []
    hhi = sum(x * x for x in w)
    top = lambda n: sum(w[:n]) * 100  # noqa: E731
    return {"total_usd": total, "positions": len(hs), "hhi": hhi, "effective_n": 1 / hhi if hhi else None,
            "largest_pct": w[0] * 100 if w else None, "largest": hs[0].label if hs else None,
            "top5_pct": top(5), "top10_pct": top(10),
            "large": [{"key": h.key, "label": h.label, "pct": x * 100, "very_large": x * 100 >= VERY_LARGE}
                      for h, x in zip(hs, w) if x * 100 >= LARGE],
            "weights": [{"key": h.key, "label": h.label, "value_usd": h.value_usd, "pct": x * 100} for h, x in zip(hs, w)]}


def exposure(holdings: list[Holding]) -> dict:
    total = sum(h.value_usd for h in holdings if h.value_usd > 0)
    sec: dict[str, float] = {}
    cur: dict[str, float] = {}
    brk: dict[str, float] = {}
    for h in holdings:
        if h.value_usd <= 0:
            continue
        sec[h.sector or "No sector set"] = sec.get(h.sector or "No sector set", 0.0) + h.value_usd
        cur[h.currency] = cur.get(h.currency, 0.0) + h.value_usd
        for b, v in (h.brokers or {"Unknown broker": h.value_usd}).items():
            brk[b or "Unknown broker"] = brk.get(b or "Unknown broker", 0.0) + v
    return {"sector": _share(sec, total), "currency": _share(cur, total), "broker": _share(brk, total)}


def _on_grid(series: list[tuple[date, float]], grid: list[date]) -> np.ndarray | None:
    """Closes carried forward onto the grid; None if the series doesn't cover the window."""
    if not series:
        return None
    ds = [d for d, _ in series]
    first_ok = grid[min(START_SLACK, len(grid) - 1)]
    if ds[0] > first_ok or (grid[-1] - ds[-1]).days > END_SLACK_DAYS:
        return None
    out = np.empty(len(grid))
    for k, g in enumerate(grid):
        i = bisect.bisect_right(ds, g) - 1
        out[k] = series[max(i, 0)][1]  # before its first close: the first close (no move)
    return out if np.all(out > 0) else None


def _drawdown(rets: np.ndarray) -> tuple[np.ndarray, float, int, int]:
    idx = np.concatenate([[1.0], np.cumprod(1 + rets)])
    peak = np.maximum.accumulate(idx)
    dd = idx / peak - 1
    trough = int(np.argmin(dd))
    top = int(np.argmax(idx[: trough + 1])) if trough else 0
    return dd, float(dd[trough]), top, trough


def market_risk(holdings: list[Holding], closes: dict[str, list[tuple[date, float]]],
                market: list[tuple[date, float]] | None, end: date, window: str = "1y") -> dict:
    """Replay today's holdings over the window. closes: key -> [(date, USD close)], split-adjusted, sorted."""
    n = WINDOWS[window]
    src = market if market else sorted({d for s in closes.values() for d, _ in s})
    days = [d for d in ((x[0] if isinstance(x, tuple) else x) for x in src) if d <= end]
    grid = days[-(n + 1):]
    live = [h for h in holdings if h.value_usd > 0]
    total = sum(h.value_usd for h in live)
    if len(grid) < 40:
        return {"status": "no_data", "message": "Not enough daily prices yet: download price history on Data ▾ Price history."}
    cols, used, missing = [], [], []
    for h in live:
        p = _on_grid(closes.get(h.key) or [], grid)
        if p is None:
            missing.append({"key": h.key, "label": h.label, "pct": h.value_usd / total * 100,
                            "reason": "no daily prices" if not closes.get(h.key) else "price history doesn't cover the window"})
        else:
            cols.append(p)
            used.append(h)
    out = {"status": "ok", "window": window, "start": grid[0].isoformat(), "end": grid[-1].isoformat(), "days": len(grid) - 1,
           "missing": missing, "covered_pct": sum(h.value_usd for h in used) / total * 100 if total else 0.0}
    mkt = None
    if market:
        mp = _on_grid([(d, v) for d, v in market], grid)
        mkt = mp[1:] / mp[:-1] - 1 if mp is not None else None
    beta_of = {}
    if not used:
        out.update(status="no_data", message="None of your positions has daily prices for this window yet.")
    else:
        P_ = np.column_stack(cols)
        R = P_[1:] / P_[:-1] - 1
        cv = sum(h.value_usd for h in used)
        w = np.array([h.value_usd / cv for h in used])
        rp = R @ w
        S = np.cov(R, rowvar=False, ddof=1) if len(used) > 1 else np.array([[np.var(R[:, 0], ddof=1)]])
        var_p = float(w @ S @ w)
        dd, mdd, top, trough = _drawdown(rp)
        q = float(np.percentile(rp, 5))
        tail = rp[rp <= q]
        roll = np.array([np.prod(1 + rp[i:i + 21]) - 1 for i in range(max(0, len(rp) - 20))]) if len(rp) >= 21 else np.array([])
        if mkt is not None:
            vm = float(np.var(mkt, ddof=1))
            beta = float(np.cov(rp, mkt, ddof=1)[0, 1] / vm) if vm else None
            corr = float(np.corrcoef(rp, mkt)[0, 1])
            beta_of = {h.key: float(np.cov(R[:, i], mkt, ddof=1)[0, 1] / vm) if vm else None for i, h in enumerate(used)}
            _, mkt_mdd, _, _ = _drawdown(mkt)
            mdd_m = _drawdown(mkt)[0]
        else:
            beta = corr = mkt_mdd = None
            mdd_m = None
        marg = S @ w
        rows = []
        for i, h in enumerate(used):
            p = P_[:, i]
            _, mdd_i, _, _ = _drawdown(R[:, i])
            hi = float(np.max(p[-min(len(p), TRADING_DAYS):]))
            rows.append({"key": h.key, "label": h.label, "weight_pct": h.value_usd / total * 100, "value_usd": h.value_usd,
                         "vol_pct": float(np.std(R[:, i], ddof=1) * np.sqrt(TRADING_DAYS) * 100),
                         "beta": beta_of.get(h.key), "max_drawdown_pct": mdd_i * 100,
                         "from_high_pct": (float(p[-1]) / hi - 1) * 100,
                         "risk_share_pct": float(w[i] * marg[i] / var_p * 100) if var_p > 0 else None})
        rows.sort(key=lambda r: -(r["risk_share_pct"] or 0))
        out.update({
            "covered_usd": cv,
            "volatility_pct": float(np.sqrt(var_p * TRADING_DAYS) * 100),
            "max_drawdown_pct": mdd * 100, "drawdown_peak": grid[top].isoformat(), "drawdown_trough": grid[trough].isoformat(),
            "current_drawdown_pct": float(dd[-1]) * 100,
            "var95_pct": -q * 100, "var95_usd": -q * cv, "es95_pct": float(-tail.mean() * 100), "es95_usd": float(-tail.mean() * cv),
            "worst_day_pct": float(rp.min() * 100), "worst_day": grid[int(np.argmin(rp)) + 1].isoformat(),
            "best_day_pct": float(rp.max() * 100),
            "worst_month_pct": float(roll.min() * 100) if roll.size else None,
            "beta": beta, "market_correlation": corr, "market_max_drawdown_pct": mkt_mdd * 100 if mkt_mdd is not None else None,
            "market_volatility_pct": float(np.std(mkt, ddof=1) * np.sqrt(TRADING_DAYS) * 100) if mkt is not None else None,
            "positions": rows,
            "drawdown": {"dates": [d.isoformat() for d in grid], "portfolio": [float(x) * 100 for x in dd],
                         "market": [float(x) * 100 for x in mdd_m] if mdd_m is not None else None},
            "correlation": _correlations(used, R),
        })
    # Market drops: each covered position moves with its own beta; positions without history count with beta 1.
    stress = []
    for s in SHOCKS:
        loss = sum(h.value_usd * (beta_of.get(h.key) if beta_of.get(h.key) is not None else 1.0) * s / 100 for h in live)
        stress.append({"market_pct": s, "change_usd": loss, "change_pct": loss / total * 100 if total else None})
    out["stress"] = stress if market else None
    return out


def _correlations(used: list[Holding], R: np.ndarray) -> dict | None:
    if len(used) < 2:
        return None
    order = sorted(range(len(used)), key=lambda i: -used[i].value_usd)[:MAX_CORR]
    C = np.corrcoef(R[:, order], rowvar=False)
    labels = [used[i].label for i in order]
    pairs = [{"a": labels[i], "b": labels[j], "corr": float(C[i, j])} for i in range(len(order)) for j in range(i + 1, len(order))]
    pairs.sort(key=lambda p: -p["corr"])
    allC = np.corrcoef(R, rowvar=False)
    iu = np.triu_indices(len(used), 1)
    return {"labels": labels, "matrix": [[round(float(v), 3) for v in row] for row in C],
            "average": float(np.mean(allC[iu])), "most": pairs[:5], "least": sorted(pairs, key=lambda p: p["corr"])[:3]}


def adjust_splits(rows: list[tuple[date, float, float]]) -> list[tuple[date, float]]:
    """Raw closes with split factors (Tiingo) -> closes comparable across splits (earlier closes ÷ later splits)."""
    out, f = [], 1.0
    for d, c, s in reversed(rows):
        out.append((d, c / f))
        if s and abs(s - 1) > 1e-9:
            f *= s
    return out[::-1]
