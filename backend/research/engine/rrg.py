"""Relative Rotation Graph: an RRG-INSPIRED APPROXIMATION (SECTOR_ROTATION_TASK.md §2).

The JdK RS-Ratio / RS-Momentum formulas are proprietary (RRG Research) and are NOT reproduced here.
This module uses a documented, open approximation with the same intent and the same reading
(100 = benchmark-neutral on both axes):

    RS          = 100 * sector_close / benchmark_close          (common dates only)
    RS_s        = EMA(RS, s)                                     (light smoothing)
    RS-Ratio    = 100 + zscore(RS_s, w)                          (vs. its own last w values)
    RS-Momentum = 100 + zscore(RS-Ratio_t - RS-Ratio_{t-m}, w)

All windows are trailing, so a value at t uses only data up to t.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import indicators

RRG_VERSION = "rrg-approx-v1"
METHOD_NOTE = ("RRG-inspired approximation: RS-Ratio and RS-Momentum are z-scores of relative strength and its "
               "rate of change, centred on 100. They are not the proprietary JdK calculations.")

# id -> (label, window w, momentum lag m, smoothing span s)
TIMEFRAMES: dict[str, tuple[str, int, int, int]] = {
    "10d": ("10 trading days", 10, 5, 2),
    "1m": ("1 month", 21, 10, 3),
    "3m": ("3 months", 63, 21, 5),
    "6m": ("6 months", 126, 42, 8),
    "12m": ("12 months", 252, 63, 10),
}
DEFAULT_TIMEFRAME = "3m"
TRAILS = (5, 10, 20)
QUADRANTS = ("leading", "weakening", "lagging", "improving")


def bars_needed(timeframe: str, trail: int = max(TRAILS)) -> int:
    """Aligned bars needed for a full trail: EMA warm-up + two z-score windows + momentum lag."""
    _, w, m, s = TIMEFRAMES[timeframe]
    return s + 2 * w + m + trail


def rolling_z(x: np.ndarray, w: int) -> np.ndarray:
    """(x_t - mean(x_{t-w+1..t})) / std(same window, ddof=1). NaN until w valid values; NaN if std == 0."""
    out = np.full(len(x), np.nan)
    for t in range(w - 1, len(x)):
        win = x[t - w + 1 : t + 1]
        if np.isnan(win).any():
            continue
        sd = win.std(ddof=1)
        if sd > 0:
            out[t] = (x[t] - win.mean()) / sd
    return out


@dataclass
class RrgSeries:
    rs: np.ndarray          # 100 * sector / benchmark
    ratio: np.ndarray       # RS-Ratio (NaN during warm-up)
    momentum: np.ndarray    # RS-Momentum (NaN during warm-up)


def compute(sector_close, benchmark_close, timeframe: str = DEFAULT_TIMEFRAME) -> RrgSeries:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {list(TIMEFRAMES)}")
    _, w, m, s = TIMEFRAMES[timeframe]
    a = np.asarray(sector_close, dtype="float64")
    b = np.asarray(benchmark_close, dtype="float64")
    if a.shape != b.shape:
        raise ValueError("series must be aligned to the same dates")
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(b > 0, 100.0 * a / b, np.nan)
    smooth = indicators.ema(rs, s) if s > 1 else rs
    ratio = 100.0 + rolling_z(smooth, w)
    change = np.full(len(ratio), np.nan)
    change[m:] = ratio[m:] - ratio[:-m]
    momentum = 100.0 + rolling_z(change, w)
    return RrgSeries(rs, ratio, momentum)


def quadrant(ratio: float | None, momentum: float | None) -> str | None:
    if ratio is None or momentum is None or math.isnan(ratio) or math.isnan(momentum):
        return None
    if ratio >= 100:
        return "leading" if momentum >= 100 else "weakening"
    return "improving" if momentum >= 100 else "lagging"


def _f(x) -> float | None:
    return None if x is None or math.isnan(x) else float(x)


def trail(series: RrgSeries, dates: list, t: int, length: int) -> list[dict]:
    """The last `length` points up to and including bar t (fewer if warm-up isn't over)."""
    pts = []
    for i in range(max(0, t - length + 1), t + 1):
        r, mo = _f(series.ratio[i]), _f(series.momentum[i])
        if r is None or mo is None:
            continue
        pts.append({"date": dates[i].isoformat(), "ratio": r, "momentum": mo, "quadrant": quadrant(r, mo)})
    return pts
