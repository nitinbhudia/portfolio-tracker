"""Compare your trades with market indexes (S&P 500, Nasdaq, Russell 2000, FTSE 100).

Your sheet has no price history for your own stocks, so the portfolio's day-by-day value is unknown. The honest
comparisons are the ones built on your actual cash flows and holding periods:

- **Per trade:** each sale (and each open lot) against what the same dollars would have done in the index over
  exactly the same holding period: index-equivalent gain = cost × (index at sale ÷ index at purchase − 1).
- **Same money in the index (all time):** every purchase buys the index instead, every sale sells the same dollar
  amount of it; what's left is valued today. Its money-weighted return (XIRR) is compared with yours.
- **Index performance** over the chosen period (price index, not including dividends).

Index levels are converted to USD at the ECB rate of each day (FTSE 100 is in GBP), because your results are in USD.
Index prices exclude dividends; so do your gains unless you entered dividends.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date

import httpx

from . import indexcsv
from .analytics import xirr
from .fifo import Lot, Sale
from .fx import Rates

INDEXES = {  # id: (name, default source, default symbol, currency)
    "spx": ("S&P 500", "fred", "SP500", "USD"),
    "ndq": ("Nasdaq Composite", "fred", "NASDAQCOM", "USD"),
    "ndx": ("Nasdaq-100", "fred", "NASDAQ100", "USD"),
    "rut": ("Russell 2000", "stooq", "^rut", "USD"),
    "ukx": ("FTSE 100", "stooq", "^ukx", "GBP"),
}
SOURCES = {"fred": "FRED (St. Louis Fed)", "stooq": "Stooq"}
STOOQ = "https://stooq.com/q/d/l/"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_START = "2015-01-01"
MAX_STALE_DAYS = 7
TIMEOUT = httpx.Timeout(25.0, connect=10.0)


class BenchmarkError(RuntimeError):
    pass


def parse_csv(text: str) -> list[tuple[date, float]]:
    """Daily closes from a downloaded CSV; see `indexcsv` for the formats accepted."""
    try:
        return indexcsv.parse(text)
    except indexcsv.CsvError as e:
        raise BenchmarkError(str(e)) from e


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "PortfolioTracker/0.1 (personal tool)"}, follow_redirects=True)


def _get(http: httpx.Client, url: str, params: dict, name: str) -> str:
    try:
        r = http.get(url, params=params)
    except httpx.TimeoutException as e:
        raise BenchmarkError(f"{name} didn't answer in time. Try again later, or upload a CSV.") from e
    except Exception as e:  # network refused, TLS, DNS…: always a readable message, never a crash
        raise BenchmarkError(f"Couldn't reach {name} ({type(e).__name__}). Upload a CSV instead.") from e
    if r.status_code >= 400:
        raise BenchmarkError(f"{name} answered HTTP {r.status_code}. Upload a CSV instead.")
    return r.text.strip()


def fetch_stooq(symbol: str, client: httpx.Client | None = None) -> list[tuple[date, float]]:
    body = _get(client or _client(), STOOQ, {"s": symbol, "i": "d"}, "Stooq")
    if body.lower().startswith("no data") or not body or "," not in body.splitlines()[0] or body.lstrip().startswith("<"):
        raise BenchmarkError(f"Stooq returned no data for {symbol} ({body[:60]!r}). Check the symbol or upload a CSV.")
    return parse_csv(body)


def fetch_fred(series: str, client: httpx.Client | None = None) -> list[tuple[date, float]]:
    body = _get(client or _client(), FRED, {"id": series, "cosd": FRED_START}, "FRED")
    if not body or body.lstrip().startswith("<") or "," not in body.splitlines()[0]:
        raise BenchmarkError(f"FRED returned no data for {series}. Check the series id or upload a CSV.")
    return parse_csv(body)


def fetch(source: str, symbol: str, client: httpx.Client | None = None) -> list[tuple[date, float]]:
    if source == "fred":
        return fetch_fred(symbol, client)
    if source == "stooq":
        return fetch_stooq(symbol, client)
    raise BenchmarkError(f"unknown source '{source}'")


@dataclass
class Series:
    id: str
    currency: str
    dates: list[date]
    closes: list[float]

    def level(self, d: date) -> tuple[date, float] | None:
        i = bisect.bisect_right(self.dates, d) - 1
        if i < 0 or (d - self.dates[i]).days > MAX_STALE_DAYS:
            return None
        return self.dates[i], self.closes[i]

    def usd(self, d: date, rates: Rates) -> float | None:
        lv = self.level(d)
        if lv is None:
            return None
        if self.currency == "USD":
            return lv[1]
        r = rates.usd(self.currency, lv[0])
        return lv[1] * r.rate if r else None


def _ratio(s: Series, a: date, b: date, rates: Rates) -> float | None:
    x, y = s.usd(a, rates), s.usd(b, rates)
    return y / x if x and y else None


def sale_vs_index(s: Series, sa: Sale, rates: Rates) -> float | None:
    """Index-equivalent gain (USD) of one sale: each matched purchase's cost held in the index instead."""
    total = 0.0
    for mt in sa.matches:
        q = _ratio(s, mt.buy_date, sa.date, rates)
        if q is None or mt.cost_usd is None:
            return None
        total += mt.cost_usd * (q - 1)
    return total


def compare(s: Series, sales: list[Sale], lots: list[Lot], rates: Rates, start: date, end: date,
            valuation: date) -> dict:
    """Your realised sales (sale date in [start, end]) and, if the period runs to the valuation date, your open lots,
    against the same dollars in the index over the same holding periods."""
    real = {"sales": 0, "compared": 0, "cost_usd": 0.0, "gain_usd": 0.0, "index_gain_usd": 0.0, "beat": 0, "not_compared": 0}
    for sa in sales:
        if not (start <= sa.date <= end) or sa.gain_usd is None:
            continue
        real["sales"] += 1
        idx_gain = sale_vs_index(s, sa, rates)
        if idx_gain is None:
            real["not_compared"] += 1
            continue
        real["compared"] += 1
        real["cost_usd"] += sa.cost_usd
        real["gain_usd"] += sa.gain_usd
        real["index_gain_usd"] += idx_gain
        real["beat"] += sa.gain_usd > idx_gain
    opn = None
    if end >= valuation:
        opn = {"lots": 0, "compared": 0, "cost_usd": 0.0, "index_gain_usd": 0.0, "not_compared": 0}
        for lot in lots:
            opn["lots"] += 1
            q = _ratio(s, lot.date, valuation, rates)
            cost = lot.shares * (lot.price * lot.scale + lot.fee_per_share) * lot.cost_rate if lot.cost_rate is not None else None
            if q is None or cost is None:
                opn["not_compared"] += 1
                continue
            opn["compared"] += 1
            opn["cost_usd"] += cost
            opn["index_gain_usd"] += cost * (q - 1)
    return {"realised": real, "open": opn}


def same_money(s: Series, buys: list[tuple[date, float]], sales: list[Sale], rates: Rates, valuation: date,
               your_end_value: float | None) -> dict | None:
    """All time: every purchase buys the index, every sale sells the same dollar amount of it."""
    units, flows, missing, ran_out = 0.0, [], 0, None
    events = [(d, -c, "buy") for d, c in buys if c is not None] + [(sa.date, sa.proceeds_usd, "sell") for sa in sales if sa.proceeds_usd is not None]
    all_flows = [(d, v) for d, v, _ in events]
    for d, v, _ in sorted(events, key=lambda e: e[0]):
        px = s.usd(d, rates)
        if px is None:
            missing += 1
            continue
        units += -v / px
        flows.append((d, v))
        if units < -1e-9 and ran_out is None:
            ran_out = d
    end_px = s.usd(valuation, rates)
    if end_px is None or not flows:
        return None
    if ran_out is not None:  # a sale took out more than the index holding was worth: no meaningful comparison
        return {"index_end_value_usd": None, "your_end_value_usd": your_end_value, "index_xirr_pct": None,
                "your_xirr_pct": _pct(xirr(all_flows + ([(valuation, your_end_value)] if your_end_value is not None else []))),
                "trades_not_priced": missing, "ran_out": ran_out.isoformat()}
    end_value = units * end_px
    your_flows = all_flows + ([(valuation, your_end_value)] if your_end_value is not None else [])
    return {"index_end_value_usd": end_value, "your_end_value_usd": your_end_value,
            "index_xirr_pct": _pct(xirr(flows + [(valuation, end_value)])), "your_xirr_pct": _pct(xirr(your_flows)),
            "trades_not_priced": missing, "ran_out": None}


def _pct(x):
    return None if x is None else x * 100
