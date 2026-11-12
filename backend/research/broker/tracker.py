"""Holdings from Portfolio Tracker (read-only): your open positions from the workbook, as a broker-style snapshot.

Research treats Portfolio Tracker like a read-only broker: each sync turns the tracker's open positions into
"broker positions" (ticker, shares, average cost, current price), which the rest of Research already knows how to
value, chart, scan and alert on. US stocks with a ticker (set on Data ▾ Price history) get real Tiingo prices and a
full analysis; other positions are valued with the tracker's own price and exchange rate.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from .base import BrokerError, BrokerPosition, BrokerSnapshot, SkippedPosition

SOURCE = "tracker"
# The tracker doesn't know a US stock's exchange; any existing real listing's exchange is reused, else NYSE
# (same trading calendar as Nasdaq; only the label differs).
MIC_TO_IBKR = {"XNAS": "NASDAQ", "XNYS": "NYSE", "ARCX": "ARCA", "XASE": "AMEX", "BATS": "BATS"}


def _d(x) -> Decimal | None:
    return None if x is None else Decimal(str(round(float(x), 8)))


def snapshot_from_positions(pos: dict, tickers: dict[str, str | None], mic_for=lambda t: None) -> BrokerSnapshot:
    """pos: Portfolio Tracker's /api/positions result; tickers: stock group -> ticker (US pools)."""
    as_of = date.fromisoformat(pos["as_of"])
    snap = BrokerSnapshot(source=SOURCE, generated_at=datetime.now(timezone.utc), report_date=as_of,
                          accounts={"tracker": "USD"})
    for p in pos["positions"]:
        if not p.get("shares") or p["shares"] <= 0:
            continue
        if p.get("price") is None or p.get("rate") is None:
            snap.skipped.append(SkippedPosition(p["stock"], "STK", "no current price or exchange rate in Portfolio Tracker"))
            continue
        scale = 0.01 if p.get("pence") else 1.0
        ticker = tickers.get(p["stock_key"]) if p["currency"] == "USD" else None
        mark = p["price"] * scale
        avg = (p.get("avg_cost") or 0.0) * scale if p.get("avg_cost") is not None else None
        exch = None
        if ticker:
            exch = MIC_TO_IBKR.get(mic_for(ticker) or "", "NYSE")
        snap.positions.append(BrokerPosition(
            account_masked="tracker", conid=None, isin=None, symbol=ticker or p["stock"], description=p["stock"],
            asset_category="STK", listing_exchange=exch, currency=p["currency"], quantity=_d(p["shares"]), multiplier=Decimal(1),
            mark_price=_d(mark), position_value=_d(p["shares"] * mark), cost_basis_price=_d(avg),
            cost_basis_money=_d(p["cost_local"] * scale if p.get("cost_local") is not None else None),
            unrealised_pnl=_d(p["shares"] * mark - p["cost_local"] * scale) if p.get("cost_local") is not None else None,
            fx_rate_to_base=_d(p["rate"]), report_date=date.fromisoformat(p["price_date"]) if p.get("price_date") else as_of))
        if p["currency"] != "USD":
            snap.fx_rates[(p["currency"], "USD")] = (_d(p["rate"]), date.fromisoformat(p["rate_date"]) if p.get("rate_date") else as_of)
    usd_without_ticker = [p["stock"] for p in pos["positions"] if p["currency"] == "USD" and not tickers.get(p["stock_key"])]
    if usd_without_ticker:
        snap.warnings.append(f"{len(usd_without_ticker)} US position(s) have no ticker, so no price history or analysis: "
                             "set tickers on Data ▾ Price history.")
    return snap


def fingerprint(pos: dict, tickers: dict) -> str:
    key = [(p["pool"], round(p["shares"], 6), p.get("price"), tickers.get(p["stock_key"])) for p in pos["positions"]]
    return hashlib.sha256(json.dumps([pos["as_of"], key], default=str).encode()).hexdigest()[:20]


def read_tracker() -> tuple[dict, dict]:
    """The tracker's open positions and tickers, from its own database."""
    from app.db import models as tm
    from app.services import portfolio as tp
    db = tm.SessionLocal()
    try:
        try:
            st = tp._need(db)
            pos = tp.positions(db)
        except tp.NotFound as e:
            raise BrokerError("not_configured", "Nothing imported in Portfolio Tracker yet: upload your workbook first.") from e
        return pos, dict(st["tickers"])
    finally:
        db.close()
