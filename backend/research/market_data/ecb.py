"""ECB euro foreign exchange reference rates (free, no key).

Docs: https://data.ecb.europa.eu/help/api/data
  GET https://data-api.ecb.europa.eu/service/data/EXR/D.USD+CHF.EUR.SP00.A?startPeriod=YYYY-MM-DD&format=csvdata
Rates are published around 16:00 CET on TARGET working days, "for information purposes only".
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date

import httpx

from .tiingo import MarketDataError

PROVIDER = "ecb"
BASE = "https://data-api.ecb.europa.eu/service/data/EXR"
USER_AGENT = "FibonacciAI/0.4 (personal research tool)"


@dataclass(frozen=True)
class EcbRate:
    date: date
    currency: str  # quoted per 1 EUR
    rate: float


class EcbClient:
    def __init__(self, client: httpx.Client | None = None):
        self.http = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})

    def daily(self, currencies: list[str], start: date, end: date | None = None) -> list[EcbRate]:
        key = f"D.{'+'.join(currencies)}.EUR.SP00.A"
        params = {"startPeriod": start.isoformat(), "format": "csvdata"}
        if end:
            params["endPeriod"] = end.isoformat()
        try:
            r = self.http.get(f"{BASE}/{key}", params=params)
        except httpx.HTTPError as e:
            raise MarketDataError("network", f"Could not reach the ECB data service ({type(e).__name__}).") from e
        if r.status_code == 404:  # the ECB answers 404 when the range has no observations
            return []
        if r.status_code >= 400:
            raise MarketDataError("provider_error", f"ECB data service returned HTTP {r.status_code}.")
        out = []
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                v = row.get("OBS_VALUE")
                if not v:
                    continue
                out.append(EcbRate(date.fromisoformat(row["TIME_PERIOD"]), row["CURRENCY"], float(v)))
            except (KeyError, ValueError) as e:
                raise MarketDataError("bad_response", "Unexpected response from the ECB data service.") from e
        return sorted(out, key=lambda x: (x.date, x.currency))
