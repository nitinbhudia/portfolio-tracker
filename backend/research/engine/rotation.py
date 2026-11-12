"""Sector ranking metrics, rotation detection and the Rotation Signal Score (SECTOR_ROTATION_TASK.md §3).

Pure functions over aligned daily arrays. Nothing here is a buy or sell signal: the score summarises
transparent components so the user can see *why* a sector ranks where it does.
"""
from __future__ import annotations

import math

import numpy as np

from .rrg import RrgSeries, quadrant

ROTATION_VERSION = "rotation-v1"
TRANSITION_LOOKBACK = 20   # sessions scanned for quadrant transitions
SCORE_TRANSITION_WINDOW = 10
ACCEL_LAG = 5

DEFAULT_WEIGHTS = {"relative_strength": 25.0, "relative_momentum": 25.0, "acceleration": 15.0,
                   "ma_alignment": 15.0, "volume": 10.0, "transition": 10.0}
WEIGHT_LABELS = {"relative_strength": "Relative strength (RS-Ratio)", "relative_momentum": "Relative momentum (RS-Momentum)",
                 "acceleration": "Momentum acceleration (5-day change)", "ma_alignment": "Moving-average alignment",
                 "volume": "Volume confirmation", "transition": "Recent quadrant transition"}
TRANSITION_POINTS = {("improving", "leading"): 90.0, ("lagging", "improving"): 80.0,
                     ("leading", "weakening"): 20.0, ("weakening", "lagging"): 10.0}

# (from, to) -> (category, label)
TRANSITIONS = {
    ("lagging", "improving"): ("early_opportunity", "Lagging → Improving"),
    ("improving", "leading"): ("established", "Improving → Leading"),
    ("leading", "weakening"): ("exit_warning", "Leading → Weakening"),
    ("weakening", "lagging"): ("deterioration", "Weakening → Lagging"),
    # counter-clockwise or diagonal moves happen too; reported, but with a neutral category
    ("improving", "lagging"): ("deterioration", "Improving → Lagging (turnaround failed)"),
    ("weakening", "leading"): ("established", "Weakening → Leading (re-acceleration)"),
    ("lagging", "leading"): ("established", "Lagging → Leading"),
    ("leading", "lagging"): ("deterioration", "Leading → Lagging"),
    ("improving", "weakening"): ("neutral", "Improving → Weakening"),
    ("weakening", "improving"): ("neutral", "Weakening → Improving"),
    ("leading", "improving"): ("neutral", "Leading → Improving"),
    ("lagging", "weakening"): ("neutral", "Lagging → Weakening"),
}
CATEGORY_LABELS = {"early_opportunity": "Early opportunity", "established": "Established strength",
                   "exit_warning": "Potential exit warning", "deterioration": "Deterioration", "neutral": "Other rotation"}


def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else float(x)


def _v(arr, t: int) -> float | None:
    return _f(float(arr[t])) if 0 <= t < len(arr) else None


def _pct(close: np.ndarray, t: int, n: int) -> float | None:
    a, b = _v(close, t), _v(close, t - n)
    return (a / b - 1) * 100 if a is not None and b else None


def validate_weights(w: dict | None) -> dict:
    out = dict(DEFAULT_WEIGHTS)
    for k, v in (w or {}).items():
        if k not in DEFAULT_WEIGHTS:
            raise ValueError(f"unknown score component '{k}'")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
            raise ValueError(f"weight for {k} must be between 0 and 100")
        out[k] = float(v)
    if sum(out.values()) <= 0:
        raise ValueError("at least one weight must be above 0")
    return out


def metrics(close: np.ndarray, volume: np.ndarray, ind: dict, bench_close: np.ndarray, t: int) -> dict:
    """Absolute and relative measures at bar t (the three are kept apart on purpose)."""
    c = _v(close, t)
    sma = {n: _v(ind[f"sma{n}"], t) for n in (10, 20, 50, 200)}
    vol = np.asarray(volume, dtype="float64")
    v20 = vol[max(0, t - 19) : t + 1]
    v50 = vol[max(0, t - 49) : t + 1]
    vt = None
    if len(v50) == 50 and not np.isnan(v50).any() and v50.mean() > 0:
        vt = float(v20.mean() / v50.mean())
    rel20 = None
    s20, b20 = _pct(close, t, 20), _pct(bench_close, t, 20)
    if s20 is not None and b20 is not None:
        rel20 = s20 - b20
    above = {f"above_sma{n}": (c > sma[n]) if c is not None and sma[n] is not None else None for n in (10, 20, 50, 200)}
    if c is None or sma[50] is None or sma[200] is None:
        trend = None
    elif c > sma[50] > sma[200]:
        trend = "up"
    elif c < sma[50] < sma[200]:
        trend = "down"
    else:
        trend = "mixed"
    return {"close": c, "change_10d_pct": _pct(close, t, 10), "change_20d_pct": s20, "change_50d_pct": _pct(close, t, 50),
            "benchmark_change_20d_pct": b20, "relative_20d_pct": rel20, "rsi14": _v(ind["rsi14"], t),
            **{f"sma{n}": sma[n] for n in (10, 20, 50, 200)}, **above,
            "volume_trend": vt,
            "volume_trend_label": None if vt is None else "rising" if vt > 1.1 else "falling" if vt < 0.9 else "flat",
            "absolute_trend": trend}


def transitions(series: RrgSeries, dates: list, close: np.ndarray, sma50: np.ndarray, t: int,
                lookback: int = TRANSITION_LOOKBACK) -> list[dict]:
    """Quadrant changes, momentum crossings of 100 and close-below-SMA50 crossings in the last `lookback` sessions."""
    out = []
    for i in range(max(1, t - lookback + 1), t + 1):
        r0, m0, r1, m1 = (_v(series.ratio, i - 1), _v(series.momentum, i - 1), _v(series.ratio, i), _v(series.momentum, i))
        if None in (r0, m0, r1, m1):
            continue
        q0, q1 = quadrant(r0, m0), quadrant(r1, m1)
        base = {"date": dates[i].isoformat(), "sessions_ago": t - i, "ratio": r1, "momentum": m1}
        if q0 != q1:
            cat, label = TRANSITIONS[(q0, q1)]
            out.append({**base, "kind": "quadrant", "from": q0, "to": q1, "category": cat, "label": label})
        elif m0 < 100 <= m1 and r1 < 100:
            out.append({**base, "kind": "momentum_cross", "category": "early_opportunity",
                        "label": "RS-Momentum crossed above 100 (RS-Ratio still below 100)"})
        elif m0 >= 100 > m1 and r1 >= 100:
            out.append({**base, "kind": "momentum_cross", "category": "exit_warning",
                        "label": "RS-Momentum fell below 100 (RS-Ratio still above 100)"})
        c0, c1, s0, s1 = _v(close, i - 1), _v(close, i), _v(sma50, i - 1), _v(sma50, i)
        if None not in (c0, c1, s0, s1) and c0 >= s0 and c1 < s1:
            out.append({**base, "kind": "ma_cross", "category": "deterioration", "label": "Close crossed below SMA 50"})
    return out


def _clip(x: float) -> float:
    return max(0.0, min(100.0, x))


def score(series: RrgSeries, m: dict, events: list[dict], t: int, weights: dict | None = None) -> dict:
    w = validate_weights(weights)
    r, mo, mo_then = _v(series.ratio, t), _v(series.momentum, t), _v(series.momentum, t - ACCEL_LAG)
    comps: dict[str, dict] = {}
    if r is not None:
        comps["relative_strength"] = {"points": _clip(50 + 10 * (r - 100)), "input": r, "rule": "50 + 10 × (RS-Ratio − 100)"}
    if mo is not None:
        comps["relative_momentum"] = {"points": _clip(50 + 10 * (mo - 100)), "input": mo, "rule": "50 + 10 × (RS-Momentum − 100)"}
    if mo is not None and mo_then is not None:
        comps["acceleration"] = {"points": _clip(50 + 10 * (mo - mo_then)), "input": mo - mo_then,
                                 "rule": f"50 + 10 × RS-Momentum change over {ACCEL_LAG} sessions"}
    checks = [(m["close"], m["sma20"]), (m["sma20"], m["sma50"]), (m["sma50"], m["sma200"]), (m["close"], m["sma200"])]
    if all(a is not None and b is not None for a, b in checks):
        met = [a > b for a, b in checks]
        comps["ma_alignment"] = {"points": 25.0 * sum(met), "input": sum(met),
                                 "rule": "25 each: close > SMA20, SMA20 > SMA50, SMA50 > SMA200, close > SMA200",
                                 "checks": met}
    if m["volume_trend"] is not None:
        comps["volume"] = {"points": _clip(50 + 200 * (m["volume_trend"] - 1)), "input": m["volume_trend"],
                           "rule": "50 + 200 × (20-day ÷ 50-day average volume − 1)"}
    recent = [e for e in events if e["kind"] == "quadrant" and e["sessions_ago"] < SCORE_TRANSITION_WINDOW]
    last = recent[-1] if recent else None
    pts = TRANSITION_POINTS.get((last["from"], last["to"]), 50.0) if last else 50.0
    comps["transition"] = {"points": pts, "input": last["label"] if last else "none",
                           "rule": f"latest quadrant change in {SCORE_TRANSITION_WINDOW} sessions: Improving→Leading 90, "
                                   "Lagging→Improving 80, none 50, Leading→Weakening 20, Weakening→Lagging 10"}
    used = {k: w[k] for k in comps if w[k] > 0}
    total_w = sum(used.values())
    if total_w <= 0 or "relative_strength" not in comps:
        return {"total": None, "components": comps, "weights": w, "status": "insufficient_data"}
    total = sum(comps[k]["points"] * used[k] / total_w for k in used)
    for k, c in comps.items():
        c["weight"] = w[k]
        c["effective_weight"] = used.get(k, 0.0) / total_w
        c["contribution"] = c["points"] * c["effective_weight"]
    return {"total": round(total, 1), "components": comps, "weights": w, "status": "ok",
            "excluded": [k for k in DEFAULT_WEIGHTS if k not in comps]}
