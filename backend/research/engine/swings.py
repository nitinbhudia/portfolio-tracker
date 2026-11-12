"""ATR ZigZag swing detection (PHASE_1_TASK.md §6.1).

Walks forward bar by bar. A swing high is *confirmed* on the first bar whose
low <= running_high - k * ATR14 (ATR taken at the confirming bar); swing lows
mirror this. Each swing records the bar where the extreme occurred and the bar
where it was confirmed. Consumers must only use swings whose
``confirmed_index <= as_of_index`` — this is what prevents look-ahead bias.

Ties on equal extremes resolve to the earliest bar (strict comparisons).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

CALC_VERSION = "swings-zigzag-atr-v1"

SENSITIVITY_PRESETS = {"high": 1.5, "medium": 2.5, "low": 4.0}
K_MIN, K_MAX = 0.5, 10.0


@dataclass(frozen=True)
class Swing:
    kind: str  # "high" | "low"
    index: int
    confirmed_index: int
    price: float

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_k(sensitivity: str | float) -> float:
    if isinstance(sensitivity, str):
        if sensitivity in SENSITIVITY_PRESETS:
            return SENSITIVITY_PRESETS[sensitivity]
        try:
            sensitivity = float(sensitivity)
        except ValueError as e:
            raise ValueError(f"unknown sensitivity '{sensitivity}'") from e
    k = float(sensitivity)
    if not (K_MIN <= k <= K_MAX):
        raise ValueError(f"atr multiple must be between {K_MIN} and {K_MAX}")
    return k


def _argmax_earliest(a: np.ndarray, lo: int, hi: int) -> int:
    return lo + int(np.argmax(a[lo : hi + 1]))  # argmax returns first occurrence


def _argmin_earliest(a: np.ndarray, lo: int, hi: int) -> int:
    return lo + int(np.argmin(a[lo : hi + 1]))


def detect_swings(high, low, atr, k: float) -> list[Swing]:
    h = np.asarray(high, dtype="float64")
    lo_ = np.asarray(low, dtype="float64")
    a = np.asarray(atr, dtype="float64")
    n = len(h)
    valid = np.flatnonzero(~np.isnan(a))
    if len(valid) == 0:
        return []
    start = int(valid[0])
    swings: list[Swing] = []

    direction = 0  # 0 undetermined, +1 tracking a high (up leg), -1 tracking a low
    hi_i = lo_i = start

    for i in range(start + 1, n):
        thr = k * a[i]
        if direction == 0:
            if h[i] > h[hi_i]:
                hi_i = i
            if lo_[i] < lo_[lo_i]:
                lo_i = i
            high_conf = lo_[i] <= h[hi_i] - thr and hi_i < i
            low_conf = h[i] >= lo_[lo_i] + thr and lo_i < i
            if high_conf and (not low_conf or hi_i <= lo_i):
                swings.append(Swing("high", hi_i, i, float(h[hi_i])))
                direction = -1
                lo_i = _argmin_earliest(lo_, hi_i + 1, i)
            elif low_conf:
                swings.append(Swing("low", lo_i, i, float(lo_[lo_i])))
                direction = +1
                hi_i = _argmax_earliest(h, lo_i + 1, i)
        elif direction == +1:
            if h[i] > h[hi_i]:
                hi_i = i
            if lo_[i] <= h[hi_i] - thr and hi_i < i:
                swings.append(Swing("high", hi_i, i, float(h[hi_i])))
                direction = -1
                lo_i = _argmin_earliest(lo_, hi_i + 1, i)
        else:
            if lo_[i] < lo_[lo_i]:
                lo_i = i
            if h[i] >= lo_[lo_i] + thr and lo_i < i:
                swings.append(Swing("low", lo_i, i, float(lo_[lo_i])))
                direction = +1
                hi_i = _argmax_earliest(h, lo_i + 1, i)
    return swings


def confirmed_as_of(swings: list[Swing], as_of_index: int) -> list[Swing]:
    return [s for s in swings if s.confirmed_index <= as_of_index]
