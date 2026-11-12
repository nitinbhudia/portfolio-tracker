"""Interactive Brokers Flex Web Service adapter (read-only reporting).

Protocol (Flex Web Service v3, per IBKR documentation):
  1. GET {SEND_URL}?t=TOKEN&q=QUERY_ID&v=3  -> XML with <Status>Success</Status><ReferenceCode>…
  2. GET {GET_URL}?t=TOKEN&q=REFERENCE_CODE&v=3 -> the Flex statement XML (poll while it's generating)

IBKR documents a rate limit of 1 request/second and 10 requests/minute per token.
The token only grants access to *reports*; Flex cannot place or change orders.

Security: the token is read from the environment only, is never logged, and is
redacted from every error message produced here.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx
from defusedxml import ElementTree as ET

from .base import BrokerError, BrokerPosition, BrokerSnapshot, SkippedPosition, mask_account

log = logging.getLogger("fibonacci_ai.broker")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx INFO logs would include the token in the URL
logging.getLogger("httpcore").setLevel(logging.WARNING)

SOURCE = "ibkr_flex"
SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
GET_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
USER_AGENT = "FibonacciAI/0.2 (personal read-only research tool)"

# Asset categories imported as holdings. Everything else is reported as skipped.
SUPPORTED_CATEGORIES = {"STK"}  # IBKR reports stocks and ETFs as STK

# IBKR Flex error codes (documented "Version 3 Error Codes").
RETRY_CODES = {"1001", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"}
FRIENDLY = {
    "1003": "Statement is not available.",
    "1010": "Legacy Flex Queries are no longer supported. Create an Activity Flex Query.",
    "1011": "Flex Web Service is not enabled or the account is inactive.",
    "1012": "Your Flex token has expired. Generate a new token in Client Portal and update .env.",
    "1013": "IP restriction on the Flex token blocks this computer.",
    "1014": "Query ID is invalid. Check IBKR_FLEX_QUERY_ID.",
    "1015": "Flex token is invalid. Check IBKR_FLEX_TOKEN.",
    "1016": "Account is invalid.",
    "1017": "Reference code is invalid.",
    "1018": "Too many requests to IBKR. Wait a minute and try again.",
    "1019": "IBKR is still generating the statement.",
    "1020": "Invalid request or unable to validate request.",
}


class Redactor:
    def __init__(self, *secrets: str | None):
        self.secrets = [s for s in secrets if s]

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return text


# --------------------------------------------------------------------------- parsing helpers

def _dec(v: str | None) -> Decimal | None:
    if v is None or v.strip() in ("", "--", "N/A"):
        return None
    try:
        return Decimal(v.replace(",", "").strip())
    except InvalidOperation:
        return None


def _date(v: str | None) -> date | None:
    if not v:
        return None
    v = v.strip().split(";")[0].split(",")[0].split(" ")[0]
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _generated(v: str | None) -> datetime | None:
    if not v:
        return None
    v = v.strip()
    for fmt in ("%Y%m%d;%H%M%S", "%Y%m%d %H%M%S", "%Y-%m-%d;%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(v, fmt)  # IBKR reports in its own timezone; kept naive and labelled
        except ValueError:
            continue
    return None


def _attr(el, *names: str) -> str | None:
    for n in names:
        v = el.get(n)
        if v not in (None, ""):
            return v
    return None


def parse_flex_statement(xml_text: str | bytes) -> BrokerSnapshot:
    """Parse an Activity Flex Query XML response into a BrokerSnapshot.

    Requires the *Open Positions* section. Uses *Account Information* (base currency)
    and *Conversion Rates* sections when present.
    """
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:  # defusedxml raises several types
        raise BrokerError("parse_error", "The file is not valid Flex XML.") from e

    if root.tag == "FlexStatementResponse":
        code = (root.findtext("ErrorCode") or "").strip()
        msg = FRIENDLY.get(code, (root.findtext("ErrorMessage") or "IBKR returned an error.").strip())
        raise BrokerError(f"ibkr_{code or 'error'}", msg, retryable=code in RETRY_CODES)
    if root.tag != "FlexQueryResponse":
        raise BrokerError("parse_error", "Unexpected XML: expected a FlexQueryResponse.")

    statements = root.findall(".//FlexStatement")
    if not statements:
        raise BrokerError("empty", "The Flex report contains no statements.")

    snap = BrokerSnapshot(source=SOURCE, generated_at=None, report_date=None)
    saw_positions_section = False
    for st in statements:
        acct = mask_account(st.get("accountId"))
        snap.generated_at = snap.generated_at or _generated(st.get("whenGenerated"))
        snap.report_date = max(filter(None, [snap.report_date, _date(st.get("toDate"))]), default=None)

        info = st.find("AccountInformation")
        base = (info.get("currency") if info is not None else None) or ""
        snap.accounts[acct] = base

        for cr in st.findall("./ConversionRates/ConversionRate"):
            f, t, r = cr.get("fromCurrency"), cr.get("toCurrency"), _dec(cr.get("rate"))
            if f and t and r and r > 0 and r != Decimal(-1):
                snap.fx_rates[(f, t)] = (r, _date(cr.get("reportDate")))

        section = st.find("OpenPositions")
        if section is None:
            continue
        saw_positions_section = True
        rows = section.findall("OpenPosition")
        # If both SUMMARY and LOT rows exist, use SUMMARY only (avoids double counting).
        has_summary = any((r.get("levelOfDetail") or "").upper() == "SUMMARY" for r in rows)
        for r in rows:
            lvl = (r.get("levelOfDetail") or "").upper()
            if has_summary and lvl != "SUMMARY":
                continue
            cat = (r.get("assetCategory") or "").upper()
            sym = r.get("symbol") or "?"
            if cat not in SUPPORTED_CATEGORIES:
                snap.skipped.append(SkippedPosition(sym, cat or "unknown", "asset class not supported yet (stocks/ETFs only)"))
                continue
            qty, mark = _dec(r.get("position")), _dec(r.get("markPrice"))
            ccy = r.get("currency")
            if qty is None or mark is None or not ccy:
                snap.skipped.append(SkippedPosition(sym, cat, "missing quantity, price or currency"))
                continue
            isin = _attr(r, "isin")
            if not isin and (r.get("securityIDType") or "").upper() == "ISIN":
                isin = r.get("securityID")
            fx = _dec(r.get("fxRateToBase"))
            rd = _date(r.get("reportDate"))
            snap.positions.append(BrokerPosition(
                account_masked=acct, conid=r.get("conid"), isin=isin, symbol=sym,
                description=r.get("description"), asset_category=cat,
                listing_exchange=r.get("listingExchange"), currency=ccy, quantity=qty,
                multiplier=_dec(r.get("multiplier")) or Decimal(1), mark_price=mark,
                position_value=_dec(r.get("positionValue")),
                cost_basis_price=_dec(r.get("costBasisPrice")),
                cost_basis_money=_dec(r.get("costBasisMoney")),
                unrealised_pnl=_dec(r.get("fifoPnlUnrealized")),
                fx_rate_to_base=fx, report_date=rd))
            if fx and base and ccy != base:
                snap.fx_rates.setdefault((ccy, base), (fx, rd))
            snap.report_date = max(filter(None, [snap.report_date, rd]), default=None)

    if not saw_positions_section:
        raise BrokerError("no_positions_section",
                          "The Flex Query has no 'Open Positions' section. Edit the query in Client Portal and add it.")
    for acct, base in snap.accounts.items():
        if not base:
            snap.warnings.append(f"Account {acct}: base currency unknown (add the 'Account Information' section to the query).")
    return snap


# --------------------------------------------------------------------------- web service client

class IbkrFlexAdapter:
    """Fetches an Activity Flex Query via the Flex Web Service. Read-only."""

    name = SOURCE

    def __init__(self, token: str, query_id: str, *, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_polls: int = 6):
        if not token or not query_id:
            raise BrokerError("not_configured", "IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID must be set in .env.")
        self._token = token
        self._query_id = query_id
        self._redact = Redactor(token)
        self._client = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
        self._sleep = sleep
        self._max_polls = max_polls

    def _get(self, url: str, params: dict) -> str:
        try:
            r = self._client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        except httpx.TimeoutException as e:
            raise BrokerError("timeout", "IBKR did not respond in time. Try again later.", retryable=True) from None
        except httpx.HTTPError as e:
            raise BrokerError("network", self._redact(f"Network error contacting IBKR ({type(e).__name__}).")) from None
        if r.status_code != 200:
            raise BrokerError(f"http_{r.status_code}", f"IBKR returned HTTP {r.status_code}.",
                              retryable=r.status_code >= 500)
        return r.text

    def fetch_snapshot(self) -> BrokerSnapshot:
        body = self._get(SEND_URL, {"t": self._token, "q": self._query_id, "v": "3"})
        try:
            root = ET.fromstring(body)
        except Exception:
            raise BrokerError("parse_error", "Unexpected response from IBKR SendRequest.") from None
        status = (root.findtext("Status") or "").strip()
        if status != "Success":
            code = (root.findtext("ErrorCode") or "").strip()
            raise BrokerError(f"ibkr_{code or 'error'}",
                              FRIENDLY.get(code, self._redact((root.findtext("ErrorMessage") or "SendRequest failed.").strip())),
                              retryable=code in RETRY_CODES)
        ref = (root.findtext("ReferenceCode") or "").strip()
        if not ref.isdigit():
            raise BrokerError("parse_error", "IBKR did not return a reference code.")

        delay = 2.0
        for _ in range(self._max_polls):
            self._sleep(delay)
            stmt = self._get(GET_URL, {"t": self._token, "q": ref, "v": "3"})
            try:
                return parse_flex_statement(stmt)
            except BrokerError as e:
                if e.code in ("ibkr_1019", "ibkr_1004", "ibkr_1009", "ibkr_1018") or (e.retryable and e.code.startswith("ibkr_")):
                    delay = min(delay * 1.6, 12.0)
                    continue
                raise
        raise BrokerError("not_ready", "IBKR is still generating the report. Try again in a minute.", retryable=True)
