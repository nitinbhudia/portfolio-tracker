"""RRG approximation engine (SECTOR_ROTATION_TASK.md §5.1)."""
from datetime import date, timedelta

import numpy as np
import pytest

from research.engine import rrg


def test_rolling_z_by_hand():
    x = np.array([1.0, 2.0, 3.0, 4.0, 10.0])
    z = rrg.rolling_z(x, 3)
    assert np.isnan(z[:2]).all()
    assert z[2] == pytest.approx((3 - 2) / 1.0)                        # window 1,2,3: mean 2, sd 1
    win = np.array([2.0, 3.0, 4.0])
    assert z[3] == pytest.approx((4 - win.mean()) / win.std(ddof=1))
    assert np.isnan(rrg.rolling_z(np.ones(5), 3)[4])                    # flat -> undefined, never invented


def test_benchmark_against_itself_is_undefined_not_100():
    b = 100 + np.cumsum(np.random.default_rng(1).standard_normal(300))
    s = rrg.compute(b, b, "1m")
    assert np.allclose(s.rs, 100.0) and np.isnan(s.ratio).all()


def test_outperformer_reads_above_100_and_turnaround_is_improving():
    n = 300
    bench = np.full(n, 100.0)
    # steadily rising relative strength -> RS-Ratio above 100
    up = 100 * np.exp(np.linspace(0, 0.3, n))
    s = rrg.compute(up, bench, "1m")
    assert s.ratio[-1] > 100
    # long relative decline that has just flattened out: ratio still below 100, momentum turning up -> Improving
    path = np.concatenate([np.linspace(130, 90, 300), np.linspace(90, 91, 15)])
    t = rrg.compute(path, np.full(len(path), 100.0), "3m")
    assert t.ratio[-1] < 100 and t.momentum[-1] > 100
    assert rrg.quadrant(t.ratio[-1], t.momentum[-1]) == "improving"
    # ...then rotates clockwise: a recovery becomes Leading, and once its pace stops accelerating, Weakening
    seq = []
    for k in (20, 60):
        longer = np.concatenate([path, np.linspace(91, 110, k)])
        u = rrg.compute(longer, np.full(len(longer), 100.0), "3m")
        seq.append(rrg.quadrant(u.ratio[-1], u.momentum[-1]))
    assert seq == ["leading", "weakening"]


@pytest.mark.parametrize("r,m,q", [(101, 101, "leading"), (101, 99, "weakening"), (99, 99, "lagging"),
                                   (99, 101, "improving"), (100, 100, "leading"), (None, 100, None)])
def test_quadrants(r, m, q):
    assert rrg.quadrant(r, m) == q


def test_trail_lengths_and_dates():
    rng = np.random.default_rng(3)
    n = 400
    a = 100 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))
    b = 100 * np.exp(np.cumsum(0.008 * rng.standard_normal(n)))
    s = rrg.compute(a, b, "1m")
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    for k in rrg.TRAILS:
        tr = rrg.trail(s, dates, n - 1, k)
        assert len(tr) == k and tr[-1]["date"] == dates[-1].isoformat()
        assert all(p["quadrant"] in rrg.QUADRANTS for p in tr)
    assert rrg.trail(s, dates, 5, 10) == []  # still in warm-up: no points, nothing invented


@pytest.mark.parametrize("tf", list(rrg.TIMEFRAMES))
def test_no_lookahead(tf):
    rng = np.random.default_rng(7)
    n = 700
    a = 100 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))
    b = 100 * np.exp(np.cumsum(0.008 * rng.standard_normal(n)))
    full = rrg.compute(a, b, tf)
    T = n - 37
    cut = rrg.compute(a[:T], b[:T], tf)
    np.testing.assert_array_equal(full.ratio[:T], cut.ratio)
    np.testing.assert_array_equal(full.momentum[:T], cut.momentum)
    first = int(np.flatnonzero(~np.isnan(full.momentum))[0])
    assert first <= rrg.bars_needed(tf, 0)  # the documented requirement is enough


def test_bad_input():
    with pytest.raises(ValueError):
        rrg.compute([1, 2], [1, 2, 3])
    with pytest.raises(ValueError):
        rrg.compute([1, 2], [1, 2], "2y")
