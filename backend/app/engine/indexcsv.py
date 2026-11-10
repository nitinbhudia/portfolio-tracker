"""Read daily index history from the CSV files finance sites let you download.

Accepted:
- separators: comma, semicolon or tab;
- date column: Date, Data, Datum, observation_date (FRED), Time;
- value column: Close, Close/Last (Nasdaq.com), Adj Close, Close*, Price (Investing.com), Last, Schluss, Zamkniecie,
  or the only other column (FRED names it after the series);
- dates: 2026-11-09, 2026/11/09, 2026.11.09, 20261109, 11/09/2026, 09/11/2026, 09.11.2026, 11-09-26,
  Nov 09, 2026, November 9 2026, 9 Nov 2026, 9-Nov-26, with or without a time;
- numbers: 4726.81, "4,726.81", $4,726.81, 4.726,81 / 4726,81 (decimal comma), blanks and "." skipped.

Day-first vs month-first (09/11 vs 11/09) is decided for the whole file: a first number above 12 means day-first, a
second number above 12 means month-first; otherwise the order that gives a tidy run of trading days (sorted, gaps of
a few days) wins, and if both are equally tidy the file is refused with a message instead of guessing.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_COLS = ("date", "data", "datum", "observation_date", "time", "trade date")
VALUE_COLS = ("close", "close/last", "adj close", "adj. close", "close price", "price", "last", "schluss", "schlusskurs",
              "zamkniecie", "value")

ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?$")
COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
NUMERIC = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})(?:[ T].*)?$")
NAMED_MDY = re.compile(r"^([A-Za-z]{3,9})\.?[\s-]+(\d{1,2}),?[\s-]+(\d{2}|\d{4})$")
NAMED_DMY = re.compile(r"^(\d{1,2})[\s-]+([A-Za-z]{3,9})\.?,?[\s-]+(\d{2}|\d{4})$")


class CsvError(ValueError):
    pass


def _year(y: str) -> int:
    n = int(y)
    return n if len(y) == 4 else (2000 + n if n < 70 else 1900 + n)


def _month(name: str) -> int | None:
    return MONTHS.get(name[:3].lower())


def _clean_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.replace("*", "").replace('"', "").strip().lower())


def number(s: str) -> float | None:
    s = (s or "").strip().strip('"').replace(" ", "").replace(" ", "")
    s = re.sub(r"[$£€]", "", s)
    if s in ("", ".", "-", "null", "N/A", "n/a"):
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_dates(raw: list[str]) -> list[date | None]:
    """Parse a whole column, choosing day-first or month-first once for the file."""
    out: list[date | None] = [None] * len(raw)
    ambiguous: list[tuple[int, int, int, int]] = []  # (row, a, b, year)
    for i, s in enumerate(raw):
        s = (s or "").strip().strip('"')
        try:
            if m := ISO.match(s):
                out[i] = date(int(m[1]), int(m[2]), int(m[3]))
            elif m := COMPACT.match(s):
                out[i] = date(int(m[1]), int(m[2]), int(m[3]))
            elif m := NUMERIC.match(s):
                ambiguous.append((i, int(m[1]), int(m[2]), _year(m[3])))
            elif (m := NAMED_MDY.match(s)) and _month(m[1]):
                out[i] = date(_year(m[3]), _month(m[1]), int(m[2]))
            elif (m := NAMED_DMY.match(s)) and _month(m[2]):
                out[i] = date(_year(m[3]), _month(m[2]), int(m[1]))
        except ValueError:
            out[i] = None
    if not ambiguous:
        return out
    if any(a > 12 for _, a, _, _ in ambiguous):
        order = "dmy"
    elif any(b > 12 for _, _, b, _ in ambiguous):
        order = "mdy"
    else:
        order = _tidier(ambiguous)
    for i, a, b, y in ambiguous:
        d, mth = (a, b) if order == "dmy" else (b, a)
        try:
            out[i] = date(y, mth, d)
        except ValueError:
            out[i] = None
    return out


def _tidiness(ds: list[date]) -> int:
    """How many consecutive rows are 1–5 days apart (in either direction): high for real daily history."""
    return sum(1 for x, y in zip(ds, ds[1:]) if 1 <= abs((y - x).days) <= 5)


def _tidier(rows: list[tuple[int, int, int, int]]) -> str:
    def build(order):
        ds = []
        for _, a, b, y in rows:
            d, mth = (a, b) if order == "dmy" else (b, a)
            try:
                ds.append(date(y, mth, d))
            except ValueError:
                return None
        return ds
    dmy, mdy = build("dmy"), build("mdy")
    sd, sm = (_tidiness(dmy) if dmy else -1), (_tidiness(mdy) if mdy else -1)
    if sd == sm:
        raise CsvError("Can't tell whether the dates are day-first (09/11 = 9 November) or month-first (09/11 = 11 September). "
                       "Save the file with dates as YYYY-MM-DD, or include more rows.")
    return "dmy" if sd > sm else "mdy"


def parse(text: str) -> list[tuple[date, float]]:
    text = text.lstrip("﻿").strip()
    if not text:
        raise CsvError("Not a CSV file with a header row (expected columns Date and Close).")
    first = text.splitlines()[0]
    delim = max((",", ";", "\t"), key=first.count)
    if first.count(delim) == 0:
        raise CsvError("Not a CSV file with a header row (expected columns Date and Close).")
    reader = list(csv.reader(io.StringIO(text), delimiter=delim))
    header, body = reader[0], [r for r in reader[1:] if any(c.strip() for c in r)]
    if not body:
        raise CsvError("The CSV has a header but no rows.")
    names = [_clean_header(h) for h in header]
    di = next((names.index(c) for c in DATE_COLS if c in names), None)
    vi = next((names.index(c) for c in VALUE_COLS if c in names), None)
    if di is not None and vi is None and len([n for n in names if n]) == 2:  # FRED: value column named after the series
        vi = next(i for i, n in enumerate(names) if n and i != di)
    if di is None or vi is None:
        raise CsvError(f"Couldn't find Date and Close columns (found: {', '.join(h.strip() for h in header)}).")
    dates = _parse_dates([r[di] if di < len(r) else "" for r in body])
    out = {}
    for r, d in zip(body, dates):
        v = number(r[vi]) if vi < len(r) else None
        if d is not None and v is not None and v > 0:
            out[d] = v
    if not out:
        raise CsvError("No rows with a readable date and a positive close.")
    return sorted(out.items())
