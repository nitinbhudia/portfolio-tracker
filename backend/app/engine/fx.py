"""Currency conversion to USD with ECB euro reference rates (SPEC.md §3).

The ECB publishes, on each TARGET working day, how many units of each currency 1 EUR buys. So
USD per 1 X = (USD per EUR) / (X per EUR). For a date with no publication (weekend, holiday) the last
rate published before it is used; the date of the rate actually used is returned with it.
"""
from __future__ import annotations

import bisect
import csv
import io
from dataclasses import dataclass
from datetime import date

import httpx

BASE = "https://data-api.ecb.europa.eu/service/data/EXR"
USER_AGENT = "PortfolioTracker/0.1 (personal tool)"
MAX_STALE_DAYS = 7


class FxError(RuntimeError):
    pass


@dataclass(frozen=True)
class Rate:
    rate: float  # USD per 1 unit of the currency
    rate_date: date | None  # ECB publication day used (None for USD)


class Rates:
    """per_eur: currency -> sorted [(date, units per EUR)]."""

    def __init__(self, per_eur: dict[str, list[tuple[date, float]]]):
        self.per_eur = {c: sorted(v) for c, v in per_eur.items()}
        self._dates = {c: [d for d, _ in v] for c, v in self.per_eur.items()}

    def _on(self, cur: str, d: date) -> tuple[date, float] | None:
        ds = self._dates.get(cur)
        if not ds:
            return None
        i = bisect.bisect_right(ds, d) - 1
        if i < 0:
            return None
        rd, v = self.per_eur[cur][i]
        return (rd, v) if (d - rd).days <= MAX_STALE_DAYS else None

    def usd(self, cur: str, d: date) -> Rate | None:
        if cur == "USD":
            return Rate(1.0, None)
        u = self._on("USD", d)
        if u is None:
            return None
        if cur == "EUR":
            return Rate(u[1], u[0])
        x = self._on(cur, d)
        if x is None or x[0] != u[0]:
            return None
        return Rate(u[1] / x[1], u[0])

    def latest_date(self) -> date | None:
        ds = self._dates.get("USD")
        return ds[-1] if ds else None


def fetch(currencies: list[str], start: date, client: httpx.Client | None = None) -> list[tuple[date, str, float]]:
    """Daily rates (units per EUR) from the ECB for USD and the given currencies, from `start` to today."""
    curs = sorted({"USD", *[c for c in currencies if c not in ("EUR",)]})
    http = client or httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT})
    try:
        r = http.get(f"{BASE}/D.{'+'.join(curs)}.EUR.SP00.A", params={"startPeriod": start.isoformat(), "format": "csvdata"})
    except httpx.HTTPError as e:
        raise FxError(f"Could not reach the ECB data service ({type(e).__name__}).") from e
    if r.status_code == 404:
        return []
    if r.status_code >= 400:
        raise FxError(f"The ECB data service returned HTTP {r.status_code}.")
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        v = row.get("OBS_VALUE")
        if v:
            try:
                out.append((date.fromisoformat(row["TIME_PERIOD"]), row["CURRENCY"], float(v)))
            except (KeyError, ValueError) as e:
                raise FxError("Unexpected response from the ECB data service.") from e
    return out
