"""European exchange holiday rules (PHASE_2B_TASK.md §2)."""
from datetime import date

import numpy as np
import pytest

from research.core.calendars import eu_holidays, holidays_for
from research.services.analysis import find_gaps


def _hol(mic):
    return {d.astype(object) for d in eu_holidays(mic)}


@pytest.mark.parametrize("mic,day", [
    ("XETR", date(2025, 4, 18)), ("XETR", date(2025, 4, 21)), ("XETR", date(2025, 5, 1)),
    ("XETR", date(2025, 12, 24)), ("XETR", date(2025, 12, 31)),
    ("XAMS", date(2025, 4, 18)), ("XAMS", date(2025, 12, 26)), ("XAMS", date(2026, 1, 1)),
    ("XSWX", date(2025, 1, 2)), ("XSWX", date(2025, 5, 29)), ("XSWX", date(2025, 6, 9)), ("XSWX", date(2025, 8, 1)),
    ("XLON", date(2025, 5, 5)), ("XLON", date(2025, 5, 26)), ("XLON", date(2025, 8, 25)),
    ("XLON", date(2022, 6, 3)), ("XLON", date(2022, 9, 19)), ("XLON", date(2023, 5, 8)),
    ("XLON", date(2021, 12, 27)), ("XLON", date(2021, 12, 28)),  # Christmas on Saturday
    ("XLON", date(2022, 1, 3)),                                   # New Year on Saturday
])
def test_known_closures(mic, day):
    assert day in _hol(mic)


@pytest.mark.parametrize("mic,day", [
    ("XAMS", date(2025, 12, 24)),  # Euronext open (early close) on Christmas Eve
    ("XETR", date(2025, 6, 9)),    # Whit Monday: Xetra trades
    ("XLON", date(2025, 5, 1)),    # LSE trades on 1 May
    ("XLON", date(2022, 5, 30)),   # 2022 spring bank holiday moved to 2 June
    ("XSWX", date(2025, 4, 22)),
])
def test_trading_days_not_marked(mic, day):
    assert day not in _hol(mic)


def test_no_weekends_and_synthetic_unchanged():
    for mic in ("XETR", "XAMS", "XSWX", "XLON"):
        assert all(d.astype(object).weekday() < 5 for d in eu_holidays(mic))
    assert len(holidays_for("XETR", "synthetic")) == 0


def test_holiday_is_not_a_gap_but_a_real_gap_is():
    hol = holidays_for("XETR", "real")
    days = [date(2025, 4, 16), date(2025, 4, 17), date(2025, 4, 22), date(2025, 4, 23)]  # Easter skipped
    assert find_gaps(days, hol) == []
    days2 = [date(2025, 4, 22), date(2025, 4, 25)]  # 23rd and 24th really missing
    assert find_gaps(days2, hol) == [{"after": "2025-04-22", "before": "2025-04-25", "missing_business_days": 2}]
