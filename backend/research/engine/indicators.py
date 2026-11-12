"""Technical indicators.

Conventions (see PHASE_1_TASK.md §5) — tests depend on these exactly:

* Inputs are 1-D float arrays ordered by date (oldest first).
* Warm-up values are ``NaN`` (serialised as ``null``) — never 0, never partial.
* EMA is seeded with the SMA of the first ``n`` values (TA-Lib convention).
* RSI and ATR use Wilder smoothing; both match TA-Lib (first value at index 14).
* MACD = EMA12 - EMA26 with each EMA SMA-seeded independently; the signal is an
  SMA-seeded EMA9 of the line (first value at index 33). Note TA-Lib's MACD() seeds
  the fast EMA later, so cross-checks use TA-Lib's EMA() instead.
* Relative volume excludes the current bar from its 20-day average.

No function looks at data after index ``t`` when producing the value at ``t``.
"""
from __future__ import annotations

import numpy as np

CALC_VERSION = "indicators-v1"


def _as_float(a) -> np.ndarray:
    return np.asarray(a, dtype="float64")


def sma(values, n: int) -> np.ndarray:
    x = _as_float(values)
    out = np.full(x.shape, np.nan)
    if n <= 0 or len(x) < n:
        return out
    # Exact per-window mean (no cumulative-sum drift on long series).
    out[n - 1 :] = np.lib.stride_tricks.sliding_window_view(x, n).mean(axis=1)
    return out


def ema(values, n: int) -> np.ndarray:
    """EMA with alpha = 2/(n+1), seeded with SMA(n) at index n-1.

    Leading NaNs in ``values`` are skipped: the seed is taken over the first
    ``n`` finite values (used for MACD's signal line).
    """
    x = _as_float(values)
    out = np.full(x.shape, np.nan)
    finite = np.flatnonzero(~np.isnan(x))
    if len(finite) < n:
        return out
    start = finite[0]
    seed_end = start + n - 1
    if np.isnan(x[start : seed_end + 1]).any():
        raise ValueError("ema: NaN inside series after warm-up")
    alpha = 2.0 / (n + 1)
    out[seed_end] = x[start : seed_end + 1].mean()
    for i in range(seed_end + 1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(close, n: int = 14) -> np.ndarray:
    """Wilder RSI. First value at index ``n``."""
    c = _as_float(close)
    out = np.full(c.shape, np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    avg_g = gains[:n].mean()
    avg_l = losses[:n].mean()

    def _val(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[n] = _val(avg_g, avg_l)
    for i in range(n + 1, len(c)):
        avg_g = (avg_g * (n - 1) + gains[i - 1]) / n
        avg_l = (avg_l * (n - 1) + losses[i - 1]) / n
        out[i] = _val(avg_g, avg_l)
    return out


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (line, signal, hist). line valid from slow-1, signal from slow+signal-2."""
    c = _as_float(close)
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def true_range(high, low, close) -> np.ndarray:
    h, l, c = _as_float(high), _as_float(low), _as_float(close)
    tr = np.empty(h.shape)
    if len(h) == 0:
        return tr
    tr[0] = h[0] - l[0]
    prev = c[:-1]
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - prev), np.abs(l[1:] - prev)])
    return tr


def atr(high, low, close, n: int = 14) -> np.ndarray:
    """Wilder ATR (TA-Lib convention).

    TR needs a previous close, so TR is used from bar 1. ATR[n] = mean(TR[1..n]),
    then Wilder smoothing. First value at index n.
    """
    tr = true_range(high, low, close)
    out = np.full(tr.shape, np.nan)
    if len(tr) <= n:
        return out
    out[n] = tr[1 : n + 1].mean()
    for i in range(n + 1, len(tr)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def relative_volume(volume, n: int = 20) -> np.ndarray:
    """volume_t / mean(volume[t-n .. t-1]). First value at index n. NaN if volume missing."""
    v = _as_float(volume)
    out = np.full(v.shape, np.nan)
    for i in range(n, len(v)):
        window = v[i - n : i]
        if np.isnan(window).any() or np.isnan(v[i]):
            continue
        m = window.mean()
        out[i] = v[i] / m if m > 0 else np.nan
    return out


def rate_of_change(close, n: int = 60) -> np.ndarray:
    c = _as_float(close)
    out = np.full(c.shape, np.nan)
    out[n:] = c[n:] / c[:-n] - 1.0
    return out


SMA_PERIODS = (10, 20, 50, 100, 200)


def compute_all(o, h, l, c, v) -> dict[str, np.ndarray]:
    line, sig, hist = macd(c)
    out = {f"sma{n}": sma(c, n) for n in SMA_PERIODS}
    out.update(
        rsi14=rsi(c, 14),
        macd_line=line,
        macd_signal=sig,
        macd_hist=hist,
        atr14=atr(h, l, c, 14),
        relvol20=relative_volume(v, 20),
        roc60=rate_of_change(c, 60),
    )
    return out


# Lookback (bars, inclusive of current) each indicator needs, for gap flags.
LOOKBACK = {
    **{f"sma{n}": n for n in SMA_PERIODS},
    "rsi14": 15,
    "macd_line": 26,
    "macd_signal": 34,
    "macd_hist": 34,
    "atr14": 15,
    "relvol20": 21,
    "roc60": 61,
}
