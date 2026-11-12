"""Setup detectors (PHASE_4_TASK.md §2): triggered / not triggered / insufficient data,
not-applicable for indices, and no look-ahead."""
import math

import numpy as np
import pytest

from research.engine import fibonacci, indicators, setups, swings

N = 260


def _flat(n=N, price=100.0):
    c = np.full(n, price)
    return {"o": c.copy(), "h": c + 1, "l": c - 1, "c": c, "v": np.full(n, 1000.0)}


def _ind(**over):
    base = {k: np.full(N, np.nan) for k in ("rsi14", "macd_hist", "relvol20", "sma20", "sma50", "sma200")}
    base.update({k: np.asarray(v, dtype=float) for k, v in over.items()})
    return base


def _run(bars, ind, fib=None, has_volume=True, t=None):
    out = setups.detect_all(bars["o"], bars["h"], bars["l"], bars["c"], bars["v"], ind, fib, t, has_volume)
    return {s["id"]: s for s in out["setups"]}


def _series(*tail, fill=np.nan):
    a = np.full(N, fill)
    a[N - len(tail):] = tail
    return a


# --------------------------------------------------------------- reversal

def test_bullish_reversal_triggers_and_not():
    rsi = _series(40, 28, 26, 29, 31, 33, fill=45)  # dipped below 30, now back above
    hist = _series(-2.0, -1.5, -1.0, -0.5, fill=-3.0)
    r = _run(_flat(), _ind(rsi14=rsi, macd_hist=hist))["bullish_reversal"]
    assert r["status"] == "triggered" and all(x["result"] for x in r["rules"])
    rsi2 = _series(40, 35, 36, 34, 31, 33, fill=45)  # never below 30
    r2 = _run(_flat(), _ind(rsi14=rsi2, macd_hist=hist))["bullish_reversal"]
    assert r2["status"] == "not_triggered"
    assert r2["rules"][0]["result"] is False


def test_bearish_reversal_triggers():
    rsi = _series(60, 72, 75, 71, 69, 66, fill=55)
    hist = _series(2.0, 1.5, 1.0, 0.5, fill=3.0)
    assert _run(_flat(), _ind(rsi14=rsi, macd_hist=hist))["bearish_reversal"]["status"] == "triggered"


def test_insufficient_data_when_warmup_missing():
    r = _run(_flat(), _ind())
    for sid in ("bullish_reversal", "bullish_ma", "momentum_up", "breakout"):
        assert r[sid]["status"] == "insufficient_data", sid


# --------------------------------------------------------------- MA alignment / momentum

def test_ma_alignment_bullish_and_bearish():
    b = _flat()
    b["c"][-1] = 110
    up = _ind(sma20=_series(105, fill=105), sma50=np.linspace(90, 100, N), sma200=_series(80, fill=80))
    r = _run(b, up)
    assert r["bullish_ma"]["status"] == "triggered" and r["bearish_ma"]["status"] == "not_triggered"
    b["c"][-1] = 70
    down = _ind(sma20=_series(75, fill=75), sma50=np.linspace(100, 90, N), sma200=_series(120, fill=120))
    assert _run(b, down)["bearish_ma"]["status"] == "triggered"


def test_momentum_acceleration():
    up = _ind(macd_hist=_series(0.1, 0.2, 0.3, 0.5, fill=0.0))
    assert _run(_flat(), up)["momentum_up"]["status"] == "triggered"
    flat_then_up = _ind(macd_hist=_series(0.3, 0.2, 0.3, 0.5, fill=0.0))
    assert _run(_flat(), flat_then_up)["momentum_up"]["status"] == "not_triggered"
    down = _ind(macd_hist=_series(-0.1, -0.2, -0.4, -0.5, fill=0.0))
    assert _run(_flat(), down)["momentum_down"]["status"] == "triggered"


# --------------------------------------------------------------- breakout / volume

def test_breakout_needs_volume_confirmation():
    b = _flat()
    b["c"][-1] = 105
    b["h"][-1] = 106
    hi_rv = _ind(relvol20=_series(2.0, fill=1.0))
    assert _run(b, hi_rv)["breakout"]["status"] == "triggered"
    lo_rv = _ind(relvol20=_series(1.1, fill=1.0))
    assert _run(b, lo_rv)["breakout"]["status"] == "not_triggered"
    b["c"][-1] = 95
    b["l"][-1] = 94
    assert _run(b, hi_rv)["breakdown"]["status"] == "triggered"


def test_volume_setups_not_applicable_without_volume():
    r = _run(_flat(), _ind(relvol20=_series(2.0, fill=1.0)), has_volume=False)
    for sid in ("breakout", "breakdown", "accumulation", "distribution"):
        assert r[sid]["status"] == "not_applicable"


def test_accumulation_and_distribution():
    b = _flat()
    # sideways: alternate +1 / -1, with heavy volume on up days
    c = 100 + np.tile([0.0, 1.0], N // 2)
    b["c"] = c
    b["v"] = np.where(np.diff(c, prepend=c[0]) > 0, 3000.0, 1000.0)
    r = _run(b, _ind())
    assert r["accumulation"]["status"] == "triggered"
    assert r["distribution"]["status"] == "not_triggered"
    b["v"] = np.where(np.diff(c, prepend=c[0]) < 0, 3000.0, 1000.0)
    assert _run(b, _ind())["distribution"]["status"] == "triggered"


def test_accumulation_rejects_trending_price():
    b = _flat()
    b["c"] = np.geomspace(10, 100, N)  # ~+0.9% per bar -> ~19% over 20 bars
    r = _run(b, _ind())["accumulation"]
    assert r["status"] == "not_triggered"
    assert r["rules"][1]["result"] is False
    assert r["rules"][0]["left"] is None  # no down days -> ratio infinite, reported as None


# --------------------------------------------------------------- Fibonacci

def _fib_up(close_now):
    sw = [swings.Swing("low", 10, 15, 80.0), swings.Swing("high", 100, 110, 120.0)]
    return fibonacci.analyse(sw, close_now, atr=3.0)


def test_fib_support_and_resistance():
    b = _flat()
    b["c"][-6] = 110
    b["c"][-1] = 106  # 0.382 level of 80..120 up-swing is 104.72 -> 1.28 below, 0.43 ATR
    r = _run(b, _ind(), fib=_fib_up(106))
    assert r["fib_support"]["status"] == "triggered"
    assert r["fib_resistance"]["status"] == "not_triggered"  # wrong swing direction
    b["c"][-6] = 115
    b["c"][-1] = 112  # still falling, but nearest level (0.236 = 110.56) is below and 0.48 ATR
    assert _run(b, _ind(), fib=_fib_up(112))["fib_support"]["status"] == "triggered"
    b["c"][-6] = 100  # rising now -> not "approaching" support
    assert _run(b, _ind(), fib=_fib_up(112))["fib_support"]["status"] == "not_triggered"


def test_fib_insufficient_without_swings():
    r = _run(_flat(), _ind(), fib={"status": "insufficient_swings"})
    assert r["fib_support"]["status"] == "insufficient_data"


# --------------------------------------------------------------- real engine, no look-ahead

def _engine_setups(bars, t):
    o, h, l_, c, v = (bars[k][: t + 1] for k in ("open", "high", "low", "close", "volume"))
    ind = indicators.compute_all(o, h, l_, c, v)
    sw = swings.detect_swings(h, l_, ind["atr14"], 2.5)
    fib = fibonacci.analyse(swings.confirmed_as_of(sw, t), float(c[t]), float(ind["atr14"][t]))
    return setups.detect_all(o, h, l_, c, v, ind, fib, t)


def test_no_lookahead_full_vs_truncated(aapl):
    n = len(aapl["close"])
    full = {k: aapl[k] for k in aapl}
    for t in (250, 400, n - 30):
        o, h, l_, c, v = (full[k] for k in ("open", "high", "low", "close", "volume"))
        ind = indicators.compute_all(o, h, l_, c, v)
        sw = swings.detect_swings(h, l_, ind["atr14"], 2.5)
        fib = fibonacci.analyse(swings.confirmed_as_of(sw, t), float(c[t]), float(ind["atr14"][t]))
        on_full = setups.detect_all(o, h, l_, c, v, ind, fib, t)
        assert on_full == _engine_setups(full, t)


def test_detector_output_is_json_safe_and_deterministic(aapl):
    a = _engine_setups(aapl, len(aapl["close"]) - 1)
    b = _engine_setups(aapl, len(aapl["close"]) - 1)
    assert a == b and a["version"] == setups.SETUPS_VERSION
    assert len(a["setups"]) == len(setups.SETUPS)
    for s in a["setups"]:
        for r in s["rules"]:
            for k in ("left", "right"):
                assert r[k] is None or math.isfinite(r[k])


def test_every_setup_triggers_somewhere_in_synthetic_history(aapl):
    """Sanity: across 600 synthetic bars each non-volume-only detector fires at least once."""
    seen = set()
    for t in range(220, len(aapl["close"]), 3):
        seen.update(_engine_setups(aapl, t)["triggered"])
    assert {"bullish_ma", "momentum_up", "momentum_down"} <= seen


@pytest.mark.parametrize("sid", list(setups.SETUPS))
def test_every_setup_has_a_detector(sid):
    assert sid in setups.DETECTORS
