"""Trading calendars.

Synthetic data uses a plain Mon–Fri calendar (documented simplification).
Real US data uses the NYSE/Nasdaq full-day holiday rules below, so ordinary
market holidays are not reported as "missing data".

Rules (NYSE): New Year's Day (Sunday -> Monday; a Saturday holiday is NOT moved to
Friday), MLK Day, Presidents' Day, Good Friday, Memorial Day, Juneteenth (from 2022),
Independence Day, Labor Day, Thanksgiving, Christmas (Sat -> Fri, Sun -> Mon), plus
special one-off closures listed in SPECIAL_CLOSURES.

Real European data (Phase 2b) uses the standard full-day closures below. They are built-in
rules, NOT yet checked against each exchange's official calendar; early closes are ignored.
  Xetra (XETR): New Year, Good Friday, Easter Monday, 1 May, 24/25/26/31 Dec.
  Euronext Amsterdam (XAMS) and Paris (XPAR): New Year, Good Friday, Easter Monday, 1 May, 25/26 Dec.
  SIX Swiss (XSWX): 1/2 Jan, Good Friday, Easter Monday, Ascension, Whit Monday, 1 May,
    1 Aug, 24/25/26/31 Dec.
  London (XLON): New Year (weekend -> next Monday), Good Friday, Easter Monday, first and last
    Monday of May, last Monday of August, Christmas and Boxing Day with weekend substitutes,
    plus the one-off bank-holiday changes in UK_SPECIAL.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from dateutil.easter import easter

import numpy as np
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay,
                                    USMartinLutherKingJr, USMemorialDay, USPresidentsDay,
                                    USThanksgivingDay, nearest_workday, sunday_to_monday)

US_MICS = {"XNAS", "XNYS", "ARCX", "XASE", "BATS"}

SPECIAL_CLOSURES = [
    date(2012, 10, 29), date(2012, 10, 30),  # Hurricane Sandy
    date(2018, 12, 5),                        # President G.H.W. Bush
    date(2025, 1, 9),                         # President Carter
]


class _NYSE(AbstractHolidayCalendar):
    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=1)
def us_holidays() -> np.ndarray:
    hol = {d.date() for d in _NYSE().holidays(start="1990-01-01", end="2035-12-31")}
    hol |= set(SPECIAL_CLOSURES)
    # nearest_workday would move a Saturday New Year to Friday Dec 31; NYSE does not close then.
    hol = {d for d in hol if not (d.month == 12 and d.day == 31)}
    return np.array(sorted(hol), dtype="datetime64[D]")


EU_MICS = {"XETR", "XAMS", "XSWX", "XLON", "XPAR"}
YEARS = range(1990, 2036)

# One-off UK bank-holiday changes: (dates added, dates removed)
UK_SPECIAL = {
    1999: ([date(1999, 12, 31)], []),
    2002: ([date(2002, 6, 3), date(2002, 6, 4)], [date(2002, 5, 27)]),
    2011: ([date(2011, 4, 29)], []),
    2012: ([date(2012, 6, 4), date(2012, 6, 5)], [date(2012, 5, 28)]),
    2020: ([date(2020, 5, 8)], [date(2020, 5, 4)]),
    2022: ([date(2022, 6, 2), date(2022, 6, 3), date(2022, 9, 19)], [date(2022, 5, 30)]),
    2023: ([date(2023, 5, 8)], []),
}


def _weekday_of_month(y: int, m: int, weekday: int, last: bool = False) -> date:
    if last:
        d = (date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() - weekday) % 7)
    d = date(y, m, 1)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def _next_monday_if_weekend(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7) if d.weekday() >= 5 else d


def _eu_year(mic: str, y: int) -> set[date]:
    e = easter(y)
    good_friday, easter_monday = e - timedelta(days=2), e + timedelta(days=1)
    if mic == "XETR":
        return {date(y, 1, 1), good_friday, easter_monday, date(y, 5, 1),
                date(y, 12, 24), date(y, 12, 25), date(y, 12, 26), date(y, 12, 31)}
    if mic in ("XAMS", "XPAR"):  # Euronext markets share one holiday calendar
        return {date(y, 1, 1), good_friday, easter_monday, date(y, 5, 1), date(y, 12, 25), date(y, 12, 26)}
    if mic == "XSWX":
        return {date(y, 1, 1), date(y, 1, 2), good_friday, easter_monday, e + timedelta(days=39),
                e + timedelta(days=50), date(y, 5, 1), date(y, 8, 1),
                date(y, 12, 24), date(y, 12, 25), date(y, 12, 26), date(y, 12, 31)}
    if mic == "XLON":
        out = {_next_monday_if_weekend(date(y, 1, 1)), good_friday, easter_monday,
               _weekday_of_month(y, 5, 0), _weekday_of_month(y, 5, 0, last=True),
               _weekday_of_month(y, 8, 0, last=True)}
        xmas = date(y, 12, 25)
        if xmas.weekday() == 5:      # Sat: Mon 27 + Tue 28
            out |= {date(y, 12, 27), date(y, 12, 28)}
        elif xmas.weekday() == 6:    # Sun: Boxing Mon 26 + Christmas Tue 27
            out |= {date(y, 12, 26), date(y, 12, 27)}
        elif xmas.weekday() == 4:    # Fri: Boxing Day Sat -> Mon 28
            out |= {xmas, date(y, 12, 28)}
        else:
            out |= {xmas, date(y, 12, 26)}
        added, removed = UK_SPECIAL.get(y, ([], []))
        return (out - set(removed)) | set(added)
    raise ValueError(mic)


@lru_cache(maxsize=8)
def eu_holidays(mic: str) -> np.ndarray:
    hol = set().union(*(_eu_year(mic, y) for y in YEARS))
    return np.array(sorted(d for d in hol if d.weekday() < 5), dtype="datetime64[D]")


def holidays_for(exchange_mic: str, namespace: str) -> np.ndarray:
    if namespace == "real" and exchange_mic in US_MICS:
        return us_holidays()
    if namespace == "real" and exchange_mic in EU_MICS:
        return eu_holidays(exchange_mic)
    return np.array([], dtype="datetime64[D]")
