"""Tiingo end-of-day price client (free plan friendly).

Docs: https://www.tiingo.com/documentation/end-of-day
  GET https://api.tiingo.com/tiingo/daily/{ticker}           -> metadata (name, exchangeCode, ...)
  GET https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate=YYYY-MM-DD -> daily bars

The API token is sent in the Authorization header (never in the URL), is read from
the environment only, and is redacted from every error message.
Free plan limits (Tiingo pricing page): 50 requests/hour, 1,000/day, 500 unique symbols/month,
personal internal use only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

PROVIDER = "tiingo"
BASE = "https://api.tiingo.com/tiingo/daily"
USER_AGENT = "FibonacciAI/0.3 (personal research tool)"


class MarketDataError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DailyBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    raw_close: float
    raw_volume: int | None
    div_cash: float
    split_factor: float


@dataclass(frozen=True)
class SymbolMeta:
    ticker: str
    name: str | None
    exchange_code: str | None
    start_date: date | None
    end_date: date | None


def to_tiingo_symbol(ticker: str) -> str:
    """IBKR 'BRK B' / 'BRK.B' -> Tiingo 'brk-b'."""
    return ticker.strip().replace(" ", "-").replace(".", "-").replace("/", "-").lower()


def _d(v: str | None) -> date | None:
    return date.fromisoformat(v[:10]) if v else None


def _int(v) -> int | None:
    return None if v is None else int(round(float(v)))


class TiingoClient:
    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise MarketDataError("not_configured", "TIINGO_API_KEY is not set in .env.")
        self._token = token
        self._client = client or httpx.Client(timeout=30.0)

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***")

    def _get(self, path: str, params: dict | None = None):
        try:
            r = self._client.get(f"{BASE}/{path}", params=params or {},
                                 headers={"Authorization": f"Token {self._token}",
                                          "Content-Type": "application/json", "User-Agent": USER_AGENT})
        except httpx.TimeoutException:
            raise MarketDataError("timeout", "Tiingo did not respond in time.") from None
        except httpx.HTTPError as e:
            raise MarketDataError("network", f"Network error contacting Tiingo ({type(e).__name__}).") from None
        if r.status_code == 404:
            raise MarketDataError("not_found", "Symbol not found at Tiingo.")
        if r.status_code in (401, 403):
            raise MarketDataError("auth", "Tiingo rejected the API key. Check TIINGO_API_KEY in .env.")
        if r.status_code == 429:
            raise MarketDataError("rate_limited", "Tiingo usage limit reached. Try again later.")
        if r.status_code != 200:
            raise MarketDataError(f"http_{r.status_code}", f"Tiingo returned HTTP {r.status_code}.")
        try:
            data = r.json()
        except ValueError:
            raise MarketDataError("parse_error", "Unexpected response from Tiingo.") from None
        # Tiingo sometimes reports errors (e.g. limits) as JSON with a 'detail' field.
        if isinstance(data, dict) and "detail" in data and len(data) == 1:
            msg = self._redact(str(data["detail"]))[:200]
            code = "rate_limited" if "limit" in msg.lower() else "provider_error"
            raise MarketDataError(code, f"Tiingo: {msg}")
        return data

    def meta(self, ticker: str) -> SymbolMeta:
        d = self._get(to_tiingo_symbol(ticker))
        return SymbolMeta(ticker=d.get("ticker", ticker), name=d.get("name"),
                          exchange_code=d.get("exchangeCode"), start_date=_d(d.get("startDate")),
                          end_date=_d(d.get("endDate")))

    def daily(self, ticker: str, start: date) -> list[DailyBar]:
        rows = self._get(f"{to_tiingo_symbol(ticker)}/prices", {"startDate": start.isoformat()})
        if not isinstance(rows, list):
            raise MarketDataError("parse_error", "Unexpected price response from Tiingo.")
        out = []
        for r in rows:
            try:
                out.append(DailyBar(
                    date=_d(r["date"]),
                    open=float(r["adjOpen"]), high=float(r["adjHigh"]), low=float(r["adjLow"]),
                    close=float(r["adjClose"]), volume=_int(r.get("adjVolume")),
                    raw_close=float(r["close"]), raw_volume=_int(r.get("volume")),
                    div_cash=float(r.get("divCash") or 0.0), split_factor=float(r.get("splitFactor") or 1.0)))
            except (KeyError, TypeError, ValueError):
                raise MarketDataError("parse_error", "Tiingo returned an incomplete price row.") from None
        return out


def dec(v: float | None) -> Decimal | None:
    return None if v is None else Decimal(str(round(v, 6)))
