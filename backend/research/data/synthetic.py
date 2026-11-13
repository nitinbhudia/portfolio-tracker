"""Deterministic synthetic OHLCV and FX generator.

* The seed is derived from sha256(ticker + exchange); nothing depends on the clock.
* The calendar is fixed: N business days (Mon-Fri, holidays not modelled) ending on
  settings.synthetic_end_date.
* Regime-switching GBM (trending / ranging regimes), so that real swings exist.

THIS DATA IS NOT REAL MARKET DATA. It is labelled SYNTHETIC throughout the app.
"""
from __future__ import annotations

import hashlib
from datetime import date

import numpy as np
import pandas as pd

SOURCE = "synthetic"
GENERATOR_VERSION = "synthetic-v1"
REGIME_DRIFTS = (-0.45, -0.15, 0.0, 0.0, 0.15, 0.35, 0.6)  # annualised


def seed_for(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def business_calendar(end: date, n: int) -> list[date]:
    return [d.date() for d in pd.bdate_range(end=pd.Timestamp(end), periods=n)]


def generate_ohlcv(ticker: str, mic: str, start_price: float, annual_vol: float,
                   end: date, n: int, with_volume: bool = True,
                   gap: tuple[int, int] | None = None) -> list[dict]:
    rng = np.random.Generator(np.random.PCG64(seed_for(ticker, mic, GENERATOR_VERSION)))
    dates = business_calendar(end, n)
    dvol = annual_vol / np.sqrt(252)

    drifts = np.empty(n)
    i = 0
    while i < n:
        length = int(rng.integers(25, 110))
        drifts[i : i + length] = rng.choice(REGIME_DRIFTS) / 252
        i += length

    rets = drifts + dvol * rng.standard_normal(n)
    close = start_price * np.exp(np.cumsum(rets))
    prev = np.concatenate([[start_price], close[:-1]])
    open_ = prev * np.exp(dvol * 0.3 * rng.standard_normal(n))
    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    high = body_hi * (1 + np.abs(rng.standard_normal(n)) * dvol * 0.6)
    low = body_lo * (1 - np.abs(rng.standard_normal(n)) * dvol * 0.6)

    base_vol = 2e9 / start_price
    shock = 1 + 2.5 * np.abs(rets - drifts) / dvol
    volume = base_vol * shock * rng.lognormal(0.0, 0.35, n)

    skip = set()
    if gap:
        skip = set(range(gap[0], gap[0] + gap[1]))

    rows = []
    for k in range(n):
        if k in skip:
            continue
        o, h, l_, c = (round(float(v), 4) for v in (open_[k], high[k], low[k], close[k]))
        h = max(h, o, c)
        l_ = min(l_, o, c)
        rows.append({
            "date": dates[k], "open": o, "high": h, "low": l_, "close": c,
            "adj_close": c,  # no corporate actions in synthetic data
            "volume": int(volume[k]) if with_volume else None,
        })
    return rows


def generate_fx(base: str, quote: str, start: float, annual_vol: float,
                end: date, n: int) -> list[dict]:
    rng = np.random.Generator(np.random.PCG64(seed_for("FX", base, quote, GENERATOR_VERSION)))
    dates = business_calendar(end, n)
    rate = start * np.exp(np.cumsum(annual_vol / np.sqrt(252) * rng.standard_normal(n)))
    return [{"date": d, "rate": round(float(r), 6)} for d, r in zip(dates, rate)]


def generate_sector_ohlcv(ticker: str, mic: str, market: list[dict], beta: float, idio_vol: float,
                          start_price: float = 100.0) -> list[dict]:
    """Synthetic sector ETF = (synthetic market)^beta x an idiosyncratic regime-switching path.

    Each day's O/H/L/C from the idiosyncratic path is scaled by the same market factor, so bars stay
    consistent (low <= open/close <= high). Dates follow `market`. SYNTHETIC, NOT REAL DATA.
    """
    end, n = market[-1]["date"], len(market)
    idio = generate_ohlcv(ticker, mic, start_price, idio_vol, end, n)
    m0 = market[0]["close"]
    rows = []
    for mk, r in zip(market, idio):
        f = (mk["close"] / m0) ** beta
        o, h, l_, c = (round(r[k] * f, 4) for k in ("open", "high", "low", "close"))
        rows.append({"date": mk["date"], "open": o, "high": max(h, o, c), "low": min(l_, o, c), "close": c,
                     "adj_close": c, "volume": r["volume"]})
    return rows
