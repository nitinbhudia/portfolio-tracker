"""A made-up stock market for demo mode: daily prices for any ticker, exchange rates and index levels.

Deterministic: the same symbol always gets the same history (seeded from its name), and a later day never changes
earlier days, so prices downloaded in the demo yesterday still match today's. Stocks move with a synthetic market
(beta) plus their own noise, in trending and ranging spells, so charts, swings and Fibonacci levels look natural.
THIS IS NOT REAL MARKET DATA.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from .universe import BY_TICKER, FX_START, INDEXES

ANCHOR = date(2019, 1, 2)
HORIZON = 3400  # business days generated once (to about 2032); sliced to today
REGIMES = (-0.4, -0.15, 0.0, 0.0, 0.15, 0.4)  # yearly drift of a spell; averages to 0


def _seed(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(("pt-demo-v1", *parts)).encode()).digest()[:8], "big")


@lru_cache(maxsize=1)
def calendar() -> tuple[date, ...]:
    return tuple(d.date() for d in pd.bdate_range(start=pd.Timestamp(ANCHOR), periods=HORIZON))


def _upto(end: date | None) -> int:
    end = min(end or date.today(), date.today())
    cal = calendar()
    return int(np.searchsorted(np.array(cal, dtype="datetime64[D]"), np.datetime64(end, "D"), side="right"))


@lru_cache(maxsize=1)
def _market() -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(_seed("MARKET")))
    vol = 0.16 / np.sqrt(252)
    drift = np.empty(HORIZON)
    i = 0
    while i < HORIZON:
        n = int(rng.integers(40, 160))
        drift[i:i + n] = rng.choice((-0.25, 0.0, 0.08, 0.15, 0.25)) / 252
        i += n
    return drift + vol * rng.standard_normal(HORIZON)


def profile(symbol: str) -> tuple[float, float, float, float, float]:
    """start price, annual volatility, beta, yearly drift, strength of trending spells: the demo company's, or, for any
    other symbol (index, sector ETF, a stock you look up), a calmer, market-like one made up from the symbol."""
    s = symbol.upper()
    if s in BY_TICKER:
        c = BY_TICKER[s]
        return c.p0, c.vol, c.beta, c.drift, 1.0
    if symbol in INDEXES:
        p0, vol, beta = INDEXES[symbol]
        return p0, vol, beta, 0.0, 0.2
    h = _seed("profile", s)
    return 20 + h % 380, 0.15 + (h >> 12) % 10 / 100, 0.9 + (h >> 20) % 4 / 10, ((h >> 28) % 7 - 2) / 100, 0.3


@lru_cache(maxsize=512)
def _path(symbol: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    p0, vol, beta, drift, spells = profile(symbol)
    rng = np.random.Generator(np.random.PCG64(_seed("STOCK", symbol.upper())))
    mkt = _market()
    dvol = vol / np.sqrt(252)
    own = np.sqrt(max(dvol ** 2 - (beta * 0.16 / np.sqrt(252)) ** 2, (0.35 * dvol) ** 2))
    reg = np.empty(HORIZON)
    i = 0
    while i < HORIZON:
        n = int(rng.integers(25, 120))
        reg[i:i + n] = spells * rng.choice(REGIMES) / 252
        i += n
    rets = beta * mkt + reg + (drift - 0.5 * (own ** 2) * 252) / 252 + own * rng.standard_normal(HORIZON)
    close = p0 * np.exp(np.cumsum(rets))
    prev = np.concatenate([[p0], close[:-1]])
    open_ = prev * np.exp(dvol * 0.3 * rng.standard_normal(HORIZON))
    hi = np.maximum(open_, close) * (1 + np.abs(rng.standard_normal(HORIZON)) * dvol * 0.6)
    lo = np.minimum(open_, close) * (1 - np.abs(rng.standard_normal(HORIZON)) * dvol * 0.6)
    vol_ = (2e8 / max(p0, 1)) * (1 + 2.5 * np.abs(rets) / dvol) * rng.lognormal(0, 0.35, HORIZON)
    return open_, hi, lo, close, vol_


def bars(symbol: str, start: date | None = None, end: date | None = None) -> list[dict]:
    """Daily bars (date, open, high, low, close, volume) from `start` to `end` (default: today)."""
    o, h, l_, c, v = _path(symbol)
    cal = calendar()
    out = []
    for k in range(_upto(end)):
        d = cal[k]
        if start and d < start:
            continue
        out.append({"date": d, "open": round(float(o[k]), 4), "high": round(float(max(h[k], o[k], c[k])), 4),
                    "low": round(float(min(l_[k], o[k], c[k])), 4), "close": round(float(c[k]), 4),
                    "volume": int(v[k])})
    return out


def close_on(symbol: str, d: date) -> float:
    """The close on day `d`, or the last one before it."""
    rows = bars(symbol, d - timedelta(days=10), d)
    return rows[-1]["close"]


@lru_cache(maxsize=64)
def _fx_path(cur: str) -> np.ndarray:
    start = FX_START.get(cur, 1.0)
    rng = np.random.Generator(np.random.PCG64(_seed("FX", cur)))
    x = np.empty(HORIZON)
    x[0] = 0.0
    shocks = 0.07 / np.sqrt(252) * rng.standard_normal(HORIZON)
    for k in range(1, HORIZON):  # mean-reverting around the start level
        x[k] = x[k - 1] * 0.997 + shocks[k]
    return start * np.exp(x)


def fx(currencies: list[str], start: date, end: date | None = None) -> list[tuple[date, str, float]]:
    """ECB-style reference rates: units of each currency per 1 EUR, business days."""
    cal = calendar()
    out = []
    for cur in currencies:
        if cur == "EUR":
            continue
        p = _fx_path(cur)
        for k in range(_upto(end)):
            if cal[k] >= start:
                out.append((cal[k], cur, round(float(p[k]), 6)))
    return sorted(out)


def usd_per(cur: str, d: date) -> float:
    """USD for one unit of `cur` on day `d` (via the synthetic EUR rates)."""
    if cur == "USD":
        return 1.0
    rows = fx(["USD", cur], d - timedelta(days=10), d)
    last = {"EUR": 1.0, **{c: v for _, c, v in rows}}
    return last["USD"] / last[cur]
