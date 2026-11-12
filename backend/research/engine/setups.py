"""Setup detectors for the opportunity scanner (PHASE_4_TASK.md §2).

Each detector is a deterministic, documented rule set evaluated at bar ``t`` using
only values at or before ``t`` (no look-ahead). A detector returns every rule with
its inputs and outcome, so the UI can show exactly why it did or didn't trigger.

A triggered setup is a condition worth researching, never a buy or sell signal.
"""
from __future__ import annotations

import math

import numpy as np

from research.core.hashing import stable_hash

SETUPS_VERSION = "setups-v1"

PARAMS = {
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "reversal_lookback": 5,
    "macd_hist_compare": 3,
    "fib_ratios": [0.236, 0.382, 0.5, 0.618, 0.786],
    "fib_max_atr": 1.0,
    "fib_trend_lookback": 5,
    "breakout_lookback": 20,
    "breakout_min_relvol": 1.5,
    "ma_slope_lookback": 5,
    "momentum_bars": 3,
    "accum_window": 20,
    "accum_ratio": 1.5,
    "accum_max_change_pct": 5.0,
}
PARAMS_HASH = stable_hash({"version": SETUPS_VERSION, **PARAMS})

# id -> (name, direction, needs_volume)
SETUPS: dict[str, tuple[str, str, bool]] = {
    "bullish_reversal": ("Potential bullish reversal", "bullish", False),
    "bearish_reversal": ("Potential bearish reversal", "bearish", False),
    "fib_support": ("Approaching Fibonacci support", "bullish", False),
    "fib_resistance": ("Approaching Fibonacci resistance", "bearish", False),
    "breakout": ("Potential breakout", "bullish", True),
    "breakdown": ("Potential breakdown", "bearish", True),
    "bullish_ma": ("Bullish MA alignment", "bullish", False),
    "bearish_ma": ("Bearish MA alignment", "bearish", False),
    "momentum_up": ("Momentum acceleration (up)", "bullish", False),
    "momentum_down": ("Momentum acceleration (down)", "bearish", False),
    "accumulation": ("Potential accumulation", "bullish", True),
    "distribution": ("Potential distribution", "bearish", True),
}


class _Insufficient(Exception):
    pass


def _v(arr, i: int) -> float:
    """Value at index i, or raise _Insufficient for out-of-range / NaN."""
    if i < 0 or i >= len(arr):
        raise _Insufficient
    x = float(arr[i])
    if math.isnan(x):
        raise _Insufficient
    return x


def _window(arr, lo: int, hi: int) -> np.ndarray:
    """arr[lo..hi] inclusive, or raise _Insufficient if out of range or any NaN."""
    if lo < 0 or hi >= len(arr) or lo > hi:
        raise _Insufficient
    w = np.asarray(arr[lo : hi + 1], dtype="float64")
    if np.isnan(w).any():
        raise _Insufficient
    return w


def _rule(rule: str, left, right, result: bool) -> dict:
    return {"rule": rule, "left": None if left is None else float(left),
            "right": None if right is None else float(right), "result": bool(result)}


# ---------------------------------------------------------------- detectors
# Each takes a context dict and returns a list of rules. All rules must be true.

def _reversal(x: dict, bullish: bool) -> list[dict]:
    t, P, rsi, hist = x["t"], PARAMS, x["ind"]["rsi14"], x["ind"]["macd_hist"]
    n, k = P["reversal_lookback"], P["macd_hist_compare"]
    prior = _window(rsi, t - n, t - 1)
    now, h_now, h_then = _v(rsi, t), _v(hist, t), _v(hist, t - k)
    if bullish:
        lim = P["rsi_oversold"]
        return [_rule(f"min RSI14 over previous {n} bars < {lim:g}", prior.min(), lim, prior.min() < lim),
                _rule(f"RSI14 now >= {lim:g}", now, lim, now >= lim),
                _rule(f"MACD hist now > MACD hist {k} bars ago", h_now, h_then, h_now > h_then)]
    lim = P["rsi_overbought"]
    return [_rule(f"max RSI14 over previous {n} bars > {lim:g}", prior.max(), lim, prior.max() > lim),
            _rule(f"RSI14 now <= {lim:g}", now, lim, now <= lim),
            _rule(f"MACD hist now < MACD hist {k} bars ago", h_now, h_then, h_now < h_then)]


def _fib(x: dict, support: bool) -> list[dict]:
    fib, t, c, P = x["fib"], x["t"], x["c"], PARAMS
    if not fib or fib.get("status") != "ok":
        raise _Insufficient
    close = _v(c, t)
    n = P["fib_trend_lookback"]
    then = _v(c, t - n)
    levels = [lv for lv in fib["levels"] if lv["kind"] == "retracement"
              and any(abs(lv["ratio"] - r) < 1e-9 for r in P["fib_ratios"])]
    if not levels or levels[0].get("distance_atr") is None:
        raise _Insufficient
    lv = min(levels, key=lambda z: (abs(close - z["price"]), z["ratio"]))
    want_dir = "up" if support else "down"
    dist = lv["distance_atr"]
    rules = [{"rule": f"swing direction is {want_dir}", "left": None, "right": None,
              "result": fib["direction"] == want_dir, "value": fib["direction"]}]
    if support:
        rules += [_rule(f"nearest retracement ({lv['ratio']:g}) is below price", close, lv["price"], close >= lv["price"]),
                  _rule(f"distance to it <= {P['fib_max_atr']:g} ATR", dist, P["fib_max_atr"], dist <= P["fib_max_atr"]),
                  _rule(f"close below close {n} bars ago (moving toward level)", close, then, close < then)]
    else:
        rules += [_rule(f"nearest retracement ({lv['ratio']:g}) is above price", close, lv["price"], close <= lv["price"]),
                  _rule(f"distance to it <= {P['fib_max_atr']:g} ATR", dist, P["fib_max_atr"], dist <= P["fib_max_atr"]),
                  _rule(f"close above close {n} bars ago (moving toward level)", close, then, close > then)]
    return rules


def _breakout(x: dict, up: bool) -> list[dict]:
    t, P = x["t"], PARAMS
    n = P["breakout_lookback"]
    close, rv = _v(x["c"], t), _v(x["ind"]["relvol20"], t)
    lim = P["breakout_min_relvol"]
    if up:
        hi = _window(x["h"], t - n, t - 1).max()
        r = _rule(f"close > highest high of previous {n} bars", close, hi, close > hi)
    else:
        lo = _window(x["l"], t - n, t - 1).min()
        r = _rule(f"close < lowest low of previous {n} bars", close, lo, close < lo)
    return [r, _rule(f"relative volume >= {lim:g}", rv, lim, rv >= lim)]


def _ma(x: dict, bullish: bool) -> list[dict]:
    t, ind, k = x["t"], x["ind"], PARAMS["ma_slope_lookback"]
    close = _v(x["c"], t)
    s20, s50, s200 = _v(ind["sma20"], t), _v(ind["sma50"], t), _v(ind["sma200"], t)
    s50_then = _v(ind["sma50"], t - k)
    if bullish:
        return [_rule("close > SMA20", close, s20, close > s20), _rule("SMA20 > SMA50", s20, s50, s20 > s50),
                _rule("SMA50 > SMA200", s50, s200, s50 > s200),
                _rule(f"SMA50 rising (vs {k} bars ago)", s50, s50_then, s50 > s50_then)]
    return [_rule("close < SMA20", close, s20, close < s20), _rule("SMA20 < SMA50", s20, s50, s20 < s50),
            _rule("SMA50 < SMA200", s50, s200, s50 < s200),
            _rule(f"SMA50 falling (vs {k} bars ago)", s50, s50_then, s50 < s50_then)]


def _momentum(x: dict, up: bool) -> list[dict]:
    t, n = x["t"], PARAMS["momentum_bars"]
    w = _window(x["ind"]["macd_hist"], t - n, t)
    steps = np.diff(w)
    if up:
        return [_rule("MACD hist > 0", w[-1], 0.0, w[-1] > 0),
                _rule(f"MACD hist rose on each of the last {n} bars", steps.min(), 0.0, bool((steps > 0).all()))]
    return [_rule("MACD hist < 0", w[-1], 0.0, w[-1] < 0),
            _rule(f"MACD hist fell on each of the last {n} bars", steps.max(), 0.0, bool((steps < 0).all()))]


def _accum(x: dict, accumulation: bool) -> list[dict]:
    t, P = x["t"], PARAMS
    n = P["accum_window"]
    c = _window(x["c"], t - n, t)  # n+1 closes -> n day-over-day changes
    vol = _window(x["v"], t - n + 1, t)
    chg = np.diff(c)
    up_v, down_v = float(vol[chg > 0].sum()), float(vol[chg < 0].sum())
    change_pct = (c[-1] / c[0] - 1) * 100
    lim, max_chg = P["accum_ratio"], P["accum_max_change_pct"]
    if accumulation:
        ratio = up_v / down_v if down_v > 0 else math.inf
        r = _rule(f"up-day volume / down-day volume over {n} bars >= {lim:g}", ratio, lim, ratio >= lim)
    else:
        ratio = down_v / up_v if up_v > 0 else math.inf
        r = _rule(f"down-day volume / up-day volume over {n} bars >= {lim:g}", ratio, lim, ratio >= lim)
    if math.isinf(ratio):
        r["left"] = None
        r["note"] = "no opposite-direction volume in window"
    return [r, _rule(f"|{n}-bar price change| <= {max_chg:g}% (sideways)", abs(change_pct), max_chg,
                     abs(change_pct) <= max_chg)]


DETECTORS = {
    "bullish_reversal": lambda x: _reversal(x, True),
    "bearish_reversal": lambda x: _reversal(x, False),
    "fib_support": lambda x: _fib(x, True),
    "fib_resistance": lambda x: _fib(x, False),
    "breakout": lambda x: _breakout(x, True),
    "breakdown": lambda x: _breakout(x, False),
    "bullish_ma": lambda x: _ma(x, True),
    "bearish_ma": lambda x: _ma(x, False),
    "momentum_up": lambda x: _momentum(x, True),
    "momentum_down": lambda x: _momentum(x, False),
    "accumulation": lambda x: _accum(x, True),
    "distribution": lambda x: _accum(x, False),
}


def detect_all(o, h, l, c, v, ind: dict, fib: dict | None, t: int | None = None,
               has_volume: bool = True) -> dict:
    """Evaluate every setup at bar ``t`` (default: the last bar).

    ``ind`` holds full indicator arrays (from ``indicators.compute_all``); ``fib`` is the
    Fibonacci result for bar ``t`` built from swings confirmed on or before ``t``.
    """
    n = len(c)
    t = n - 1 if t is None else t
    ctx = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "ind": ind, "fib": fib}
    out = []
    for sid, (name, direction, needs_volume) in SETUPS.items():
        item = {"id": sid, "name": name, "direction": direction}
        if needs_volume and not has_volume:
            out.append({**item, "status": "not_applicable", "rules": [],
                        "reason": "needs volume, which indices don't have"})
            continue
        try:
            rules = DETECTORS[sid](ctx)
        except _Insufficient:
            out.append({**item, "status": "insufficient_data", "rules": [],
                        "reason": "not enough history for every input"})
            continue
        hit = all(r["result"] for r in rules)
        out.append({**item, "status": "triggered" if hit else "not_triggered", "rules": rules})
    return {"version": SETUPS_VERSION, "params_hash": PARAMS_HASH, "params": PARAMS,
            "setups": out, "triggered": [s["id"] for s in out if s["status"] == "triggered"]}
