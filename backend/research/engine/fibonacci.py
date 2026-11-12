"""Fibonacci retracements / extensions from confirmed swings (PHASE_1_TASK.md §6.2)."""
from __future__ import annotations

import math

from .swings import Swing

CALC_VERSION = "fibonacci-v1"

RETRACEMENTS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
EXTENSIONS = (1.272, 1.618, 2.0, 2.618)


def fibonacci_levels(swing_high: float, swing_low: float, direction: str) -> tuple[list[dict], list[dict]]:
    """Return (levels, dropped). direction 'up' = low came first, 'down' = high came first."""
    H, L = float(swing_high), float(swing_low)
    rng = H - L
    if rng <= 0:
        raise ValueError("swing high must be above swing low")
    levels: list[dict] = []
    dropped: list[dict] = []
    for r in RETRACEMENTS:
        price = H - r * rng if direction == "up" else L + r * rng
        levels.append({"ratio": r, "kind": "retracement", "price": price})
    for e in EXTENSIONS:
        price = L + e * rng if direction == "up" else H - e * rng
        if price <= 0:
            dropped.append({"ratio": e, "kind": "extension", "price": price,
                            "reason": "non-positive price"})
            continue
        levels.append({"ratio": e, "kind": "extension", "price": price})
    return levels, dropped


def analyse(swings_confirmed: list[Swing], close: float, atr: float | None) -> dict:
    """Fibonacci analysis using the last two confirmed swings as of the analysis date."""
    if len(swings_confirmed) < 2:
        return {"status": "insufficient_swings", "calc_version": CALC_VERSION,
                "swings_available": len(swings_confirmed)}
    a, b = swings_confirmed[-2], swings_confirmed[-1]
    hi, lo = (a, b) if a.kind == "high" else (b, a)
    direction = "up" if lo.index < hi.index else "down"
    levels, dropped = fibonacci_levels(hi.price, lo.price, direction)
    rng = hi.price - lo.price

    # nearest: min |close - level|, ties -> lower ratio (levels are already ratio-ordered)
    nearest = min(levels, key=lambda lv: (abs(close - lv["price"]), lv["ratio"]))
    dist_abs = close - nearest["price"]
    atr_ok = atr is not None and not math.isnan(atr) and atr > 0
    for lv in levels:
        lv["distance_abs"] = close - lv["price"]
        lv["distance_pct"] = (close - lv["price"]) / close * 100.0
        lv["distance_atr"] = abs(close - lv["price"]) / atr if atr_ok else None
        lv["is_nearest"] = lv is nearest

    depth = (hi.price - close) / rng if direction == "up" else (close - lo.price) / rng
    return {
        "status": "ok",
        "calc_version": CALC_VERSION,
        "direction": direction,
        "swing_high": hi.to_dict(),
        "swing_low": lo.to_dict(),
        "levels": levels,
        "dropped_levels": dropped,
        "nearest": {
            "ratio": nearest["ratio"],
            "kind": nearest["kind"],
            "price": nearest["price"],
            "distance_abs": dist_abs,
            "distance_pct": dist_abs / close * 100.0,
            "distance_atr": abs(dist_abs) / atr if atr_ok else None,
            "price_above_level": close >= nearest["price"],
        },
        "retracement_depth": depth,
        "beyond_swing": depth < 0 or depth > 1,
    }
