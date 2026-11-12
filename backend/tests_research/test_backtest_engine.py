"""Backtest engine (PHASE_7_TASK.md §7.1-7.5)."""
from datetime import date, timedelta

import numpy as np
import pytest

from research.engine import backtest as B

N = 400


def days(n=N):
    out, d = [], date(2020, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def flat_ctx(n=N, price=100.0):
    c = np.full(n, price)
    return B.Context(days(n), c, c + 1, c - 1, c, np.full(n, 1000.0))


class Scripted(B.Strategy):
    """Enters at the close of bar `enter_at` (fills next open), exits at the close of `exit_at`."""
    id = "scripted"

    def __init__(self, enter_at, exit_at=None, stop=None, target=None):
        self.enter_at, self.exit_at, self.stop, self.target = enter_at, exit_at, stop, target

    def entry(self, ctx, t, p):
        return B.Signal(stop=self.stop, target=self.target) if t == self.enter_at else None

    def exit(self, ctx, t, p, held):
        return t == self.exit_at


ZERO = B.Costs(0, 0)


# ---------------------------------------------------------------- fills and costs

def test_next_open_fill_and_round_trip_costs():
    ctx = flat_ctx()
    ctx.o[211], ctx.o[221] = 100.0, 110.0
    costs = B.Costs(commission_bps=5, slippage_bps=10)
    r = B.simulate(ctx, Scripted(210, 220), {}, costs, 200, 300)
    (t,) = r.trades
    assert t["entry_date"] == ctx.dates[211].isoformat() and t["exit_date"] == ctx.dates[221].isoformat()
    assert t["entry_price"] == pytest.approx(100 * 1.001) and t["exit_price"] == pytest.approx(110 * 0.999)
    expected = (1 - 0.0005) / (100 * 1.001) * (110 * 0.999) * (1 - 0.0005)
    assert r.curve[-1] == pytest.approx(expected) and t["return_pct"] == pytest.approx((expected - 1) * 100)
    assert sum(r.invested) == 10  # bars 211..220 held at the close


def test_no_entry_without_a_next_bar_and_open_position_closed_at_end():
    ctx = flat_ctx()
    assert B.simulate(ctx, Scripted(299), {}, ZERO, 200, 300).trades == []  # decided on the last bar: can't execute
    r = B.simulate(ctx, Scripted(250), {}, ZERO, 200, 300)
    assert r.trades[-1]["exit_reason"] == "end of period" and r.trades[-1]["open_at_end"] is True


def test_gap_through_stop_fills_at_open_and_stop_beats_target():
    ctx = flat_ctx()
    ctx.o[212], ctx.h[212], ctx.l[212], ctx.c[212] = 90.0, 91.0, 89.0, 90.0  # gap below the 95 stop
    r = B.simulate(ctx, Scripted(210, stop=95.0, target=120.0), {}, ZERO, 200, 300)
    assert r.trades[0]["exit_reason"] == "stop" and r.trades[0]["exit_price"] == 90.0
    ctx2 = flat_ctx()
    ctx2.h[213], ctx2.l[213] = 125.0, 94.0  # touches both in one bar
    r2 = B.simulate(ctx2, Scripted(210, stop=95.0, target=120.0), {}, ZERO, 200, 300)
    assert r2.trades[0]["exit_reason"] == "stop" and r2.trades[0]["exit_price"] == 95.0
    ctx3 = flat_ctx()
    ctx3.h[213] = 121.0
    r3 = B.simulate(ctx3, Scripted(210, stop=95.0, target=120.0), {}, ZERO, 200, 300)
    assert r3.trades[0]["exit_reason"] == "target" and r3.trades[0]["exit_price"] == 120.0


# ---------------------------------------------------------------- metrics

def test_metrics_by_hand():
    m = B.metrics([1.1, 0.99, 1.2], [True, True, False], [{"return_pct": 10.0, "bars_held": 2}, {"return_pct": -5.0, "bars_held": 4}])
    assert m["total_return_pct"] == pytest.approx(20.0)
    assert m["max_drawdown_pct"] == pytest.approx((1.1 - 0.99) / 1.1 * 100)
    assert m["win_rate_pct"] == 50.0 and m["avg_trade_pct"] == 2.5 and m["avg_bars_held"] == 3.0
    assert m["exposure_pct"] == pytest.approx(200 / 3)
    rets = np.array([0.1, 0.99 / 1.1 - 1, 1.2 / 0.99 - 1])
    assert m["sharpe_like"] == pytest.approx(rets.mean() / rets.std(ddof=1) * np.sqrt(252))
    assert m["cagr_pct"] == pytest.approx((1.2 ** (252 / 3) - 1) * 100)
    flat = B.metrics([1.0, 1.0], [False, False], [])
    assert flat["sharpe_like"] is None and flat["win_rate_pct"] is None and flat["max_drawdown_pct"] == 0.0


def test_buy_and_hold_with_costs():
    ctx = flat_ctx()
    ctx.o[200], ctx.c[299] = 100.0, 150.0
    bh = B.buy_and_hold(ctx, B.Costs(5, 10), 200, 300)
    expected = (1 - 0.0005) / (100 * 1.001) * 150 * 0.999 * (1 - 0.0005)
    assert bh.curve[-1] == pytest.approx(expected)


# ---------------------------------------------------------------- strategies

def _series(n, tail, fill):
    a = np.full(n, fill, dtype=float)
    a[n - len(tail):] = tail
    return a


def test_ma_cross_rules():
    ctx = flat_ctx(300)
    ctx.ind["sma50"] = _series(300, [99, 101, 101, 99], 99.0)
    ctx.ind["sma200"] = np.full(300, 100.0)
    s = B.STRATEGIES["ma_cross"]
    p = {"fast": 50, "slow": 200}
    assert s.entry(ctx, 297, p) is not None and s.entry(ctx, 298, p) is None
    assert s.exit(ctx, 299, p, 2) and not s.exit(ctx, 298, p, 1)
    assert all(q["fast"] < q["slow"] for q in s.grid()) and len(s.grid()) == 8


def test_rsi_reversion_rules():
    ctx = flat_ctx(300)
    ctx.ind["rsi14"] = _series(300, [28, 45, 55], 40.0)
    s, p = B.STRATEGIES["rsi_reversion"], {"entry": 30, "exit": 50}
    assert s.entry(ctx, 297, p) is not None and s.entry(ctx, 298, p) is None
    assert s.exit(ctx, 299, p, 2) and not s.exit(ctx, 298, p, 1)
    assert s.exit(ctx, 298, p, B.RSI_MAX_HOLD)  # time stop
    assert len(s.grid()) == 9


def test_macd_cross_trend_filter():
    ctx = flat_ctx(300)
    ctx.ind["macd_line"] = _series(300, [-0.1, 0.1], 0.0)
    ctx.ind["macd_signal"] = np.zeros(300)
    ctx.ind["sma200"] = np.full(300, 105.0)  # close 100 is below SMA 200
    s = B.STRATEGIES["macd_cross"]
    assert s.entry(ctx, 299, {"trend_filter": False}) is not None
    assert s.entry(ctx, 299, {"trend_filter": True}) is None


def test_setup_hold_exits_after_hold():
    s = B.STRATEGIES["setup_hold"]
    assert s.exit(None, 0, {"hold": 5, "setup": "bullish_ma"}, 5) and not s.exit(None, 0, {"hold": 5, "setup": "bullish_ma"}, 4)
    assert set(s.params["setup"]["choices"]) == {"bullish_reversal", "fib_support", "breakout", "bullish_ma", "momentum_up", "accumulation"}


def test_fib_pullback_trades_respect_stop_and_target(aapl):
    ctx = B.Context(days(len(aapl["close"])), aapl["open"], aapl["high"], aapl["low"], aapl["close"], aapl["volume"])
    s = B.STRATEGIES["fib_pullback"]
    hits = []
    for p in s.grid():
        r = B.simulate(ctx, s, p, ZERO, 200, ctx.n)
        hits += r.trades
        for t in r.trades:
            assert t["exit_reason"] in ("stop", "target", "end of period")
    assert hits, "expected at least one Fibonacci pullback trade in 400 synthetic bars"


# ---------------------------------------------------------------- no look-ahead

@pytest.mark.parametrize("sid", list(B.STRATEGIES))
def test_no_lookahead(aapl, sid):
    n = len(aapl["close"])
    T = n - 60
    full = B.Context(days(n), *(aapl[k] for k in ("open", "high", "low", "close", "volume")))
    cut = B.Context(days(n)[:T], *(aapl[k][:T] for k in ("open", "high", "low", "close", "volume")))
    strat = B.STRATEGIES[sid]
    for p in strat.grid()[:4]:
        a = B.simulate(full, strat, p, B.Costs(), 200, T)
        b = B.simulate(cut, strat, p, B.Costs(), 200, T)
        assert a.trades == b.trades and a.curve == b.curve


# ---------------------------------------------------------------- validation

def aapl_ctx(aapl):
    return B.Context(days(len(aapl["close"])), *(aapl[k] for k in ("open", "high", "low", "close", "volume")))


def test_walk_forward_never_selects_on_holdout(aapl, monkeypatch):
    ctx = aapl_ctx(aapl)
    windows = []
    real_select = B.select

    def spy(ctx_, strat, costs, a, b):
        windows.append((a, b))
        return real_select(ctx_, strat, costs, a, b)
    monkeypatch.setattr(B, "select", spy)
    out = B.run(ctx, "ma_cross", "walk_forward", None, B.Costs(), holdout_pct=0.2, folds=2)
    _, hold = B.split(ctx.n, 0.2)
    assert len(windows) == 3 and all(b <= hold for _, b in windows)  # 2 folds + final selection
    assert out["combinations_tested"] == 8 * 3 and len(out["folds"]) == 2
    assert out["holdout"]["start_date"] == ctx.dates[hold].isoformat()
    for f in out["folds"]:
        assert f["test"][0] > f["train"][1]  # test always after training


def test_single_mode_and_determinism(aapl):
    ctx = aapl_ctx(aapl)
    a = B.run(ctx, "rsi_reversion", "single", {"entry": 35, "exit": 60}, B.Costs())
    b = B.run(aapl_ctx(aapl), "rsi_reversion", "single", {"entry": 35, "exit": 60}, B.Costs())
    assert a == b and a["combinations_tested"] == 1 and a["disclaimer"] == B.DISCLAIMER
    assert a["main"]["end_date"] < a["holdout"]["start_date"]
    assert a["main"]["metrics"]["bars"] + a["holdout"]["metrics"]["bars"] == ctx.n - B.WARMUP
    assert len(a["main"]["curve"]["dates"]) == len(a["main"]["curve"]["strategy"]) == len(a["main"]["curve"]["buy_hold"])


@pytest.mark.parametrize("kwargs,msg", [
    ({"strategy_id": "nope", "mode": "single", "params": None}, "unknown strategy"),
    ({"strategy_id": "ma_cross", "mode": "yolo", "params": None}, "mode"),
    ({"strategy_id": "ma_cross", "mode": "single", "params": {"fast": 13}}, "fast must be"),
    ({"strategy_id": "ma_cross", "mode": "single", "params": {"fast": 50, "slow": 50}}, "invalid parameter combination"),
    ({"strategy_id": "ma_cross", "mode": "single", "params": {"x": 1}}, "unknown parameter"),
    ({"strategy_id": "ma_cross", "mode": "walk_forward", "params": {"fast": 10}}, "chooses parameters"),
    ({"strategy_id": "ma_cross", "mode": "walk_forward", "params": None, "folds": 9}, "folds"),
    ({"strategy_id": "ma_cross", "mode": "single", "params": None, "holdout_pct": 0.05}, "holdout"),
])
def test_bad_requests(aapl, kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        B.run(aapl_ctx(aapl), costs=B.Costs(), **kwargs)


def test_too_little_history():
    with pytest.raises(ValueError, match="needs at least"):
        B.run(flat_ctx(250), "ma_cross", "single", None, B.Costs())
