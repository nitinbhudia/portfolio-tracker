"""Weekly and monthly bars from daily bars (PHASE_2B_TASK.md §4).

A week is the trading days of one ISO week and a month those of one calendar month,
on the listing's own trading calendar. O = first open, H = max high, L = min low,
C = last close, V = sum of volume (missing if every day's volume is missing). Each bar
is dated by its last trading day. The last bar is "in progress" when its period's final
trading day comes after the last daily bar.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

CALC_VERSION = "resample-v1"
INTERVALS = ("1d", "1w", "1mo")
NO_HOLIDAYS = np.array([], dtype="datetime64[D]")


def _period_key(d: date, interval: str) -> tuple[int, int]:
    if interval == "1w":
        iso = d.isocalendar()
        return iso[0], iso[1]
    return d.year, d.month


def period_end(d: date, interval: str) -> date:
    """Last calendar day of the period containing d."""
    if interval == "1w":
        return d + timedelta(days=6 - d.weekday())
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def last_trading_day(d: date, interval: str, holidays=NO_HOLIDAYS) -> date:
    end = np.datetime64(period_end(d, interval), "D")
    return np.busday_offset(end, 0, roll="backward", holidays=holidays).astype(object)


def resample(df: pd.DataFrame, interval: str, holidays=NO_HOLIDAYS) -> tuple[pd.DataFrame, dict]:
    if interval not in ("1w", "1mo"):
        raise ValueError(f"unsupported interval '{interval}'")
    if df.empty:
        return df.copy(), {"interval": interval, "last_bar_in_progress": False, "periods": 0}
    keys = [_period_key(d, interval) for d in df["date"]]
    g = df.assign(_k=keys).groupby("_k", sort=True)
    vol = g["volume"].sum(min_count=1)
    out = pd.DataFrame({
        "date": g["date"].last(),
        "period_start": g["date"].first(),
        "trading_days": g["date"].count(),
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": vol.astype(float),
    })
    for col in ("source", "is_synthetic", "is_delayed", "delay_minutes", "adjustment"):
        if col in df:
            out[col] = g[col].last()
    out = out.reset_index(drop=True)
    last = df["date"].iloc[-1]
    in_progress = last < last_trading_day(last, interval, holidays)
    return out, {"interval": interval, "last_bar_in_progress": bool(in_progress), "periods": len(out),
                 "last_period_start": out["period_start"].iloc[-1].isoformat(),
                 "last_period_trading_days": int(out["trading_days"].iloc[-1]),
                 "calc_version": CALC_VERSION}
