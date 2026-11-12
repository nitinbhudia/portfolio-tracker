import numpy as np
import pytest

from research.engine import fibonacci as F
from research.engine import indicators as I
from research.engine import swings as S

# Hand-built zigzag (high == low == price, ATR fixed at 1). Derivation in DEVELOPMENT.md.
ZIG = np.array([100, 101, 102, 103, 104, 105, 104, 103, 102, 103, 104, 105, 106, 107,
                106, 105, 104, 105], dtype=float)
ATR1 = np.ones_like(ZIG)


def _t(sw):
    return [(s.kind, s.index, s.confirmed_index, s.price) for s in sw]


def test_swings_k_2_5():
    assert _t(S.detect_swings(ZIG, ZIG, ATR1, 2.5)) == [
        ("low", 0, 3, 100.0), ("high", 5, 8, 105.0), ("low", 8, 11, 102.0), ("high", 13, 16, 107.0)]


def test_swings_k_1_5():
    assert _t(S.detect_swings(ZIG, ZIG, ATR1, 1.5)) == [
        ("low", 0, 2, 100.0), ("high", 5, 7, 105.0), ("low", 8, 10, 102.0), ("high", 13, 15, 107.0)]


def test_equal_highs_tie_break_earliest():
    p = np.array([100, 103, 105, 105, 102, 101.0])
    sw = S.detect_swings(p, p, np.ones_like(p), 2.5)
    assert _t(sw)[:2] == [("low", 0, 1, 100.0), ("high", 2, 4, 105.0)]


def test_swings_alternate_and_confirm_after_occurrence(aapl):
    a = I.atr(aapl["high"], aapl["low"], aapl["close"])
    sw = S.detect_swings(aapl["high"], aapl["low"], a, 2.5)
    assert len(sw) > 6
    assert all(x.kind != y.kind for x, y in zip(sw, sw[1:]))
    assert all(s.confirmed_index > s.index for s in sw)


def test_swings_no_look_ahead(aapl):
    h, l, c = aapl["high"], aapl["low"], aapl["close"]
    full = S.detect_swings(h, l, I.atr(h, l, c), 2.5)
    for t in np.random.default_rng(3).integers(30, 599, 20):
        trunc = S.detect_swings(h[: t + 1], l[: t + 1], I.atr(h[: t + 1], l[: t + 1], c[: t + 1]), 2.5)
        assert _t(S.confirmed_as_of(full, t)) == _t(trunc)


def test_resolve_k():
    assert S.resolve_k("medium") == 2.5 and S.resolve_k("high") == 1.5 and S.resolve_k("3") == 3.0
    with pytest.raises(ValueError):
        S.resolve_k(0.1)
    with pytest.raises(ValueError):
        S.resolve_k("extreme")


# ---------- Fibonacci ----------
def _px(levels, ratio):
    return next(lv["price"] for lv in levels if lv["ratio"] == ratio)


def test_retracements_and_extensions_up():
    lv, dropped = F.fibonacci_levels(110, 100, "up")
    assert _px(lv, 0.0) == 110 and _px(lv, 1.0) == 100
    assert _px(lv, 0.618) == pytest.approx(103.82, abs=1e-9)
    assert _px(lv, 0.236) == pytest.approx(107.64, abs=1e-9)
    assert _px(lv, 1.618) == pytest.approx(116.18, abs=1e-9)
    assert _px(lv, 2.618) == pytest.approx(126.18, abs=1e-9)
    assert dropped == []


def test_retracements_and_extensions_down():
    lv, _ = F.fibonacci_levels(110, 100, "down")
    assert _px(lv, 0.0) == 100 and _px(lv, 1.0) == 110
    assert _px(lv, 0.618) == pytest.approx(106.18, abs=1e-9)
    assert _px(lv, 1.272) == pytest.approx(97.28, abs=1e-9)
    assert _px(lv, 2.618) == pytest.approx(83.82, abs=1e-9)


def test_negative_extensions_dropped():
    lv, dropped = F.fibonacci_levels(10, 5, "down")
    assert {d["ratio"] for d in dropped} == {2.0, 2.618}
    assert _px(lv, 1.618) == pytest.approx(10 - 1.618 * 5)


def test_analyse_uses_last_two_swings_nearest_and_depth():
    sw = [S.Swing("high", 0, 2, 120.0), S.Swing("low", 3, 5, 100.0), S.Swing("high", 8, 10, 110.0)]
    r = F.analyse(sw, close=104.0, atr=2.0)
    assert r["direction"] == "up"  # low (idx 3) before high (idx 8)
    assert r["swing_low"]["price"] == 100 and r["swing_high"]["price"] == 110
    assert r["nearest"]["ratio"] == 0.618  # 103.82 is closest to 104
    assert r["nearest"]["distance_abs"] == pytest.approx(0.18)
    assert r["nearest"]["distance_atr"] == pytest.approx(0.09)
    assert r["nearest"]["price_above_level"] is True
    assert r["retracement_depth"] == pytest.approx(0.6)
    assert r["beyond_swing"] is False


def test_beyond_swing_flag_and_insufficient():
    sw = [S.Swing("low", 0, 2, 100.0), S.Swing("high", 4, 6, 110.0)]
    assert F.analyse(sw, close=95.0, atr=1.0)["beyond_swing"] is True
    assert F.analyse(sw[:1], close=95.0, atr=1.0)["status"] == "insufficient_swings"


def test_nearest_exact_level():
    sw = [S.Swing("low", 0, 1, 100.0), S.Swing("high", 2, 3, 200.0)]
    r = F.analyse(sw, close=150.0, atr=5.0)
    assert r["nearest"]["ratio"] == 0.5 and r["nearest"]["distance_abs"] == 0
    assert sum(lv["is_nearest"] for lv in r["levels"]) == 1
