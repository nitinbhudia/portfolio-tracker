"""Weekly / monthly bars and analysis (PHASE_2B_TASK.md §4)."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from research.core.calendars import eu_holidays
from research.engine import resample as R
from research.services import analysis as an


def daily(days, start=100.0):
    n = len(days)
    c = start + np.arange(n, dtype=float)
    return pd.DataFrame({"date": days, "open": c - 0.5, "high": c + 1, "low": c - 1, "close": c,
                         "volume": np.full(n, 10.0), "source": "t", "is_synthetic": False,
                         "is_delayed": False, "delay_minutes": 0, "adjustment": "none"})


def bdays(a: date, b: date, hol=R.NO_HOLIDAYS):
    out, d = [], a
    while d <= b:
        if np.is_busday(np.datetime64(d, "D"), holidays=hol):
            out.append(d)
        d += timedelta(days=1)
    return out


def test_weekly_ohlcv_and_dates():
    days = bdays(date(2025, 3, 3), date(2025, 3, 14))  # two full Mon-Fri weeks
    w, meta = R.resample(daily(days), "1w")
    assert len(w) == 2 and meta["last_bar_in_progress"] is False
    first = w.iloc[0]
    assert first["date"] == date(2025, 3, 7) and first["period_start"] == date(2025, 3, 3)
    assert (first["open"], first["high"], first["low"], first["close"], first["volume"]) == (99.5, 105.0, 99.0, 104.0, 50.0)


def test_holiday_week_uses_trading_calendar():
    hol = eu_holidays("XETR")
    days = bdays(date(2025, 4, 14), date(2025, 4, 25), hol)  # Good Friday 18th + Easter Monday 21st closed
    w, meta = R.resample(daily(days), "1w", hol)
    assert list(w["trading_days"]) == [4, 4]
    assert w.iloc[0]["date"] == date(2025, 4, 17)  # dated by last trading day (Thursday)
    assert meta["last_bar_in_progress"] is False


def test_partial_last_period_is_flagged():
    days = bdays(date(2025, 3, 3), date(2025, 3, 12))  # ends on a Wednesday
    _, meta = R.resample(daily(days), "1w")
    assert meta["last_bar_in_progress"] is True and meta["last_period_trading_days"] == 3
    m_days = bdays(date(2025, 1, 2), date(2025, 2, 28))
    m, mm = R.resample(daily(m_days), "1mo")
    assert len(m) == 2 and mm["last_bar_in_progress"] is False
    assert m.iloc[0]["date"] == date(2025, 1, 31)


def test_month_end_on_holiday_counts_as_complete():
    hol = eu_holidays("XETR")  # 31 Dec closed on Xetra
    days = bdays(date(2025, 12, 1), date(2025, 12, 30), hol)
    _, meta = R.resample(daily(days), "1mo", hol)
    assert meta["last_bar_in_progress"] is False


def test_missing_volume_stays_missing():
    df = daily(bdays(date(2025, 3, 3), date(2025, 3, 7)))
    df["volume"] = np.nan
    w, _ = R.resample(df, "1w")
    assert np.isnan(w.iloc[0]["volume"])


def test_bad_interval():
    with pytest.raises(ValueError):
        R.resample(daily([date(2025, 1, 2)]), "1h")


# ---------------------------------------------------------------- analysis API

def _lid(client, ticker="AAPL"):
    return next(x["id"] for x in client.get("/api/listings").json()["listings"] if x["ticker"] == ticker)


@pytest.mark.parametrize("interval,max_bars", [("1w", 130), ("1mo", 30)])
def test_weekly_monthly_analysis(client, interval, max_bars):
    lid = _lid(client)
    a = client.get(f"/api/listings/{lid}/analysis?interval={interval}").json()
    d = client.get(f"/api/listings/{lid}/analysis").json()
    assert a["status"] == "ok" and a["interval"] == interval and a["timeframe"]["interval"] == interval
    assert a["bars_available"] < max_bars < d["bars_available"]
    assert a["params_hash"] != d["params_hash"] and a["input_hash"] != d["input_hash"]
    assert a["provenance"] == d["provenance"]  # provenance is the daily data's
    # Fibonacci comes from weekly/monthly swings, not daily ones
    if a["fibonacci"]["status"] == "ok" and d["fibonacci"]["status"] == "ok":
        assert a["fibonacci"]["swing_high"]["date"] != d["fibonacci"]["swing_high"]["date"] or \
            a["fibonacci"]["swing_low"]["date"] != d["fibonacci"]["swing_low"]["date"]
    # SMA 200 on ~120 weekly bars is honestly missing
    assert a["latest"]["indicators"]["sma200"]["data_quality"] == "insufficient_history"
    assert len(a["series"]["dates"]) == a["bars_available"]


def test_synthetic_last_week_in_progress(client):
    a = client.get(f"/api/listings/{_lid(client)}/analysis?interval=1w").json()
    # synthetic data ends Wed 2025-12-31; that ISO week runs to Fri 2026-01-02
    assert a["as_of"] == "2025-12-31" and a["timeframe"]["last_bar_in_progress"] is True


def test_no_lookahead_weekly(client):
    lid = _lid(client, "MSFT")
    full = client.get(f"/api/listings/{lid}/analysis?interval=1w&as_of=2025-10-15").json()
    with client.Session() as db:
        bars = an.load_bars(db, lid, date(2025, 10, 15))
        rs, meta = R.resample(bars.df, "1w")
        direct = an.compute_analysis(an.Bars(bars.listing, rs), "medium", interval="1w", daily_df=bars.df, timeframe=meta)
    assert full["scores"] == direct["scores"] and full["fibonacci"] == direct["fibonacci"]
    assert full["as_of"] == "2025-10-15" and full["timeframe"]["last_bar_in_progress"] is True


def test_nesn_gap_reported_on_weekly(client):
    a = client.get(f"/api/listings/{_lid(client, 'NESN')}/analysis?interval=1w").json()
    assert a["data_quality"]["gaps"]  # the daily gap is still shown


def test_bad_interval_400(client):
    assert client.get(f"/api/listings/{_lid(client)}/analysis?interval=4h").status_code == 400
