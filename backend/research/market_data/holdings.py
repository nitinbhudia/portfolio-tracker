"""Sector ETF holdings from the issuers: State Street (SSGA, US SPDR) and iShares (European sector ETFs).

iShares (checked 2026-11-06): each fund page on ishares.com links a CSV
(`.../<product>/1495092304805.ajax?fileType=csv&fileName=<TICKER>_holdings&dataType=fund`). Layout: a
"Fund Holdings as of" line, a blank line, then Ticker, Name, Sector, Asset Class, Market Value,
Weight (%), Notional Value, Shares, Price, Location, Exchange, Market Currency. Numbers may use ’ or ,
as thousands separators. Only "Equity" rows keep a ticker; cash, FX and futures rows are kept without one.

State Street (SSGA) daily holdings files:

Source (checked 2026-11-06): https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/
holdings-daily-us-en-{ticker}.xlsx — one file per SPDR ETF. Layout: "Fund Name:", "Ticker Symbol:",
"Holdings: As of DD-Mon-YYYY", then a header row (Name, Ticker, Identifier, SEDOL, Weight, Sector,
Shares Held, Local Currency) and one row per holding. Weights are in percent.

The file is untrusted input: it's parsed with the standard zipfile module plus defusedxml (no new
dependency), with a size cap, and only the cells we need are read.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

import httpx
from defusedxml import ElementTree as ET

from .tiingo import MarketDataError

SOURCE = "ssga"
ISHARES_SOURCE = "ishares"
ISHARES_BASE = "https://www.ishares.com"
URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{t}.xlsx"
USER_AGENT = "FibonacciAI/0.5 (personal research tool)"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNZIPPED_BYTES = 30 * 1024 * 1024
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@dataclass(frozen=True)
class Holding:
    rank: int
    name: str
    ticker: str | None
    identifier: str | None
    sedol: str | None
    weight_pct: float
    currency: str | None
    exchange: str | None = None


@dataclass(frozen=True)
class HoldingsFile:
    etf_ticker: str
    fund_name: str | None
    as_of: date
    holdings: list[Holding]


def _col(ref: str) -> str:
    return "".join(ch for ch in ref if ch.isalpha())


def _rows(content: bytes) -> list[dict[str, str | None]]:
    if len(content) > MAX_FILE_BYTES:
        raise MarketDataError("parse_error", "Holdings file is unexpectedly large.")
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise MarketDataError("parse_error", "Holdings file is not a valid .xlsx file.") from None
    if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED_BYTES:
        raise MarketDataError("parse_error", "Holdings file expands to an unexpected size.")
    names = set(z.namelist())
    if "xl/worksheets/sheet1.xml" not in names:
        raise MarketDataError("parse_error", "Holdings file has no worksheet.")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    out = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{NS}row"):
        cells: dict[str, str | None] = {}
        for c in row.iter(f"{NS}c"):
            v = c.find(f"{NS}v")
            kind = c.get("t")
            if kind == "s" and v is not None:
                val = shared[int(v.text)]
            elif kind == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(f"{NS}t"))
            else:
                val = v.text if v is not None else None
            cells[_col(c.get("r", ""))] = val.strip() if isinstance(val, str) else val
        out.append(cells)
    return out


def parse_ssga(content: bytes, expected_ticker: str | None = None) -> HoldingsFile:
    rows = _rows(content)
    meta, header_i = {}, None
    for i, r in enumerate(rows):
        a = (r.get("A") or "").strip()
        if a in ("Fund Name:", "Ticker Symbol:", "Holdings:"):
            meta[a] = r.get("B")
        if a == "Name" and (r.get("B") or "") == "Ticker":
            header_i = i
            break
    if header_i is None:
        raise MarketDataError("parse_error", "Holdings file has no Name/Ticker header row.")
    header = {v: k for k, v in rows[header_i].items() if v}
    if "Weight" not in header:
        raise MarketDataError("parse_error", "Holdings file has no Weight column.")
    as_of_txt = (meta.get("Holdings:") or "").replace("As of", "").strip()
    try:
        as_of = datetime.strptime(as_of_txt, "%d-%b-%Y").date()
    except ValueError:
        raise MarketDataError("parse_error", f"Holdings file date not understood: '{as_of_txt}'.") from None
    etf = (meta.get("Ticker Symbol:") or "").strip().upper()
    if expected_ticker and etf != expected_ticker.upper():
        raise MarketDataError("parse_error", f"Expected holdings for {expected_ticker}, got {etf or 'unknown'}.")
    out: list[Holding] = []
    for r in rows[header_i + 1 :]:
        name = r.get(header["Name"])
        w = r.get(header["Weight"])
        if not name:
            if out:
                break  # first blank row after the table ends it
            continue
        try:
            weight = float(w)
        except (TypeError, ValueError):
            continue  # notes or rows without a weight are skipped, never guessed
        tk = r.get(header.get("Ticker", ""))
        out.append(Holding(rank=len(out) + 1, name=name, ticker=None if tk in (None, "", "-") else tk.upper(),
                           identifier=r.get(header.get("Identifier", "")), sedol=r.get(header.get("SEDOL", "")),
                           weight_pct=weight, currency=r.get(header.get("Local Currency", ""))))
    if not out:
        raise MarketDataError("parse_error", "Holdings file contains no holdings.")
    out.sort(key=lambda h: -h.weight_pct)
    out = [Holding(i + 1, h.name, h.ticker, h.identifier, h.sedol, h.weight_pct, h.currency) for i, h in enumerate(out)]
    return HoldingsFile(etf_ticker=etf, fund_name=meta.get("Fund Name:"), as_of=as_of, holdings=out)


def _num(v: str | None) -> float:
    return float((v or "").replace("’", "").replace("'", "").replace(",", "").strip())


def parse_ishares(content: bytes, etf_ticker: str) -> HoldingsFile:
    if len(content) > MAX_FILE_BYTES:
        raise MarketDataError("parse_error", "Holdings file is unexpectedly large.")
    text = content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    as_of = None
    for ln in lines[:5]:
        if ln.startswith("Fund Holdings as of"):
            try:
                as_of = datetime.strptime(next(csv.reader([ln]))[1].strip(), "%d/%b/%Y").date()
            except (IndexError, ValueError):
                pass
    if as_of is None:
        raise MarketDataError("parse_error", "iShares holdings file has no 'Fund Holdings as of' date.")
    try:
        hdr = next(i for i, ln in enumerate(lines) if ln.startswith("Ticker,"))
    except StopIteration:
        raise MarketDataError("parse_error", "iShares holdings file has no header row.") from None
    rows = []
    for r in csv.DictReader(io.StringIO("\n".join(lines[hdr:]))):
        name = (r.get("Name") or "").strip()
        if not name:
            continue
        try:
            w = _num(r.get("Weight (%)"))
        except ValueError:
            continue  # notes or rows without a weight are skipped, never guessed
        equity = (r.get("Asset Class") or "").strip() == "Equity"
        tk = (r.get("Ticker") or "").strip()
        rows.append(Holding(rank=0, name=name, ticker=tk.upper() if equity and tk not in ("", "-") else None,
                            identifier=None, sedol=None, weight_pct=w, currency=(r.get("Market Currency") or None),
                            exchange=(r.get("Exchange") or "").strip() or None))
    if not rows:
        raise MarketDataError("parse_error", "iShares holdings file contains no holdings.")
    rows.sort(key=lambda h: -h.weight_pct)
    rows = [Holding(i + 1, h.name, h.ticker, None, None, h.weight_pct, h.currency, h.exchange) for i, h in enumerate(rows)]
    return HoldingsFile(etf_ticker=etf_ticker.upper(), fund_name=None, as_of=as_of, holdings=rows)


def fetch_ishares(ticker: str, path: str, client: httpx.Client | None = None) -> HoldingsFile:
    http = client or httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        r = http.get(ISHARES_BASE + path, params={"fileType": "csv", "fileName": f"{ticker}_holdings", "dataType": "fund"})
    except httpx.HTTPError as e:
        raise MarketDataError("network", f"Could not reach iShares ({type(e).__name__}).") from None
    if r.status_code != 200:
        raise MarketDataError(f"http_{r.status_code}", f"iShares returned HTTP {r.status_code} for {ticker} holdings.")
    return parse_ishares(r.content, ticker)


def fetch_ssga(ticker: str, client: httpx.Client | None = None) -> HoldingsFile:
    http = client or httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        r = http.get(URL.format(t=ticker.lower()))
    except httpx.HTTPError as e:
        raise MarketDataError("network", f"Could not reach State Street ({type(e).__name__}).") from None
    if r.status_code == 404:
        raise MarketDataError("not_found", f"State Street has no holdings file for {ticker}.")
    if r.status_code != 200:
        raise MarketDataError(f"http_{r.status_code}", f"State Street returned HTTP {r.status_code} for {ticker} holdings.")
    return parse_ssga(r.content, expected_ticker=ticker)
