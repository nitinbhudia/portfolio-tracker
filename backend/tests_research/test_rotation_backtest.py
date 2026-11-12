"""Rotation backtest engine (ROTATION_BACKTEST_TASK.md §5)."""
from datetime import date, timedelta

import numpy as np
import pytest

from research.data import synthetic
from research.engine import backtest as B
from research.engine import rotation_backtest as RB
from research.engine import rrg

N = 320
ZERO = B.Costs(0, 0)


def days(n=N):
    out, d = [], date(2020, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def flat_universe(tickers=("AAA", "BBB", "CCC"), n=N, prices=None):
    prices = prices or {}
    secs = {}
    for t in tickers:
        c = np.asarray(prices.get(t, np.full(n, 100.0)), dtype=float)
        secs[t] = {"sector": f"Sector {t}", "open": c, "high": c, "low": c, "close": c, "volume": np.full(n, 1000.0)}
    b = np.full(n, 100.0)
    return RB.Universe(days(n), b, b, secs, "BENCH")


def set_quadrants(u, tf, plan: dict[str, list[tuple[int, str]]]):
    """plan: ticker -> [(from_bar, quadrant)] applied in order; lagging before the first entry."""
    pts = {"leading": (101, 101), "weakening": (101, 99), "lagging": (99, 99), "improving": (99, 101)}
    out = {}
    for tk in u.tickers:
        r, m = np.full(u.n, 99.0), np.full(u.n, 99.0)
        for start, q in plan.get(tk, []):
            r[start:], m[start:] = pts[q]
        out[tk] = rrg.RrgSeries(np.full(u.n, 100.0), r, m)
    u._rrg[tf] = out


QH = RB.STRATEGIES["quadrant_hold"]


def test_quadrant_hold_entry_exit_timing():
    u = flat_universe()
    set_quadrants(u, "3m", {"AAA": [(210, "improving"), (220, "weakening")]})
    r = RB.simulate(u, QH, {"hold": "improving", "timeframe": "3m"}, ZERO, 200, 300)
    (t,) = r.trades
    assert t["ticker"] == "AAA" and t["entry_date"] == u.dates[211].isoformat()   # decided at 210's close
    assert t["exit_date"] == u.dates[221].isoformat() and t["exit_reason"] == "left the selection"
    assert sum(r.invested) == 10 and r.days_held["AAA"] == 10
    assert r.curve[-1] == pytest.approx(1.0)  # flat prices, no costs


def test_costs_on_turnover_by_hand():
    u = flat_universe()
    set_quadrants(u, "3m", {"AAA": [(210, "improving"), (220, "lagging")]})
    costs = B.Costs(5, 10)
    rate = 0.0015
    r = RB.simulate(u, QH, {"hold": "improving", "timeframe": "3m"}, costs, 200, 300)
    assert r.curve[-1] == pytest.approx((1 - rate) ** 2)          # charged on entry and on exit
    expected_trade = (100 * (1 - costs.slip)) / (100 * (1 + costs.slip)) * (1 - costs.comm) ** 2 - 1
    assert r.trades[0]["return_pct"] == pytest.approx(expected_trade * 100)


def test_equal_weight_and_cash_when_nothing_qualifies():
    a = np.full(N, 100.0)
    a[215:] = 110.0  # AAA +10% while held
    u = flat_universe(prices={"AAA": a})
    set_quadrants(u, "3m", {"AAA": [(210, "leading")], "BBB": [(210, "leading")]})
    r = RB.simulate(u, QH, {"hold": "leading", "timeframe": "3m"}, ZERO, 200, 300)
    assert r.curve[-1] == pytest.approx(0.5 * 1.1 + 0.5 * 1.0)   # half in each, AAA up 10%
    assert r.invested[:11] == [False] * 11 and r.curve[5] == 1.0  # cash (0% return) before anything qualifies
    assert {t["ticker"] for t in r.trades} == {"AAA", "BBB"} and all(t["exit_reason"] == "end of period" for t in r.trades)


def test_top_score_cadence_and_selection():
    u = flat_universe(("AAA", "BBB", "CCC", "DDD"))
    calls = []

    def fake_scores(tf, t):
        calls.append(t)
        flip = (t // 7) % 2 == 0
        return {"AAA": 90 if flip else 10, "BBB": 80, "CCC": 70 if flip else 95, "DDD": None}
    u.scores = fake_scores
    r = RB.simulate(u, RB.STRATEGIES["top_score"], {"n": 2, "every": 5, "timeframe": "3m"}, ZERO, 200, 260)
    assert all((t - 200) % 5 == 0 for t in calls)                      # only consulted on re-selection days
    held = {t["ticker"] for t in r.trades}
    assert "DDD" not in held and {"AAA", "BBB", "CCC"} <= held        # a missing score is never selected


def test_comparisons_by_hand():
    a = np.linspace(100, 120, N)
    u = flat_universe(prices={"AAA": a})
    u.bo = np.full(N, 50.0)
    u.bc = np.full(N, 50.0)
    u.bc[-1] = 60.0
    costs = B.Costs(5, 10)
    bh = RB.benchmark_hold(u, costs, 200, N)
    assert bh.curve[-1] == pytest.approx((1 - costs.comm) / (50 * (1 + costs.slip)) * 60 * (1 - costs.slip) * (1 - costs.comm))
    ew = RB.equal_weight_hold(u, costs, 200, N)
    k = 3
    gross = sum((1 - costs.comm) / k / (u.o[t][200] * (1 + costs.slip)) * u.c[t][-1] for t in u.tickers)
    assert ew.curve[-1] == pytest.approx(gross * (1 - costs.slip) * (1 - costs.comm))


# ---------------------------------------------------------------- realistic generated universe

def generated(n=650):
    end = date(2025, 12, 31)
    market = synthetic.generate_ohlcv("MKT", "ARCX", 400.0, 0.16, end, n)
    secs = {}
    for t, beta, vol in (("S1", 1.2, 0.15), ("S2", 0.8, 0.12), ("S3", 1.0, 0.2), ("S4", 0.6, 0.12), ("S5", 1.1, 0.14)):
        rows = synthetic.generate_sector_ohlcv(t, "ARCX", market, beta, vol)
        secs[t] = {"sector": t, **{k: np.array([r[k] for r in rows], dtype=float) for k in ("open", "high", "low", "close", "volume")}}
    dates = [r["date"] for r in market]
    return dates, np.array([r["open"] for r in market]), np.array([r["close"] for r in market]), secs


@pytest.mark.parametrize("sid,p", [("quadrant_hold", {"hold": "improving_leading", "timeframe": "1m"}),
                                   ("top_score", {"n": 2, "every": 5, "timeframe": "1m"})])
def test_no_lookahead(sid, p):
    d, bo, bc, secs = generated()
    T = len(d) - 40
    full = RB.Universe(d, bo, bc, secs)
    cut = RB.Universe(d[:T], bo[:T], bc[:T], {t: {k: (v[:T] if k != "sector" else v) for k, v in s.items()} for t, s in secs.items()})
    a = RB.simulate(full, RB.STRATEGIES[sid], p, B.Costs(), 250, T)
    b = RB.simulate(cut, RB.STRATEGIES[sid], p, B.Costs(), 250, T)
    assert a.trades == b.trades and a.curve == b.curve


def test_walk_forward_holdout_isolation_and_disclosure(monkeypatch):
    d, bo, bc, secs = generated()
    u = RB.Universe(d, bo, bc, secs)
    windows = []
    real = RB.select

    def spy(u_, strat, costs, a, b, grid):
        windows.append((a, b))
        return real(u_, strat, costs, a, b, grid)
    monkeypatch.setattr(RB, "select", spy)
    out = RB.run(u, "quadrant_hold", "walk_forward", None, B.Costs(), holdout_pct=0.2, folds=2)
    hold_start = d.index(date.fromisoformat(out["periods"]["holdout_from"]))
    assert len(windows) == 3 and all(b <= hold_start for _, b in windows)
    assert out["combinations_tested"] == 6 * 3 and out["warmup_bars"] == RB.warmup_for(["1m", "3m"])
    assert out["holdout"]["start_date"] == out["periods"]["holdout_from"]
    for seg in (out["main"], out["holdout"]):
        assert {"buy_hold", "equal_weight", "time_in_sector_pct"} <= set(seg)
        assert len(seg["curve"]["equal_weight"]) == len(seg["curve"]["dates"])


def test_single_mode_reproducible_and_validation():
    d, bo, bc, secs = generated()
    a = RB.run(RB.Universe(d, bo, bc, secs), "top_score", "single", {"n": 3, "every": 10, "timeframe": "1m"}, B.Costs())
    b = RB.run(RB.Universe(d, bo, bc, secs), "top_score", "single", {"n": 3, "every": 10, "timeframe": "1m"}, B.Costs())
    assert a == b and a["combinations_tested"] == 1 and a["disclaimer"].startswith("Past performance")
    assert a["main"]["metrics"]["bars"] + a["holdout"]["metrics"]["bars"] == len(d) - a["warmup_bars"]
    u = RB.Universe(d, bo, bc, secs)
    for kw, msg in [({"strategy_id": "nope", "mode": "single", "params": None}, "unknown rotation"),
                    ({"strategy_id": "top_score", "mode": "single", "params": {"n": 4}}, "n must be"),
                    ({"strategy_id": "top_score", "mode": "walk_forward", "params": {"n": 2}}, "chooses parameters"),
                    ({"strategy_id": "top_score", "mode": "walk_forward", "params": None, "folds": 6}, "not enough history"),
                    ({"strategy_id": "top_score", "mode": "single", "params": None, "holdout_pct": 0.5}, "holdout")]:
        with pytest.raises(ValueError, match=msg):
            RB.run(u, costs=B.Costs(), **kw)
