"""Demo mode's network guard: every HTTP request the demo copy makes goes through here.

- Price and rate providers (Tiingo, EODHD, ECB, FRED, Stooq) are answered on the spot with the synthetic market
  (app.demo.market), in each provider's own format, so the app's normal download code runs unchanged and nothing is
  sent anywhere.
- A few public hosts pass through: Claude (Ask works on the demo data) and the ETF issuers' public holdings files.
- Everything else (GitHub updates, your broker, unknown hosts) is refused as a connection error.

It wraps the transport of every httpx client created after `install()` (including proxy mounts), so no client can
go around it.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from urllib.parse import unquote

import httpx

from . import market
from .universe import COMPANIES

FAKE_HOSTS = {"api.tiingo.com", "eodhd.com", "data-api.ecb.europa.eu", "fred.stlouisfed.org", "stooq.com"}
PASS_HOSTS = {"api.anthropic.com", "www.ssga.com", "www.ishares.com"}
TIINGO_EXCHANGE = {"XNAS": "NASDAQ", "XNYS": "NYSE"}
_installed = False


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _json(request: httpx.Request, body, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body, default=str).encode(), request=request,
                          headers={"Content-Type": "application/json"})


def _text(request: httpx.Request, body: str) -> httpx.Response:
    return httpx.Response(200, content=body.encode(), request=request, headers={"Content-Type": "text/csv"})


def _company(sym: str):
    s = sym.upper().replace("-", ".")
    return next((c for c in COMPANIES if c.ticker == s), None)


def _tiingo(request: httpx.Request) -> httpx.Response:
    path, q = request.url.path, request.url.params
    if path.startswith("/tiingo/utilities/search"):
        text = (q.get("query") or "").lower()
        rows = [{"ticker": c.ticker, "name": f"{c.name} (demo)", "assetType": "Stock", "countryCode": "US", "isActive": True}
                for c in COMPANIES if c.us and (text in c.ticker.lower() or text in c.name.lower())]
        return _json(request, rows[: int(q.get("limit") or 15)])
    m = re.fullmatch(r"/tiingo/daily/([^/]+)(/prices)?/?", path)
    if not m:
        return _json(request, {"detail": "Not found."}, 404)
    sym = m.group(1).upper()
    c = _company(sym)
    if not m.group(2):
        return _json(request, {"ticker": sym, "name": f"{c.name} (demo)" if c else f"{sym} (demo company)",
                               "exchangeCode": TIINGO_EXCHANGE.get(c.mic, "NYSE") if c else "NYSE",
                               "startDate": market.ANCHOR.isoformat(), "endDate": date.today().isoformat()})
    rows = []
    for b in market.bars(sym, _d(q.get("startDate")), _d(q.get("endDate"))):
        rows.append({"date": f"{b['date'].isoformat()}T00:00:00.000Z", "open": b["open"], "high": b["high"], "low": b["low"],
                     "close": b["close"], "volume": b["volume"], "adjOpen": b["open"], "adjHigh": b["high"], "adjLow": b["low"],
                     "adjClose": b["close"], "adjVolume": b["volume"], "divCash": 0.0, "splitFactor": 1.0})
    return _json(request, rows)


def _eodhd(request: httpx.Request) -> httpx.Response:
    m = re.fullmatch(r"/api/eod/([^/]+)", request.url.path)
    if not m:
        return _json(request, {"error": "not found"}, 404)
    sym = unquote(m.group(1)).rsplit(".", 1)[0].upper()
    rows = [{"date": b["date"].isoformat(), "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
             "adjusted_close": b["close"], "volume": b["volume"]}
            for b in market.bars(sym, _d(request.url.params.get("from")), _d(request.url.params.get("to")))]
    return _json(request, rows)


def _ecb(request: httpx.Request) -> httpx.Response:
    m = re.search(r"/EXR/D\.([A-Z+]+)\.EUR\.SP00\.A", request.url.path)
    curs = m.group(1).split("+") if m else ["USD"]
    q = request.url.params
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["KEY", "FREQ", "CURRENCY", "CURRENCY_DENOM", "EXR_TYPE", "EXR_SUFFIX", "TIME_PERIOD", "OBS_VALUE"])
    for d, c, v in market.fx(curs, _d(q.get("startPeriod")) or market.ANCHOR, _d(q.get("endPeriod"))):
        w.writerow([f"EXR.D.{c}.EUR.SP00.A", "D", c, "EUR", "SP00", "A", d.isoformat(), v])
    return _text(request, out.getvalue())


def _fred(request: httpx.Request) -> httpx.Response:
    sid = request.url.params.get("id") or "SP500"
    lines = [f"observation_date,{sid}"] + [f"{b['date'].isoformat()},{b['close']}" for b in market.bars(sid)]
    return _text(request, "\n".join(lines) + "\n")


def _stooq(request: httpx.Request) -> httpx.Response:
    sym = request.url.params.get("s") or "^rut"
    lines = ["Date,Open,High,Low,Close,Volume"] + [f"{b['date'].isoformat()},{b['open']},{b['high']},{b['low']},{b['close']},0"
                                                   for b in market.bars(sym)]
    return _text(request, "\n".join(lines) + "\n")


HANDLERS = {"api.tiingo.com": _tiingo, "eodhd.com": _eodhd, "data-api.ecb.europa.eu": _ecb,
            "fred.stlouisfed.org": _fred, "stooq.com": _stooq}
LOG: list[tuple[str, str]] = []  # (host, "fake" | "pass" | "blocked"), the latest 200, for tests and the mode page


def route(request: httpx.Request) -> httpx.Response | None:
    """A synthetic answer, None to let the request through, or a ConnectError for anything not allowed."""
    host = (request.url.host or "").lower()
    kind = "fake" if host in HANDLERS else "pass" if host in PASS_HOSTS else "blocked"
    LOG.append((host, kind))
    del LOG[:-200]
    if kind == "fake":
        return HANDLERS[host](request)
    if kind == "pass":
        return None
    raise httpx.ConnectError(f"Demo mode doesn't connect to {host or 'this address'} (only made-up data is used).",
                             request=request)


class Guard(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport | None):
        self.inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        r = route(request)
        if r is not None:
            return r
        if self.inner is None:
            raise httpx.ConnectError("no transport", request=request)
        return self.inner.handle_request(request)

    def close(self) -> None:
        if self.inner is not None:
            self.inner.close()


class AsyncGuard(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport | None):
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        r = route(request)
        if r is not None:
            return r
        if self.inner is None:
            raise httpx.ConnectError("no transport", request=request)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        if self.inner is not None:
            await self.inner.aclose()


def _wrap(cls, guard):
    orig = cls.__init__

    def __init__(self, *a, **kw):
        orig(self, *a, **kw)
        if not isinstance(self._transport, guard):
            self._transport = guard(self._transport)
        self._mounts = {k: (v if v is None or isinstance(v, guard) else guard(v)) for k, v in self._mounts.items()}
    cls.__init__ = __init__


def install() -> None:
    """Route all of this process's HTTP through the guard, and lift the free-plan request budgets (nothing is sent)."""
    global _installed
    if _installed:
        return
    _installed = True
    _wrap(httpx.Client, Guard)
    _wrap(httpx.AsyncClient, AsyncGuard)
    from research.market_data import service as md
    md.HOURLY_BUDGET = md.DAILY_BUDGET = 10 ** 9
    from research.core.config import settings
    settings.eodhd_daily_budget = 10 ** 9
