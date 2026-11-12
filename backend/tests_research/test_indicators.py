import json
import math
from pathlib import Path

import numpy as np
import pytest

from research.engine import indicators as I

GOLD = json.loads((Path(__file__).parent / "fixtures" / "golden_indicators.json").read_text())


# ---------- SMA ----------
def test_sma_golden():
    c = np.arange(1, 31, dtype=float)
    g = GOLD["sma_basic"]
    s10, s20 = I.sma(c, 10), I.sma(c, 20)
    assert np.isnan(s10[:9]).all() and np.isnan(s20[:19]).all()
    assert s10[9] == g["sma10_at_9"] and s10[29] == g["sma10_at_29"]
    assert s20[19] == g["sma20_at_19"] and s20[29] == g["sma20_at_29"]


def test_sma_shorter_than_window_is_all_nan():
    assert np.isnan(I.sma([1, 2, 3], 10)).all()


# ---------- EMA / MACD ----------
def test_ema_is_sma_seeded():
    c = np.array([1, 2, 3, 4, 5, 6.0])
    e = I.ema(c, 3)
    assert np.isnan(e[:2]).all()
    assert e[2] == 2.0  # SMA(1,2,3)
    assert e[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)  # alpha = 2/(3+1)
    assert e[4] == pytest.approx(0.5 * 5 + 0.5 * e[3])


def test_macd_warmup_indices(aapl):
    line, sig, hist = I.macd(aapl["close"])
    assert np.isnan(line[:25]).all() and not np.isnan(line[25])
    assert np.isnan(sig[:33]).all() and not np.isnan(sig[33])
    assert np.allclose(hist[33:], line[33:] - sig[33:])


def test_macd_constant_series_is_zero():
    line, sig, hist = I.macd(np.full(60, 50.0))
    assert np.allclose(line[25:], 0) and np.allclose(sig[33:], 0) and np.allclose(hist[33:], 0)


# ---------- RSI ----------
def test_rsi_golden_alternating():
    # 14 changes: +1,-1,... -> avg gain = avg loss = 0.5 -> RSI 50.
    # Next change +1: avg_g = (0.5*13+1)/14 = 7.5/14, avg_l = 6.5/14 -> RSI = 100*7.5/14 = 53.5714...
    changes = [1, -1] * 7 + [1]
    c = np.concatenate([[100.0], 100 + np.cumsum(changes)])
    r = I.rsi(c, 14)
    g = GOLD["rsi_alternating"]
    assert np.isnan(r[:14]).all()
    assert r[14] == pytest.approx(g["rsi_at_14"])
    assert r[15] == pytest.approx(g["rsi_at_15"], abs=1e-10)
    assert g["rsi_at_15"] == pytest.approx(100 * 7.5 / 14)


def test_rsi_bounds_and_monotonic():
    up = np.arange(30, dtype=float)
    assert (I.rsi(up)[14:] == 100).all()
    down = up[::-1].copy()
    assert (I.rsi(down)[14:] == 0).all()


# ---------- ATR ----------
def test_atr_true_range_uses_previous_close_on_gap():
    h = np.array([10, 11, 18.0]); l = np.array([9, 10, 17.0]); c = np.array([9.5, 11, 17.5])
    tr = I.true_range(h, l, c)
    assert tr[0] == 1 and tr[1] == 1.5  # |11 - 9.5| > 11-10
    assert tr[2] == GOLD["atr_gap_up"]["tr_gap_bar"]  # |18 - 11| = 7 (gap up)


def test_atr_wilder_seed_and_smoothing():
    n = 20
    h = np.full(n, 11.0); l = np.full(n, 9.0); c = np.full(n, 10.0)
    h[16] = 15.0  # TR = max(15-9, |15-10|, |9-10|) = 6 at bar 16
    a = I.atr(h, l, c, 14)
    assert np.isnan(a[:14]).all()
    assert a[14] == 2.0 and a[15] == 2.0
    assert a[16] == pytest.approx((2.0 * 13 + 6.0) / 14)


# ---------- Relative volume ----------
def test_relative_volume_excludes_today():
    v = np.array([100.0] * 20 + [1000.0])
    rv = I.relative_volume(v, 20)
    assert np.isnan(rv[:20]).all()
    assert rv[20] == 10.0  # if today were included the mean would be 142.86


def test_relative_volume_missing_volume_is_nan():
    v = np.full(25, np.nan)
    assert np.isnan(I.relative_volume(v)).all()


# ---------- No look-ahead ----------
def test_indicators_have_no_look_ahead(aapl):
    full = I.compute_all(*(aapl[k] for k in ("open", "high", "low", "close", "volume")))
    rng = np.random.default_rng(7)
    for t in rng.integers(40, 599, 20):
        trunc = I.compute_all(*(aapl[k][: t + 1] for k in ("open", "high", "low", "close", "volume")))
        for name in full:
            a, b = full[name][t], trunc[name][t]
            assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b, rel=1e-12), name


# ---------- Optional cross-check against TA-Lib ----------
def test_cross_check_talib(aapl):
    talib = pytest.importorskip("talib")
    o, h, l, c = (aapl[k] for k in ("open", "high", "low", "close"))

    def same(a, b):
        assert np.array_equal(np.isnan(a), np.isnan(b))
        m = ~np.isnan(a)
        assert np.allclose(a[m], b[m], rtol=0, atol=1e-8)

    for n in I.SMA_PERIODS:
        same(I.sma(c, n), talib.SMA(c, n))
    same(I.ema(c, 12), talib.EMA(c, 12))
    same(I.ema(c, 26), talib.EMA(c, 26))
    same(I.rsi(c, 14), talib.RSI(c, 14))
    same(I.atr(h, l, c, 14), talib.ATR(h, l, c, 14))
    line, sig, _ = I.macd(c)
    same(sig, talib.EMA(line, 9))
