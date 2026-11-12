"""Alert transitions (PHASE_6_TASK.md §1, §7.1, §7.6)."""
import copy

import pytest

from research.engine import alerts as A
from research.engine import fibonacci, swings

CFG = A.validate_config({})


def snap(close=100.0, fib=None, scores=None, ago=None, triggered=(), **ind):
    return {"close": close, "ind": ind, "fib": fib or {"status": "insufficient_swings"},
            "scores": scores or {}, "scores_ago": ago or {}, "triggered": list(triggered)}


def types(events):
    return sorted(e["key"] for e in events)


def fib_up(close, atr=3.0):
    sw = [swings.Swing("low", 10, 15, 80.0), swings.Swing("high", 100, 110, 120.0)]
    return fibonacci.analyse(sw, close, atr)  # 0.382 -> 104.72, 0.5 -> 100, 0.618 -> 95.28


# ---------------------------------------------------------------- crosses

def test_sma_cross_up_down_and_persisting():
    up = A.detect(snap(99, sma50=100.0, sma200=90.0), snap(101, sma50=100.0, sma200=90.0), CFG)
    assert "sma_cross:sma50:up" in types(up)
    down = A.detect(snap(101, sma50=100.0), snap(99, sma50=100.0), CFG)
    assert types(down) == ["sma_cross:sma50:down"]
    assert A.detect(snap(101, sma50=100.0), snap(102, sma50=100.0), CFG) == []  # stays above
    assert A.detect(snap(99), snap(101, sma50=100.0), CFG) == []  # missing prev SMA -> nothing


def test_sma_periods_are_configurable():
    cfg = A.validate_config({"rules": {"sma_cross": {"periods": [20]}}})
    prev, now = snap(99, sma20=100.0, sma50=100.0), snap(101, sma20=100.0, sma50=100.0)
    assert types(A.detect(prev, now, cfg)) == ["sma_cross:sma20:up"]


def test_golden_and_death_cross():
    g = A.detect(snap(sma50=99.0, sma200=100.0), snap(sma50=101.0, sma200=100.0), CFG)
    assert "golden_cross" in types(g)
    d = A.detect(snap(sma50=101.0, sma200=100.0), snap(sma50=99.0, sma200=100.0), CFG)
    assert "death_cross" in types(d)


def test_rsi_enter_zones_only_on_transition():
    assert types(A.detect(snap(rsi14=68.0), snap(rsi14=71.0), CFG)) == ["rsi:overbought"]
    assert A.detect(snap(rsi14=72.0), snap(rsi14=75.0), CFG) == []
    assert types(A.detect(snap(rsi14=32.0), snap(rsi14=29.0), CFG)) == ["rsi:oversold"]
    assert A.detect(snap(rsi14=None), snap(rsi14=29.0), CFG) == []


def test_macd_cross():
    e = A.detect(snap(macd_line=-0.1, macd_signal=0.0), snap(macd_line=0.1, macd_signal=0.0), CFG)
    assert types(e) == ["macd_cross:up"] and e[0]["direction"] == "bullish"
    assert A.detect(snap(macd_line=0.2, macd_signal=0.0), snap(macd_line=0.1, macd_signal=0.0), CFG) == []


def test_relvol_spike_and_indices():
    prev, now = snap(100, relvol20=1.2), snap(102, relvol20=2.5)
    e = A.detect(prev, now, CFG)
    assert types(e) == ["relvol_spike"] and e[0]["direction"] == "bullish"
    assert A.detect(prev, now, CFG, has_volume=False) == []
    assert A.detect(snap(relvol20=2.2), snap(relvol20=2.5), CFG) == []


# ---------------------------------------------------------------- Fibonacci

def test_fib_cross_uses_levels_known_at_previous_bar():
    e = A.detect(snap(103, fib=fib_up(103)), snap(106, fib=fib_up(106)), CFG)
    keys = types(e)
    assert "fib_cross:0.382:up" in keys
    assert not any(k.startswith("fib_approach:0.382") for k in keys)  # cross supersedes approach on same level
    assert A.detect(snap(106, fib=fib_up(106)), snap(107, fib=fib_up(107)), CFG) == []


def test_fib_approach_fires_once():
    far, near, nearer = fib_up(108), fib_up(105.5), fib_up(105.2)  # 0.382 @ 104.72, ATR 3 -> 0.5 ATR = 1.5
    e = A.detect(snap(108, fib=far), snap(105.5, fib=near), CFG)
    assert types(e) == ["fib_approach:0.382"]
    assert e[0]["details"]["distance_atr"] <= 0.5
    assert A.detect(snap(105.5, fib=near), snap(105.2, fib=nearer), CFG) == []  # still close: no repeat


def test_fib_missing_gives_nothing():
    assert A.detect(snap(100), snap(101), CFG) == []


# ---------------------------------------------------------------- score / setups

def test_score_change_transition():
    prev = snap(scores={"short": 60.0}, ago={"short": 55.0})
    now = snap(scores={"short": 70.0}, ago={"short": 58.0})
    e = A.detect(prev, now, CFG)
    assert types(e) == ["score_change:short:up"] and e[0]["details"]["change"] == pytest.approx(12.0)
    still = snap(scores={"short": 72.0}, ago={"short": 60.0})
    assert A.detect(now, still, CFG) == []  # already material yesterday, same direction
    down = snap(scores={"short": 40.0}, ago={"short": 55.0})
    assert types(A.detect(now, down, CFG)) == ["score_change:short:down"]
    assert A.detect(snap(), snap(scores={"short": 70.0}, ago={"short": None}), CFG) == []


def test_new_setup_only_when_newly_triggered():
    e = A.detect(snap(triggered=["bullish_ma"]), snap(triggered=["bullish_ma", "breakout"]), CFG)
    assert types(e) == ["setup_new:breakout"] and e[0]["direction"] == "bullish"


def test_disabled_rules_do_not_fire():
    cfg = A.validate_config({"rules": {"rsi": {"enabled": False}}})
    assert A.detect(snap(rsi14=68.0), snap(rsi14=71.0), cfg) == []


# ---------------------------------------------------------------- config validation

@pytest.mark.parametrize("bad", [
    {"scope": "everything"},
    {"cooldown_bars": -1},
    {"cooldown_bars": 2.5},
    {"rules": {"nope": {}}},
    {"rules": {"rsi": {"overbought": 120}}},
    {"rules": {"rsi": {"overbought": 50, "oversold": 50}}},
    {"rules": {"rsi": {"enabled": "yes"}}},
    {"rules": {"sma_cross": {"periods": [30]}}},
    {"rules": {"score_change": {"lookback": 2.5}}},
    {"rules": {"fib_approach": {"atr": True}}},
    {"rules": {"rsi": {"colour": "red"}}},
    {"extra": 1},
])
def test_config_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        A.validate_config(bad)


def test_config_merges_over_defaults_and_hash_changes():
    cfg = A.validate_config({"cooldown_bars": 3, "rules": {"sma_cross": {"periods": [200, 50, 50]}}})
    assert cfg["cooldown_bars"] == 3 and cfg["rules"]["sma_cross"]["periods"] == [50, 200]
    assert cfg["rules"]["rsi"] == A.DEFAULT_CONFIG["rules"]["rsi"]
    assert A.config_hash(cfg, "medium") != A.config_hash(CFG, "medium")
    assert A.config_hash(CFG, "medium") != A.config_hash(CFG, "high")
    assert A.DEFAULT_CONFIG == copy.deepcopy(A.DEFAULT_CONFIG)  # defaults never mutated
    assert A.validate_config({}) == A.DEFAULT_CONFIG
