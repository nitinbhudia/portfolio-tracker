"""Ranking metrics, rotation detection and the Rotation Signal Score (SECTOR_ROTATION_TASK.md §5.2)."""
import itertools
from datetime import date, timedelta

import numpy as np
import pytest

from research.engine import indicators, rotation as R, rrg


def test_every_quadrant_change_is_categorised():
    for a, b in itertools.permutations(rrg.QUADRANTS, 2):
        assert (a, b) in R.TRANSITIONS


def _series(ratio, momentum):
    return rrg.RrgSeries(np.full(len(ratio), 100.0), np.asarray(ratio, float), np.asarray(momentum, float))


def dates(n):
    return [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]


def test_transitions_and_crossings():
    s = _series([98, 98.5, 99, 99.5, 100.5, 101, 100.8], [99, 100.5, 101, 102, 101, 99.5, 99])
    flat = np.full(7, 50.0)
    ev = R.transitions(s, dates(7), flat, flat, 6, lookback=10)
    labels = [(e["date"], e["label"]) for e in ev]
    assert labels == [("2025-01-02", "Lagging → Improving"), ("2025-01-05", "Improving → Leading"),
                      ("2025-01-06", "Leading → Weakening")]
    assert [e["category"] for e in ev] == ["early_opportunity", "established", "exit_warning"]
    assert ev[-1]["sessions_ago"] == 1
    # momentum crossing above 100 inside Improving is its own early signal; inside Weakening, a warning
    s2 = _series([98, 98, 98], [101, 99, 100.2])
    ev2 = R.transitions(s2, dates(3), np.full(3, 50.0), np.full(3, 50.0), 2)
    assert [e["kind"] for e in ev2] == ["quadrant", "quadrant"]  # lagging<->improving changes quadrant
    s3 = _series([98, 98, 98, 98], [99, 99.5, 99.8, 99.9])
    assert R.transitions(s3, dates(4), np.full(4, 50.0), np.full(4, 50.0), 3) == []


def test_close_below_sma50_is_deterioration():
    s = _series([101] * 4, [101] * 4)
    close, sma = np.array([105, 104, 99, 98.0]), np.full(4, 100.0)
    ev = R.transitions(s, dates(4), close, sma, 3)
    assert [(e["kind"], e["category"]) for e in ev] == [("ma_cross", "deterioration")]


def test_metrics_keep_absolute_and_relative_apart():
    n = 260
    close = np.linspace(100, 90, n)            # falling in absolute terms...
    bench = np.linspace(100, 70, n)            # ...but much less than the market
    vol = np.concatenate([np.full(n - 20, 1000.0), np.full(20, 2000.0)])
    ind = indicators.compute_all(close, close, close, close, vol)
    m = R.metrics(close, vol, ind, bench, n - 1)
    assert m["change_20d_pct"] < 0 and m["relative_20d_pct"] > 0 and m["absolute_trend"] == "down"
    assert m["volume_trend"] == pytest.approx(2000 / ((30 * 1000 + 20 * 2000) / 50)) and m["volume_trend_label"] == "rising"
    assert m["change_10d_pct"] == pytest.approx((close[-1] / close[-11] - 1) * 100)
    assert m["above_sma200"] is False


def test_score_components_by_hand_and_weights():
    n = 30
    s = _series(np.full(n, 102.0), np.concatenate([np.full(n - 5, 100.0), np.full(5, 101.0)]))
    m = {"close": 110, "sma20": 108, "sma50": 105, "sma200": 100, "volume_trend": 1.1}
    ev = [{"kind": "quadrant", "from": "improving", "to": "leading", "sessions_ago": 3, "label": "Improving → Leading"}]
    sc = R.score(s, m, ev, n - 1)
    c = sc["components"]
    assert c["relative_strength"]["points"] == 70 and c["relative_momentum"]["points"] == 60
    assert c["acceleration"]["points"] == 60 and c["ma_alignment"]["points"] == 100
    assert c["volume"]["points"] == pytest.approx(70) and c["transition"]["points"] == 90
    expected = (70 * 25 + 60 * 25 + 60 * 15 + 100 * 15 + 70 * 10 + 90 * 10) / 100
    assert sc["total"] == pytest.approx(round(expected, 1))
    only_rs = R.score(s, m, ev, n - 1, {k: 0 for k in R.DEFAULT_WEIGHTS} | {"relative_strength": 1})
    assert only_rs["total"] == 70.0
    old = [{**ev[0], "sessions_ago": 15}]
    assert R.score(s, m, old, n - 1)["components"]["transition"]["points"] == 50  # too old to count


def test_score_clips_and_handles_missing():
    s = _series([120.0] * 10, [80.0] * 10)
    m = {"close": None, "sma20": None, "sma50": None, "sma200": None, "volume_trend": None}
    sc = R.score(s, m, [], 9)
    assert sc["components"]["relative_strength"]["points"] == 100 and sc["components"]["relative_momentum"]["points"] == 0
    assert set(sc["excluded"]) == {"ma_alignment", "volume"}
    warm = _series([np.nan] * 3, [np.nan] * 3)
    assert R.score(warm, m, [], 2)["status"] == "insufficient_data"


@pytest.mark.parametrize("bad", [{"nope": 1}, {"volume": -1}, {"volume": 150}, {"volume": True},
                                 {k: 0 for k in R.DEFAULT_WEIGHTS}])
def test_bad_weights(bad):
    with pytest.raises(ValueError):
        R.validate_weights(bad)
