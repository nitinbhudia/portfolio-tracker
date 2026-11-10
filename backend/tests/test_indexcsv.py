"""CSV formats from common finance sites (made-up values in each site's layout)."""
from datetime import date as D

import pytest

from app.engine import indexcsv as X

WANT = [(D(2026, 11, 5), 4726.81), (D(2026, 11, 6), 4730.5), (D(2026, 11, 9), 4801.0)]


@pytest.mark.parametrize("name,text", [
    ("Stooq", "Date,Open,High,Low,Close,Volume\n2026-11-05,1,1,1,4726.81,0\n2026-11-06,1,1,1,4730.5,0\n2026-11-09,1,1,1,4801,0\n"),
    ("FRED", "observation_date,RU2000\n2026-11-05,4726.81\n2026-11-06,4730.50\n2026-11-07,\n2026-11-09,4801.00\n"),
    ("Nasdaq.com", 'Date,Close/Last,Volume,Open,High,Low\n11/09/2026,"4,801.00",--,1,1,1\n11/06/2026,"4,730.50",--,1,1,1\n11/05/2026,"4,726.81",--,1,1,1\n'),
    ("Investing.com", '"Date","Price","Open","High","Low","Vol.","Change %"\n"11/09/2026","4,801.00","1","1","1","","1.49%"\n'
                      '"11/06/2026","4,730.50","1","1","1","","0.08%"\n"11/05/2026","4,726.81","1","1","1","","-0.1%"\n'),
    ("WSJ", "Date, Open, High, Low, Close\n11/09/26, 1, 1, 1, 4801.00\n11/06/26, 1, 1, 1, 4730.50\n11/05/26, 1, 1, 1, 4726.81\n"),
    ("Yahoo", 'Date,Open,High,Low,Close*,Adj Close**,Volume\n"Nov 9, 2026",1,1,1,"4,801.00","4,801.00",0\n'
              '"Nov 6, 2026",1,1,1,"4,730.50","4,730.50",0\n"Nov 5, 2026",1,1,1,"4,726.81","4,726.81",0\n'),
    ("European, day-first", "Datum;Schluss\n09.11.2026;4.801,00\n06.11.2026;4.730,50\n05.11.2026;4.726,81\n"),
    ("UK, day-first slashes", "Date,Close\n09/11/2026,4801\n06/11/2026,4730.5\n05/11/2026,4726.81\n"),
    ("Tab, named months", "Date\tClose\n5 Nov 2026\t4726.81\n6-Nov-26\t4730.5\n9 November 2026\t$4,801.00\n"),
    ("Compact", "Date,Close\n20261105,4726.81\n20261106,4730.5\n20261109,4801\n"),
    ("With times", "Date,Close\n2026-11-05 00:00:00,4726.81\n2026-11-06T00:00:00Z,4730.5\n2026/11/09,4801\n"),
])
def test_site_formats(name, text):
    assert X.parse(text) == WANT, name


def test_day_or_month_first_from_the_sequence():
    # all numbers ≤ 12: month-first (US) gives consecutive trading days; day-first would jump months
    us = "Date,Close\n11/03/2026,1\n11/04/2026,2\n11/05/2026,3\n11/06/2026,4\n11/09/2026,5\n11/10/2026,6\n"
    assert [d for d, _ in X.parse(us)][:2] == [D(2026, 11, 3), D(2026, 11, 4)]
    uk = "Date,Close\n03/11/2026,1\n04/11/2026,2\n05/11/2026,3\n06/11/2026,4\n09/11/2026,5\n10/11/2026,6\n"
    assert [d for d, _ in X.parse(uk)][:2] == [D(2026, 11, 3), D(2026, 11, 4)]
    with pytest.raises(X.CsvError, match="day-first"):
        X.parse("Date,Close\n03/04/2026,1\n")  # one row: can't tell, and doesn't guess


def test_numbers_and_errors():
    assert [X.number(s) for s in ("4,726.81", "4.726,81", "4726,81", "4,726", "$1,234.5", "£7.5", ".", "")] == \
        [4726.81, 4726.81, 4726.81, 4726.0, 1234.5, 7.5, None, None]
    with pytest.raises(X.CsvError, match="Couldn't find Date and Close"):
        X.parse("When,Value,Other\n2026-01-02,1,2\n")
    with pytest.raises(X.CsvError, match="no rows"):
        X.parse("Date,Close\n")
    with pytest.raises(X.CsvError, match="No rows with a readable date"):
        X.parse("Date,Close\nyesterday,5\n")
