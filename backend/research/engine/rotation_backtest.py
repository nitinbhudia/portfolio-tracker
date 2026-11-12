"""Rotation backtest (ROTATION_BACKTEST_TASK.md): sector-rotation rules as an equal-weight ETF portfolio.

Reuses the RRG approximation (`rrg`), rotation metrics/transitions/score (`rotation`), and the Phase 7
metrics and selection rules (`backtest`). Decisions at bar t's close use only data up to t; rebalancing
happens at bar t+1's open. Costs are charged on the value traded. Past performance does not guarantee
future results.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from research.core.hashing import stable_hash

from . import backtest as B
from . import indicators, rotation, rrg

ROTATION_BACKTEST_VERSION = "rotation-backtest-v1"
HOLD_SETS = {"improving": ("improving",), "improving_leading": ("improving", "leading"), "leading": ("leading",)}
HOLD_LABELS = {"improving": "Improving", "improving_leading": "Improving + Leading", "leading": "Leading"}


# ---------------------------------------------------------------- aligned universe

class Universe:
    """Benchmark and sector ETFs on common dates, with RRG series, indicators and scores evaluated lazily."""

    def __init__(self, dates: list[date], bench_open, bench_close, sectors: dict[str, dict], benchmark: str = "SPY"):
        self.dates = list(dates)
        self.n = len(self.dates)
        self.benchmark = benchmark
        self.bo = np.asarray(bench_open, dtype="float64")
        self.bc = np.asarray(bench_close, dtype="float64")
        self.tickers = sorted(sectors)
        self.sector_names = {t: sectors[t].get("sector", t) for t in self.tickers}
        self.o = {t: np.asarray(sectors[t]["open"], dtype="float64") for t in self.tickers}
        self.c = {t: np.asarray(sectors[t]["close"], dtype="float64") for t in self.tickers}
        self.v = {t: np.asarray(sectors[t]["volume"], dtype="float64") for t in self.tickers}
        h = {t: np.asarray(sectors[t].get("high", sectors[t]["close"]), dtype="float64") for t in self.tickers}
        lo = {t: np.asarray(sectors[t].get("low", sectors[t]["close"]), dtype="float64") for t in self.tickers}
        self.ind = {t: indicators.compute_all(self.o[t], h[t], lo[t], self.c[t], self.v[t]) for t in self.tickers}
        self._rrg: dict[str, dict[str, rrg.RrgSeries]] = {}
        self._score: dict[tuple[str, int], dict[str, float | None]] = {}

    def series(self, tf: str) -> dict[str, rrg.RrgSeries]:
        if tf not in self._rrg:
            self._rrg[tf] = {t: rrg.compute(self.c[t], self.bc, tf) for t in self.tickers}
        return self._rrg[tf]

    def quadrant(self, tf: str, tk: str, t: int) -> str | None:
        s = self.series(tf)[tk]
        return rrg.quadrant(float(s.ratio[t]), float(s.momentum[t]))

    def scores(self, tf: str, t: int) -> dict[str, float | None]:
        key = (tf, t)
        if key not in self._score:
            out = {}
            for tk in self.tickers:
                s = self.series(tf)[tk]
                m = rotation.metrics(self.c[tk], self.v[tk], self.ind[tk], self.bc, t)
                ev = rotation.transitions(s, self.dates, self.c[tk], self.ind[tk]["sma50"], t)
                out[tk] = rotation.score(s, m, ev, t)["total"]
            self._score[key] = out
        return self._score[key]


# ---------------------------------------------------------------- strategies

class RotationStrategy:
    id = ""
    name = ""
    description = ""
    params: dict[str, dict] = {}

    def grid(self) -> list[dict]:
        keys = list(self.params)
        return [dict(zip(keys, v)) for v in itertools.product(*(self.params[k]["choices"] for k in keys))]

    def defaults(self) -> dict:
        return {k: v["default"] for k, v in self.params.items()}

    def desired(self, u: Universe, t: int, p: dict, step: int) -> frozenset | None:
        """Sectors to hold from the next open, or None to keep the current holdings."""
        raise NotImplementedError


class QuadrantHold(RotationStrategy):
    id, name = "quadrant_hold", "Hold sectors by RRG quadrant"
    description = ("Hold, in equal weight, every sector whose RRG quadrant is in the chosen set; buy when a sector enters "
                   "the set, sell when it leaves; cash when none qualifies.")
    params = {"hold": {"choices": list(HOLD_SETS), "default": "improving_leading", "label": "Hold sectors in",
                       "labels": HOLD_LABELS},
              "timeframe": {"choices": ["1m", "3m"], "default": "3m", "label": "RRG timeframe",
                            "labels": {"1m": "1 month", "3m": "3 months"}}}

    def desired(self, u, t, p, step):
        want = HOLD_SETS[p["hold"]]
        return frozenset(tk for tk in u.tickers if u.quadrant(p["timeframe"], tk, t) in want)


class TopScore(RotationStrategy):
    id, name = "top_score", "Top sectors by Rotation Signal Score"
    description = "Every k sessions, hold the N sectors with the highest Rotation Signal Score (default weights), in equal weight."
    params = {"n": {"choices": [2, 3, 5], "default": 3, "label": "Number of sectors"},
              "every": {"choices": [5, 10, 21], "default": 10, "label": "Re-select every (sessions)"},
              "timeframe": {"choices": ["1m", "3m"], "default": "3m", "label": "RRG timeframe",
                            "labels": {"1m": "1 month", "3m": "3 months"}}}

    def desired(self, u, t, p, step):
        if step % p["every"] != 0:
            return None
        sc = u.scores(p["timeframe"], t)
        ranked = sorted((tk for tk in u.tickers if sc[tk] is not None), key=lambda tk: (-sc[tk], tk))
        return frozenset(ranked[: p["n"]])


STRATEGIES: dict[str, RotationStrategy] = {s.id: s for s in (QuadrantHold(), TopScore())}


def validate_params(strat: RotationStrategy, p: dict | None) -> dict:
    out = strat.defaults()
    for k, v in (p or {}).items():
        if k not in strat.params:
            raise ValueError(f"unknown parameter '{k}' for {strat.id}")
        if v not in strat.params[k]["choices"]:
            raise ValueError(f"{k} must be one of {strat.params[k]['choices']}")
        out[k] = v
    return out


# ---------------------------------------------------------------- simulation

@dataclass
class PResult:
    start: int
    end: int
    curve: list[float]
    invested: list[bool]
    trades: list[dict] = field(default_factory=list)
    days_held: dict[str, int] = field(default_factory=dict)


def simulate(u: Universe, strat: RotationStrategy, p: dict, costs: B.Costs, start: int, end: int,
             start_equity: float = 1.0) -> PResult:
    if not (0 < start < end <= u.n):
        raise ValueError("invalid window")
    k = len(u.tickers)
    idx = {tk: i for i, tk in enumerate(u.tickers)}
    units = np.zeros(k)
    cash = start_equity
    held: frozenset = frozenset()
    pending: frozenset | None = None
    open_trades: dict[str, tuple[int, float]] = {}  # ticker -> (entry bar, entry price incl. slippage)
    res = PResult(start, end, [], [], [], {tk: 0 for tk in u.tickers})
    rate = costs.comm + costs.slip

    def close_trade(tk: str, t: int, px: float, reason: str):
        i0, entry = open_trades.pop(tk)
        exit_px = px * (1 - costs.slip)
        ret = exit_px / entry * (1 - costs.comm) ** 2 - 1
        res.trades.append({"sector": u.sector_names[tk], "ticker": tk, "entry_date": u.dates[i0].isoformat(),
                           "entry_price": entry, "exit_date": u.dates[t].isoformat(), "exit_price": exit_px,
                           "bars_held": t - i0 + 1, "return_pct": ret * 100, "exit_reason": reason,
                           "entry_note": f"{u.sector_names[tk]} ({tk})"})

    for t in range(start, end):
        if pending is not None:
            px = np.array([u.o[tk][t] for tk in u.tickers])
            value = cash + float(units @ px)
            target = np.zeros(k)
            if pending:
                w = 1.0 / len(pending)
                for tk in pending:
                    target[idx[tk]] = value * w / px[idx[tk]]
            cost = float(np.abs(target - units) @ px) * rate
            scale = (value - cost) / value if value > 0 else 0.0
            target *= scale
            for tk in held - pending:
                close_trade(tk, t, u.o[tk][t], "left the selection")
            for tk in pending - held:
                open_trades[tk] = (t, u.o[tk][t] * (1 + costs.slip))
            units = target
            cash = (value - cost) - float(units @ px)
            held, pending = pending, None
        res.curve.append(cash + float(units @ np.array([u.c[tk][t] for tk in u.tickers])))
        res.invested.append(bool(held))
        for tk in held:
            res.days_held[tk] += 1
        if t < end - 1:
            want = strat.desired(u, t, p, t - start)
            if want is not None and want != held:
                pending = want
    if held:  # close at the last close, with costs
        last = end - 1
        px = np.array([u.c[tk][last] for tk in u.tickers])
        value = cash + float(units @ px)
        value -= float(units @ px) * rate
        for tk in sorted(held):
            close_trade(tk, last, u.c[tk][last], "end of period")
            res.trades[-1]["open_at_end"] = True
        res.curve[-1] = value
    return res


def benchmark_hold(u: Universe, costs: B.Costs, start: int, end: int) -> PResult:
    units = (1 - costs.comm) / (u.bo[start] * (1 + costs.slip))
    curve = [units * u.bc[t] for t in range(start, end)]
    curve[-1] = units * u.bc[end - 1] * (1 - costs.slip) * (1 - costs.comm)
    return PResult(start, end, curve, [True] * (end - start))


def equal_weight_hold(u: Universe, costs: B.Costs, start: int, end: int) -> PResult:
    k = len(u.tickers)
    units = {tk: (1 - costs.comm) / k / (u.o[tk][start] * (1 + costs.slip)) for tk in u.tickers}
    curve = [sum(units[tk] * u.c[tk][t] for tk in u.tickers) for t in range(start, end)]
    curve[-1] = curve[-1] * (1 - costs.slip) * (1 - costs.comm)
    return PResult(start, end, curve, [True] * (end - start))


# ---------------------------------------------------------------- report

def _by_year(u: Universe, res: PResult, bh: PResult, ew: PResult) -> list[dict]:
    years: dict[int, int] = {}
    for i, t in enumerate(range(res.start, res.end)):
        years[u.dates[t].year] = i
    out, prev = [], (1.0, 1.0, 1.0)
    for y, i in sorted(years.items()):
        cur = (res.curve[i], bh.curve[i], ew.curve[i])
        out.append({"year": y, "strategy_pct": (cur[0] / prev[0] - 1) * 100, "buy_hold_pct": (cur[1] / prev[1] - 1) * 100,
                    "equal_weight_pct": (cur[2] / prev[2] - 1) * 100,
                    "trades_closed": sum(1 for t in res.trades if t["exit_date"].startswith(str(y)))})
        prev = cur
    return out


def _segment(u: Universe, label: str, res: PResult, costs: B.Costs, params: dict | None) -> dict:
    bh = benchmark_hold(u, costs, res.start, res.end)
    ew = equal_weight_hold(u, costs, res.start, res.end)
    sm = B.metrics(res.curve, res.invested, res.trades)
    n = res.end - res.start
    return {"label": label, "start_date": u.dates[res.start].isoformat(), "end_date": u.dates[res.end - 1].isoformat(),
            "params": params, "metrics": sm, "buy_hold": B.metrics(bh.curve, bh.invested, []),
            "equal_weight": B.metrics(ew.curve, ew.invested, []), "by_year": _by_year(u, res, bh, ew),
            "trades": res.trades, "few_trades": sm["trades"] < 10,
            "time_in_sector_pct": {tk: res.days_held[tk] / n * 100 for tk in u.tickers},
            "curve": {"dates": [u.dates[t].isoformat() for t in range(res.start, res.end)],
                      "strategy": [round(x, 6) for x in res.curve], "buy_hold": [round(x, 6) for x in bh.curve],
                      "equal_weight": [round(x, 6) for x in ew.curve]}}


# ---------------------------------------------------------------- validation

def warmup_for(timeframes) -> int:
    return max([B.WARMUP] + [rrg.bars_needed(tf, 0) for tf in timeframes])


def select(u: Universe, strat: RotationStrategy, costs: B.Costs, a: int, b: int, grid: list[dict]):
    best, best_s, best_m, scores = None, float("-inf"), None, []
    for p in grid:
        r = simulate(u, strat, p, costs, a, b)
        m = B.metrics(r.curve, r.invested, r.trades)
        s = B._score(m)
        scores.append({"params": p, "sharpe_like": m["sharpe_like"], "trades": m["trades"], "total_return_pct": m["total_return_pct"]})
        if s > best_s:
            best, best_s, best_m = p, s, m
    if best is None:
        best = grid[0]
        r = simulate(u, strat, best, costs, a, b)
        best_m = {**B.metrics(r.curve, r.invested, r.trades), "fallback": True}
    return best, best_m, scores


def run(u: Universe, strategy_id: str, mode: str, params: dict | None, costs: B.Costs,
        holdout_pct: float = 0.2, folds: int = 2) -> dict:
    if strategy_id not in STRATEGIES:
        raise ValueError(f"unknown rotation strategy '{strategy_id}'")
    strat = STRATEGIES[strategy_id]
    if mode not in ("single", "walk_forward"):
        raise ValueError("mode must be 'single' or 'walk_forward'")
    if not 0.1 <= holdout_pct <= 0.4:
        raise ValueError("holdout must be between 10% and 40%")
    if len(u.tickers) < 3:
        raise ValueError("needs at least 3 sector ETFs with full history")
    grid = strat.grid()
    if mode == "single":
        p = validate_params(strat, params)
        warm = warmup_for([p["timeframe"]])
    else:
        if params:
            raise ValueError("walk-forward chooses parameters itself; don't pass params")
        if not 2 <= folds <= 6:
            raise ValueError("folds must be between 2 and 6")
        warm = warmup_for({g["timeframe"] for g in grid})
    if u.n < warm + 100:
        raise ValueError(f"needs at least {warm + 100} aligned daily bars ({warm} warm-up + 100 to trade); there are {u.n}")
    start, hold = warm, warm + int(round((u.n - warm) * (1 - holdout_pct)))
    out = {"version": ROTATION_BACKTEST_VERSION, "kind": "rotation", "strategy": f"rotation:{strategy_id}",
           "strategy_name": strat.name, "description": strat.description, "mode": mode,
           "benchmark": u.benchmark, "sectors": [{"ticker": t, "sector": u.sector_names[t]} for t in u.tickers],
           "costs": {"commission_bps": costs.commission_bps, "slippage_bps": costs.slippage_bps},
           "holdout_pct": holdout_pct, "warmup_bars": warm, "disclaimer": B.DISCLAIMER,
           "periods": {"tradable_from": u.dates[start].isoformat(), "holdout_from": u.dates[hold].isoformat(),
                       "until": u.dates[-1].isoformat()}}
    if mode == "single":
        ins = simulate(u, strat, p, costs, start, hold)
        out.update(final_params=p, combinations_tested=1, main=_segment(u, "In-sample", ins, costs, p))
    else:
        if (hold - start) // (folds + 1) < B.MIN_BLOCK_BARS:
            raise ValueError(f"not enough history for {folds} folds (each block needs {B.MIN_BLOCK_BARS}+ bars); "
                             "use fewer folds or a smaller holdout")
        edges = [start + (hold - start) * i // (folds + 1) for i in range(folds + 2)]
        rows, curve, invested, trades, eq = [], [], [], [], 1.0
        days = {tk: 0 for tk in u.tickers}
        for i in range(1, folds + 1):
            p, train_m, _ = select(u, strat, costs, edges[0], edges[i], grid)
            test = simulate(u, strat, p, costs, edges[i], edges[i + 1], start_equity=eq)
            rows.append({"fold": i, "train": [u.dates[edges[0]].isoformat(), u.dates[edges[i] - 1].isoformat()],
                         "test": [u.dates[edges[i]].isoformat(), u.dates[edges[i + 1] - 1].isoformat()],
                         "params": p, "train_metrics": train_m,
                         "test_metrics": B.metrics(test.curve, test.invested, test.trades, start_equity=eq),
                         "selection_fallback": bool(train_m.get("fallback"))})
            curve += test.curve
            invested += test.invested
            trades += test.trades
            for tk, d in test.days_held.items():
                days[tk] += d
            eq = test.curve[-1]
        oos = PResult(edges[1], hold, curve, invested, trades, days)
        final_p, final_m, scores = select(u, strat, costs, start, hold, grid)
        out.update(final_params=final_p, final_selection={"metrics": final_m, "grid_scores": scores}, folds=rows,
                   combinations_tested=len(grid) * (folds + 1),
                   main=_segment(u, "Out-of-sample (walk-forward)", oos, costs, None))
        p = final_p
    hres = simulate(u, strat, p, costs, hold, u.n)
    out["holdout"] = _segment(u, "Holdout (untouched until now)", hres, costs, p)
    out["request_hash"] = stable_hash({"strategy": strategy_id, "mode": mode, "params": params or {}, "costs": out["costs"],
                                       "holdout_pct": holdout_pct, "folds": folds if mode == "walk_forward" else None,
                                       "benchmark": u.benchmark, "version": ROTATION_BACKTEST_VERSION})
    return out
