"""EODHD end-of-day price client (European listings).

Docs (checked 2026-11-05): https://eodhd.com/financial-apis/api-for-historical-data-and-volumes
  GET https://eodhd.com/api/eod/{SYMBOL}.{EXCHANGE}?api_token=…&fmt=json&from=YYYY-MM-DD
Rows: date, open, high, low, close (raw, as traded), adjusted_close (splits AND dividends),
volume (split-adjusted). Auth is by api_token in the query string only, so the token is never
put in an error message or log line, and network exceptions are reported by type only.
"""
from __future__ import annotations

from datetime import date

import httpx

from .tiingo import DailyBar, MarketDataError

PROVIDER = "eodhd"
BASE = "https://eodhd.com/api/eod"
USER_AGENT = "FibonacciAI/0.4 (personal research tool)"

# MIC -> EODHD exchange code. XAMS and XSWX suffixes are not shown on EODHD's public pages
# (unverified until the user's account confirms them).
EODHD_EXCHANGES = {"XETR": "XETRA", "XLON": "LSE", "XAMS": "AS", "XSWX": "SW", "XPAR": "PA"}  # PA: shown in EODHD docs
UNVERIFIED_SUFFIXES = {"XAMS", "XSWX"}


def eodhd_symbol(ticker: str, mic: str) -> str:
    if mic not in EODHD_EXCHANGES:
        raise MarketDataError("unsupported_exchange", f"Exchange {mic} isn't supported for EODHD prices yet.")
    t = ticker.strip().upper().replace(" ", "-").replace("/", "-")
    return f"{t}.{EODHD_EXCHANGES[mic]}"


class EodhdClient:
    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise MarketDataError("not_configured", "EODHD_API_KEY is not set in .env.")
        self._token = token
        self._client = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})

    def _get(self, symbol: str, params: dict):
        try:
            r = self._client.get(f"{BASE}/{symbol}", params={**params, "api_token": self._token, "fmt": "json"})
        except httpx.TimeoutException:
            raise MarketDataError("timeout", "EODHD did not respond in time.") from None
        except httpx.HTTPError as e:  # the exception text can contain the URL (and token): never include it
            raise MarketDataError("network", f"Network error contacting EODHD ({type(e).__name__}).") from None
        if r.status_code == 404:
            raise MarketDataError("not_found", f"{symbol} was not found on EODHD (check the ticker and exchange).")
        if r.status_code in (401, 403):
            raise MarketDataError("auth", "EODHD rejected the API key, or your plan doesn't cover this exchange. "
                                          "Check EODHD_API_KEY in .env and your plan.")
        if r.status_code == 402:
            raise MarketDataError("plan_limit", "EODHD: your plan's daily API calls are used up.")
        if r.status_code == 429:
            raise MarketDataError("rate_limited", "EODHD rate limit reached. Try again later.")
        if r.status_code != 200:
            raise MarketDataError(f"http_{r.status_code}", f"EODHD returned HTTP {r.status_code}.")
        try:
            return r.json()
        except ValueError:
            raise MarketDataError("parse_error", "Unexpected response from EODHD.") from None

    def daily(self, symbol: str, start: date) -> list[DailyBar]:
        rows = self._get(symbol, {"from": start.isoformat(), "period": "d"})
        if not isinstance(rows, list):
            raise MarketDataError("parse_error", "Unexpected price response from EODHD.")
        out = []
        for r in rows:
            try:
                raw_close, adj = float(r["close"]), float(r["adjusted_close"])
                if raw_close <= 0:
                    raise ValueError
                k = adj / raw_close  # same factor for O/H/L as for the close on that day
                vol = r.get("volume")
                out.append(DailyBar(
                    date=date.fromisoformat(r["date"]),
                    open=float(r["open"]) * k, high=float(r["high"]) * k, low=float(r["low"]) * k, close=adj,
                    volume=int(vol) if vol is not None else None,
                    raw_close=raw_close, raw_volume=None,  # EODHD volume is already split-adjusted
                    div_cash=0.0, split_factor=1.0))     # corporate actions detected via the factor (see eu_service)
            except (KeyError, TypeError, ValueError):
                raise MarketDataError("parse_error", "EODHD returned an incomplete price row.") from None
        return sorted(out, key=lambda b: b.date)
