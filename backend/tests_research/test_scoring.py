import pytest

from research.engine import scoring as SC

FIB_UP_SUPPORT = {"status": "ok", "direction": "up",
                  "nearest": {"ratio": 0.382, "distance_atr": 0.5, "price_above_level": True}}
FIB_DOWN_RESIST = {"status": "ok", "direction": "down",
                   "nearest": {"ratio": 0.5, "distance_atr": 0.4, "price_above_level": False}}

BULL = dict(close=110, prev_close=109, sma10=108, sma20=105, sma50=100, sma100=95, sma200=90,
            rsi14=60, macd_hist=0.5, macd_line=1.0, macd_signal=0.5, roc60=0.1, relvol20=2.0)
BEAR = dict(close=90, prev_close=91, sma10=92, sma20=95, sma50=100, sma100=105, sma200=110,
            rsi14=25, macd_hist=-0.5, macd_line=-1.0, macd_signal=-0.5, roc60=-0.1, relvol20=2.0)
NEUTRAL = dict(close=100, prev_close=100, sma10=99, sma20=101, sma50=100, sma100=100, sma200=100,
               rsi14=45, macd_hist=0.2, macd_line=0.1, macd_signal=0.2, roc60=0.0, relvol20=1.0)


def test_bullish_fixture():
    s = SC.score("short", BULL, FIB_UP_SUPPORT)
    # 0.4*100 + 0.3*100 + 0.15*70 + 0.15*80 = 92.5
    assert s["total"] == 92.5 and s["classification"] == "bullish"
    assert s["components"]["fibonacci"]["points"] == 70
    assert s["components"]["volume"]["points"] == 80


def test_bearish_fixture():
    s = SC.score("short", BEAR, FIB_DOWN_RESIST)
    # 0 + 0 (RSI<30 gives no bullish credit, hist<0) + 0.15*30 + 0.15*20 = 7.5
    assert s["total"] == 7.5 and s["classification"] == "bearish"


def test_neutral_fixture():
    s = SC.score("short", NEUTRAL, None)
    # trend 1/3*100, momentum (50+100)/2 = 75, fib 50, vol 50
    expected = 0.4 * 100 / 3 + 0.3 * 75 + 0.15 * 50 + 0.15 * 50
    assert s["total"] == round(expected, 1) == 50.8
    assert s["classification"] == "neutral"


def test_medium_and_long_rules():
    assert SC.score("medium", BULL, FIB_UP_SUPPORT)["total"] == 92.5
    assert SC.score("long", BEAR, FIB_DOWN_RESIST)["total"] == 7.5


def test_rsi_overbought_and_oversold_points():
    assert SC._rsi_points(75)[0] == 50 and SC._rsi_points(29.9)[0] == 0 and SC._rsi_points(30)[0] == 50


def test_renormalises_when_volume_missing():
    s = SC.score("short", {**BULL, "relvol20": None}, FIB_UP_SUPPORT)
    assert s["excluded_components"] == ["volume"]
    assert s["total"] == round((40 + 30 + 10.5) / 0.85, 1)
    assert sum(c["effective_weight"] for c in s["components"].values()) == pytest.approx(1.0)


def test_insufficient_data_when_majority_weight_missing():
    s = SC.score("long", {**BULL, "sma200": None, "roc60": None}, None)
    assert s["status"] == "insufficient_data" and s["total"] is None


def test_score_is_deterministic():
    assert SC.score("short", BULL, FIB_UP_SUPPORT) == SC.score("short", dict(BULL), dict(FIB_UP_SUPPORT))


def test_breakdown_contributions_sum_to_total():
    s = SC.score("medium", NEUTRAL, FIB_UP_SUPPORT)
    assert round(sum(c["contribution"] for c in s["components"].values()), 1) == s["total"]
