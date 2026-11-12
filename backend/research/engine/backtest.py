"""Backtesting engine (PHASE_7_TASK.md). Pure functions, no I/O.

Event-driven over daily bars, long only, all-in / all-out. At bar t's close a strategy sees
only values at or before t (the Phase 1 indicator arrays are causal; swings count only once
confirmed); orders fill at bar t+1's open. Stops/targets are checked on each bar's high/low,
gaps fill at the open, and a bar touching both is treated as a stop (conservative).

Past performance does not guarantee future results.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from research.core.hashing import stable_hash

from . import fibonacci, indicators, setups, swings

BACKTEST_VERSION = "backtest-v1"
WARMUP = 200                 # no trading before SMA 200 exists, for every strategy
BARS_PER_YEAR = 252
MIN_TRADES_FOR_SELECTION = 3
MIN_BLOCK_BARS = 60          # walk-forward blocks shorter than ~3 months rarely contain enough trades
RSI_MAX_HOLD = 20
DISCLAIMER = "Past performance does not guarantee future results."


@dataclass(frozen=True)
class Costs:
    commission_bps: float = 5.0   # per side
    slippage_bps: float = 10.0    # per side, always against you

    @property
    def comm(self) -> float:
        return self.commission_bps / 10_000

    @property
    def slip(self) -> float:
        return self.slippage_bps / 10_000


# ---------------------------------------------------------------- data context

class Context:
    """Price arrays plus the Phase 1 indicators, swings, Fibonacci and setups, evaluated lazily per bar."""

    def __init__(self, dates: list[date], o, h, l, c, v, atr_multiple: float = 2.5, has_volume: bool = True):
        self.dates = list(dates)
        self.o, self.h, self.l, self.c = (np.asarray(x, dtype="float64") for x in (o, h, l, c))
        self.v = np.asarray(v, dtype="float64")
        self.n = len(self.c)
        self.has_volume = has_volume
        self.ind = indicators.compute_all(self.o, self.h, self.l, self.c, self.v)
        self.sw = swings.detect_swings(self.h, self.l, self.ind["atr14"], atr_multiple)
        self._fib: dict[int, dict] = {}
        self._trig: dict[int, list[str]] = {}

    def val(self, name: str, t: int) -> float | None:
        if t < 0:
            return None
        x = float(self.ind[name][t])
        return None if math.isnan(x) else x

    def fib(self, t: int) -> dict:
        if t not in self._fib:
            atr = self.val("atr14", t)
            self._fib[t] = fibonacci.analyse(swings.confirmed_as_of(self.sw, t), float(self.c[t]), atr)
        return self._fib[t]

    def triggered(self, t: int) -> list[str]:
        if t < 0:
            return []
        if t not in self._trig:
            self._trig[t] = setups.detect_all(self.o, self.h, self.l, self.c, self.v, self.ind, self.fib(t), t,
                                              has_volume=self.has_volume)["triggered"]
        return self._trig[t]


# ---------------------------------------------------------------- strategies

@dataclass
class Signal:
    stop: float | None = None
    target: float | None = None
    note: str = ""


def _cross(ctx: Context, a: str, b: str, t: int) -> str | None:
    a0, b0, a1, b1 = ctx.val(a, t - 1), ctx.val(b, t - 1), ctx.val(a, t), ctx.val(b, t)
    if None in (a0, b0, a1, b1):
        return None
    if a0 <= b0 and a1 > b1:
        return "up"
    if a0 >= b0 and a1 < b1:
        return "down"
    return None


class Strategy:
    id = ""
    name = ""
    description = ""
    params: dict[str, dict] = {}

    def grid(self) -> list[dict]:
        keys = list(self.params)
        combos = [dict(zip(keys, vals)) for vals in itertools.product(*(self.params[k]["choices"] for k in keys))]
        return [p for p in combos if self.valid(p)]

    def valid(self, p: dict) -> bool:
        return True

    def defaults(self) -> dict:
        return {k: v["default"] for k, v in self.params.items()}

    def entry(self, ctx: Context, t: int, p: dict) -> Signal | None:
        raise NotImplementedError

    def exit(self, ctx: Context, t: int, p: dict, held: int) -> bool:
        return False


class MaCross(Strategy):
    id, name = "ma_cross", "Moving-average crossover"
    description = "Buy when SMA fast crosses above SMA slow; sell when it crosses back below."
    params = {"fast": {"choices": [10, 20, 50], "default": 50, "label": "Fast SMA"},
              "slow": {"choices": [50, 100, 200], "default": 200, "label": "Slow SMA"}}

    def valid(self, p):
        return p["fast"] < p["slow"]

    def entry(self, ctx, t, p):
        return Signal(note=f"SMA{p['fast']} crossed above SMA{p['slow']}") \
            if _cross(ctx, f"sma{p['fast']}", f"sma{p['slow']}", t) == "up" else None

    def exit(self, ctx, t, p, held):
        return _cross(ctx, f"sma{p['fast']}", f"sma{p['slow']}", t) == "down"


class RsiReversion(Strategy):
    id, name = "rsi_reversion", "RSI mean reversion"
    description = f"Buy when RSI 14 closes below the entry level; sell when it closes above the exit level or after {RSI_MAX_HOLD} bars."
    params = {"entry": {"choices": [25, 30, 35], "default": 30, "label": "Buy below RSI"},
              "exit": {"choices": [50, 60, 70], "default": 50, "label": "Sell above RSI"}}

    def entry(self, ctx, t, p):
        r = ctx.val("rsi14", t)
        return Signal(note=f"RSI {r:.1f} < {p['entry']}") if r is not None and r < p["entry"] else None

    def exit(self, ctx, t, p, held):
        r = ctx.val("rsi14", t)
        return (r is not None and r > p["exit"]) or held >= RSI_MAX_HOLD


class MacdCross(Strategy):
    id, name = "macd_cross", "MACD crossover"
    description = "Buy when the MACD line crosses above its signal line (optionally only above SMA 200); sell on the cross below."
    params = {"trend_filter": {"choices": [False, True], "default": True, "label": "Only above SMA 200"}}

    def entry(self, ctx, t, p):
        if _cross(ctx, "macd_line", "macd_signal", t) != "up":
            return None
        if p["trend_filter"]:
            s = ctx.val("sma200", t)
            if s is None or ctx.c[t] <= s:
                return None
        return Signal(note="MACD crossed above signal")

    def exit(self, ctx, t, p, held):
        return _cross(ctx, "macd_line", "macd_signal", t) == "down"


class FibPullback(Strategy):
    id, name = "fib_pullback", "Fibonacci pullback"
    description = ("In a confirmed up swing, buy when a bar dips to within the tolerance (in ATR) of the chosen "
                   "retracement and closes above it as an up bar. Stop at the swing low, target the swing high.")
    params = {"level": {"choices": [0.5, 0.618], "default": 0.618, "label": "Retracement"},
              "tolerance_atr": {"choices": [0.25, 0.5, 1.0], "default": 0.5, "label": "Tolerance (ATR)"}}

    def entry(self, ctx, t, p):
        f = ctx.fib(t)
        atr = ctx.val("atr14", t)
        if f.get("status") != "ok" or f["direction"] != "up" or f["beyond_swing"] or not atr:
            return None
        lv = {round(x["ratio"], 3): x["price"] for x in f["levels"]}
        level, stop, target = lv[round(p["level"], 3)], lv[1.0], lv[0.0]
        o, lo, c = ctx.o[t], ctx.l[t], ctx.c[t]
        if lo <= level + p["tolerance_atr"] * atr and c > level and c > o and target > c:
            return Signal(stop=stop, target=target, note=f"bounce off {p['level']:g} at {level:.2f}")
        return None


class SetupHold(Strategy):
    id, name = "setup_hold", "Scanner setup, fixed hold"
    description = "Buy when the chosen Phase 4 bullish setup newly triggers; sell after a fixed number of bars."
    params = {"setup": {"choices": [s for s, (_, d, _) in setups.SETUPS.items() if d == "bullish"],
                        "default": "bullish_ma", "label": "Setup"},
              "hold": {"choices": [5, 10, 20], "default": 10, "label": "Hold (bars)"}}

    def entry(self, ctx, t, p):
        if p["setup"] in ctx.triggered(t) and p["setup"] not in ctx.triggered(t - 1):
            return Signal(note=f"new setup: {setups.SETUPS[p['setup']][0]}")
        return None

    def exit(self, ctx, t, p, held):
        return held >= p["hold"]


STRATEGIES: dict[str, Strategy] = {s.id: s for s in (MaCross(), RsiReversion(), MacdCross(), FibPullback(), SetupHold())}


def validate_params(strategy: Strategy, p: dict | None) -> dict:
    out = strategy.defaults()
    for k, v in (p or {}).items():
        if k not in strategy.params:
            raise ValueError(f"unknown parameter '{k}' for {strategy.id}")
        if v not in strategy.params[k]["choices"]:
            raise ValueError(f"{k} must be one of {strategy.params[k]['choices']}")
        out[k] = v
    if not strategy.valid(out):
        raise ValueError(f"invalid parameter combination {out}")
    return out


# ---------------------------------------------------------------- simulation

@dataclass
class Result:
    start: int
    end: int
    curve: list[float]                     # equity at each close in [start, end)
    invested: list[bool]                   # in a position at that close
    trades: list[dict] = field(default_factory=list)


def simulate(ctx: Context, strat: Strategy, p: dict, costs: Costs, start: int, end: int,
             start_equity: float = 1.0) -> Result:
    if not (0 < start < end <= ctx.n):
        raise ValueError("invalid window")
    eq, pos, pending = start_equity, None, None
    res = Result(start, end, [], [])
    d = ctx.dates

    def close_pos(t: int, px: float, reason: str):
        nonlocal eq, pos
        fill = px * (1 - costs.slip)
        proceeds = pos["units"] * fill
        eq = proceeds * (1 - costs.comm)
        res.trades.append({"entry_date": d[pos["i"]].isoformat(), "entry_price": pos["price"],
                           "exit_date": d[t].isoformat(), "exit_price": fill, "bars_held": t - pos["i"] + 1,
                           "return_pct": (eq / pos["eq_before"] - 1) * 100, "exit_reason": reason,
                           "entry_note": pos["note"]})
        pos = None

    for t in range(start, end):
        o, h, lo, c = ctx.o[t], ctx.h[t], ctx.l[t], ctx.c[t]
        if pending is not None:
            kind, sig = pending
            pending = None
            if kind == "enter":
                fill = o * (1 + costs.slip)
                units = eq * (1 - costs.comm) / fill
                pos = {"i": t, "price": fill, "units": units, "eq_before": eq,
                       "stop": sig.stop, "target": sig.target, "note": sig.note}
            else:
                close_pos(t, o, "signal")
        if pos is not None:
            if pos["stop"] is not None and lo <= pos["stop"]:
                close_pos(t, min(o, pos["stop"]), "stop")           # stop first if both are touched
            elif pos["target"] is not None and h >= pos["target"]:
                close_pos(t, max(o, pos["target"]), "target")
        res.curve.append(pos["units"] * c if pos else eq)
        res.invested.append(pos is not None)
        if t < end - 1:  # a decision at close t needs bar t+1 inside the window to execute
            if pos is None:
                sig = strat.entry(ctx, t, p)
                if sig is not None:
                    pending = ("enter", sig)
            elif strat.exit(ctx, t, p, t - pos["i"] + 1):
                pending = ("exit", None)
    if pos is not None:
        close_pos(end - 1, ctx.c[end - 1], "end of period")
        res.trades[-1]["open_at_end"] = True
        res.curve[-1] = eq
    return res


def buy_and_hold(ctx: Context, costs: Costs, start: int, end: int) -> Result:
    eq0 = 1.0
    fill = ctx.o[start] * (1 + costs.slip)
    units = eq0 * (1 - costs.comm) / fill
    curve = [units * ctx.c[t] for t in range(start, end)]
    out = units * ctx.c[end - 1] * (1 - costs.slip) * (1 - costs.comm)
    curve[-1] = out
    trade = {"entry_date": ctx.dates[start].isoformat(), "entry_price": fill, "exit_date": ctx.dates[end - 1].isoformat(),
             "exit_price": ctx.c[end - 1] * (1 - costs.slip), "bars_held": end - start,
             "return_pct": (out - 1) * 100, "exit_reason": "end of period", "entry_note": "buy and hold"}
    return Result(start, end, curve, [True] * (end - start), [trade])


# ---------------------------------------------------------------- metrics

def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else float(x)


def metrics(curve: list[float], invested: list[bool], trades: list[dict], start_equity: float = 1.0) -> dict:
    v = np.asarray([start_equity] + list(curve), dtype="float64")
    n = len(curve)
    rets = v[1:] / v[:-1] - 1
    peak = np.maximum.accumulate(v)
    mdd = float(((peak - v) / peak).max()) if n else 0.0
    total = v[-1] / start_equity - 1
    years = n / BARS_PER_YEAR
    cagr = (v[-1] / start_equity) ** (1 / years) - 1 if years > 0 and v[-1] > 0 else None
    sd = float(rets.std(ddof=1)) if n > 1 else 0.0
    sharpe = float(rets.mean()) / sd * math.sqrt(BARS_PER_YEAR) if sd > 0 else None
    tr = [t["return_pct"] for t in trades]
    wins = [x for x in tr if x > 0]
    return {"bars": n, "trades": len(trades), "win_rate_pct": _f(len(wins) / len(tr) * 100) if tr else None,
            "avg_trade_pct": _f(float(np.mean(tr))) if tr else None,
            "best_trade_pct": _f(max(tr)) if tr else None, "worst_trade_pct": _f(min(tr)) if tr else None,
            "avg_bars_held": _f(float(np.mean([t["bars_held"] for t in trades]))) if trades else None,
            "total_return_pct": _f(total * 100), "cagr_pct": _f(cagr * 100) if cagr is not None else None,
            "max_drawdown_pct": _f(mdd * 100), "sharpe_like": _f(sharpe),
            "exposure_pct": _f(sum(invested) / n * 100) if n else None}


def by_year(ctx: Context, res: Result, bh: Result) -> list[dict]:
    out, prev_s, prev_b = [], 1.0, 1.0
    years: dict[int, int] = {}
    for i, t in enumerate(range(res.start, res.end)):
        years[ctx.dates[t].year] = i
    for y, last_i in sorted(years.items()):
        s, b = res.curve[last_i], bh.curve[last_i]
        out.append({"year": y, "strategy_pct": (s / prev_s - 1) * 100, "buy_hold_pct": (b / prev_b - 1) * 100,
                    "trades_closed": sum(1 for t in res.trades if t["exit_date"].startswith(str(y)))})
        prev_s, prev_b = s, b
    return out


def _segment(ctx: Context, label: str, res: Result, bh: Result, params: dict) -> dict:
    sm, bm = metrics(res.curve, res.invested, res.trades), metrics(bh.curve, bh.invested, bh.trades)
    return {"label": label, "start_date": ctx.dates[res.start].isoformat(), "end_date": ctx.dates[res.end - 1].isoformat(),
            "params": params, "metrics": sm, "buy_hold": bm, "by_year": by_year(ctx, res, bh),
            "trades": res.trades, "few_trades": sm["trades"] < 10,
            "curve": {"dates": [ctx.dates[t].isoformat() for t in range(res.start, res.end)],
                      "strategy": [round(x, 6) for x in res.curve], "buy_hold": [round(x, 6) for x in bh.curve]}}


# ---------------------------------------------------------------- validation

def split(n: int, holdout_pct: float) -> tuple[int, int]:
    """(first tradable bar, first holdout bar)."""
    if n < WARMUP + 100:
        raise ValueError(f"needs at least {WARMUP + 100} daily bars ({WARMUP} warm-up + 100 to trade); this instrument has {n}")
    return WARMUP, WARMUP + int(round((n - WARMUP) * (1 - holdout_pct)))


def _score(m: dict) -> float:
    if m["trades"] < MIN_TRADES_FOR_SELECTION or m["sharpe_like"] is None:
        return -math.inf
    return m["sharpe_like"]


def select(ctx: Context, strat: Strategy, costs: Costs, a: int, b: int) -> tuple[dict, dict, list[dict]]:
    """Best grid combination on bars [a, b). Returns (params, its metrics, all scores)."""
    best, best_s, best_m, scores = None, -math.inf, None, []
    for p in strat.grid():
        r = simulate(ctx, strat, p, costs, a, b)
        m = metrics(r.curve, r.invested, r.trades)
        s = _score(m)
        scores.append({"params": p, "sharpe_like": m["sharpe_like"], "trades": m["trades"],
                       "total_return_pct": m["total_return_pct"]})
        if s > best_s:
            best, best_s, best_m = p, s, m
    if best is None:  # no combination had enough trades: fall back to the first, and say so
        best = strat.grid()[0]
        r = simulate(ctx, strat, best, costs, a, b)
        best_m = {**metrics(r.curve, r.invested, r.trades), "fallback": True}
    return best, best_m, scores


def run(ctx: Context, strategy_id: str, mode: str, params: dict | None, costs: Costs,
        holdout_pct: float = 0.2, folds: int = 3) -> dict:
    if strategy_id not in STRATEGIES:
        raise ValueError(f"unknown strategy '{strategy_id}'")
    strat = STRATEGIES[strategy_id]
    if mode not in ("single", "walk_forward"):
        raise ValueError("mode must be 'single' or 'walk_forward'")
    if not 0.1 <= holdout_pct <= 0.4:
        raise ValueError("holdout must be between 10% and 40%")
    start, hold = split(ctx.n, holdout_pct)
    out = {"version": BACKTEST_VERSION, "strategy": strategy_id, "strategy_name": strat.name,
           "description": strat.description, "mode": mode, "costs": {"commission_bps": costs.commission_bps,
                                                                      "slippage_bps": costs.slippage_bps},
           "holdout_pct": holdout_pct, "warmup_bars": WARMUP, "disclaimer": DISCLAIMER,
           "periods": {"tradable_from": ctx.dates[start].isoformat(), "holdout_from": ctx.dates[hold].isoformat(),
                       "until": ctx.dates[-1].isoformat()}}
    if mode == "single":
        p = validate_params(strat, params)
        ins = simulate(ctx, strat, p, costs, start, hold)
        out.update(final_params=p, combinations_tested=1,
                   main=_segment(ctx, "In-sample", ins, buy_and_hold(ctx, costs, start, hold), p))
    else:
        if params:
            raise ValueError("walk-forward chooses parameters itself; don't pass params")
        if not 2 <= folds <= 6:
            raise ValueError("folds must be between 2 and 6")
        if (hold - start) // (folds + 1) < MIN_BLOCK_BARS:
            raise ValueError(f"not enough history for {folds} folds (each block needs {MIN_BLOCK_BARS}+ bars); "
                             "use fewer folds or a smaller holdout")
        edges = [start + (hold - start) * i // (folds + 1) for i in range(folds + 2)]
        fold_rows, curve, invested, trades, eq = [], [], [], [], 1.0
        for i in range(1, folds + 1):
            p, train_m, _ = select(ctx, strat, costs, edges[0], edges[i])
            test = simulate(ctx, strat, p, costs, edges[i], edges[i + 1], start_equity=eq)
            test_m = metrics(test.curve, test.invested, test.trades, start_equity=eq)
            fold_rows.append({"fold": i, "train": [ctx.dates[edges[0]].isoformat(), ctx.dates[edges[i] - 1].isoformat()],
                              "test": [ctx.dates[edges[i]].isoformat(), ctx.dates[edges[i + 1] - 1].isoformat()],
                              "params": p, "train_metrics": train_m, "test_metrics": test_m,
                              "selection_fallback": bool(train_m.get("fallback"))})
            curve += test.curve
            invested += test.invested
            trades += test.trades
            eq = test.curve[-1]
        oos = Result(edges[1], hold, curve, invested, trades)
        final_p, final_m, scores = select(ctx, strat, costs, start, hold)
        out.update(final_params=final_p, final_selection={"metrics": final_m, "grid_scores": scores},
                   folds=fold_rows, combinations_tested=len(strat.grid()) * (folds + 1),
                   main=_segment(ctx, "Out-of-sample (walk-forward)", oos, buy_and_hold(ctx, costs, edges[1], hold), None))
        p = final_p
    hres = simulate(ctx, strat, p, costs, hold, ctx.n)
    out["holdout"] = _segment(ctx, "Holdout (untouched until now)", hres, buy_and_hold(ctx, costs, hold, ctx.n), p)
    out["request_hash"] = stable_hash({"strategy": strategy_id, "mode": mode, "params": params or {},
                                       "costs": out["costs"], "holdout_pct": holdout_pct,
                                       "folds": folds if mode == "walk_forward" else None,
                                       "version": BACKTEST_VERSION})
    return out
