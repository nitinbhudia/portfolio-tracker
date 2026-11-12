"""Broker sync and valuation of real broker positions.

Real positions never touch the synthetic universe, synthetic prices or synthetic FX.
They are valued with the broker's own end-of-day mark prices and the FX rates
contained in the broker report. If a conversion isn't possible from that data, the
app says so instead of guessing.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from research.core.config import settings
from research.db import models as m

from .base import BrokerError, BrokerSnapshot
from .ibkr_flex import SOURCE as FLEX_SOURCE
from .ibkr_flex import IbkrFlexAdapter

Q2 = Decimal("0.01")

# IBKR listingExchange code -> (MIC, display name). Display only; unknown codes are shown as-is.
IB_EXCHANGES = {
    "NASDAQ": ("XNAS", "Nasdaq"), "NYSE": ("XNYS", "NYSE"), "ARCA": ("ARCX", "NYSE Arca"),
    "AMEX": ("XASE", "NYSE American"), "BATS": ("BATS", "Cboe BZX"), "AEB": ("XAMS", "Euronext Amsterdam"),
    "SBF": ("XPAR", "Euronext Paris"), "ENEXT.BE": ("XBRU", "Euronext Brussels"), "IBIS": ("XETR", "Xetra"),
    "IBIS2": ("XETR", "Xetra"), "FWB": ("XFRA", "Frankfurt"), "FWB2": ("XFRA", "Frankfurt"),
    "EBS": ("XSWX", "SIX Swiss Exchange"), "LSE": ("XLON", "London Stock Exchange"),
    "LSEETF": ("XLON", "London Stock Exchange (ETF)"), "BVME": ("XMIL", "Borsa Italiana"),
    "BVME.ETF": ("XMIL", "Borsa Italiana (ETF)"), "BM": ("XMAD", "BME Madrid"), "SFB": ("XSTO", "Nasdaq Stockholm"),
    "CPH": ("XCSE", "Nasdaq Copenhagen"), "OSE": ("XOSL", "Oslo Børs"), "VSE": ("XWBO", "Wiener Börse"),
    "TSE": ("XTSE", "Toronto"), "ASX": ("XASX", "ASX"), "SEHK": ("XHKG", "Hong Kong"),
    "GETTEX": ("XGTX", "gettex"), "TGATE": ("TGAT", "Tradegate"),
}


def flex_configured() -> bool:
    return bool(settings.ibkr_flex_token and settings.ibkr_flex_token.get_secret_value() and settings.ibkr_flex_query_id)


def mask_query_id(q: str | None) -> str | None:
    if not q:
        return None
    return ("*" * max(0, len(q) - 3)) + q[-3:]


def default_flex_adapter() -> IbkrFlexAdapter:
    if not flex_configured():
        raise BrokerError("not_configured", "IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID must be set in .env, then restart the app.")
    return IbkrFlexAdapter(settings.ibkr_flex_token.get_secret_value(), settings.ibkr_flex_query_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_sync(db: Session, fetch: Callable[[], BrokerSnapshot], source: str, enforce_cooldown: bool = True) -> dict:
    """Run one import. Existing positions are replaced only if the import succeeds."""
    if enforce_cooldown:
        last = db.scalar(select(m.BrokerSyncRun).where(m.BrokerSyncRun.source == source)
                         .order_by(m.BrokerSyncRun.started_at.desc()).limit(1))
        if last is not None:
            started = last.started_at if last.started_at.tzinfo else last.started_at.replace(tzinfo=timezone.utc)
            wait = settings.broker_sync_cooldown_seconds - (_now() - started).total_seconds()
            if wait > 0:
                raise BrokerError("cooldown", f"Please wait {int(wait) + 1} s before syncing again (IBKR rate limits).")

    run = m.BrokerSyncRun(source=source, status="running", started_at=_now())
    db.add(run)
    db.commit()
    try:
        snap = fetch()
    except BrokerError as e:
        run.status, run.error_code, run.message, run.finished_at = "failed", e.code, e.message[:500], _now()
        db.commit()
        return run_dict(run)
    except Exception as e:  # never leak details; message is generic
        run.status, run.error_code, run.finished_at = "failed", "internal_error", _now()
        run.message = f"Unexpected error during import ({type(e).__name__})."
        db.commit()
        return run_dict(run)

    try:
        db.execute(delete(m.BrokerPositionRow))
        for p in snap.positions:
            db.add(m.BrokerPositionRow(sync_run_id=run.id, **p.__dict__))
        run.status = "success"
        run.report_date = snap.report_date
        run.generated_at = snap.generated_at.isoformat() if snap.generated_at else None
        run.accounts = snap.accounts
        run.fx_rates = [{"from": f, "to": t, "rate": str(r), "date": d.isoformat() if d else None}
                        for (f, t), (r, d) in sorted(snap.fx_rates.items())]
        run.skipped = [s.__dict__ for s in snap.skipped]
        run.warnings = snap.warnings
        run.positions_count = len(snap.positions)
        run.message = f"Imported {len(snap.positions)} position(s)" + (f", skipped {len(snap.skipped)}" if snap.skipped else "") + "."
        run.finished_at = _now()
        db.commit()
    except Exception as e:
        db.rollback()
        run = db.get(m.BrokerSyncRun, run.id)
        run.status, run.error_code, run.finished_at = "failed", "store_error", _now()
        run.message = f"Could not store the imported positions ({type(e).__name__}). Previous holdings kept."
        db.commit()
    return run_dict(run)


def run_dict(r: m.BrokerSyncRun) -> dict:
    return {"id": r.id, "source": r.source, "status": r.status, "error_code": r.error_code, "message": r.message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "generated_at": r.generated_at, "accounts": r.accounts, "positions_count": r.positions_count,
            "skipped": r.skipped or [], "warnings": r.warnings or [], "fx_rates": r.fx_rates or []}


def recent_runs(db: Session, n: int = 10) -> list[dict]:
    return [run_dict(r) for r in db.scalars(select(m.BrokerSyncRun).order_by(m.BrokerSyncRun.id.desc()).limit(n)).all()]


def last_success(db: Session) -> m.BrokerSyncRun | None:
    return db.scalar(select(m.BrokerSyncRun).where(m.BrokerSyncRun.status == "success")
                     .order_by(m.BrokerSyncRun.id.desc()).limit(1))


# --------------------------------------------------------------------------- valuation

class FlexFx:
    """FX from the broker report first; real ECB reference rates only where the report has none.
    Never uses synthetic rates."""

    def __init__(self, run: m.BrokerSyncRun, positions: list[m.BrokerPositionRow], external=None):
        self.rates: dict[tuple[str, str], tuple[Decimal, str | None]] = {}
        for r in run.fx_rates or []:
            self.rates[(r["from"], r["to"])] = (Decimal(r["rate"]), r["date"])
        self.used: dict[tuple[str, str], dict] = {}
        self.source = "portfolio_tracker" if run.source == "tracker" else FLEX_SOURCE
        self.external = external  # callable (f, t) -> {"rate", "date", "source"} | None

    def _direct(self, f: str, t: str) -> Decimal | None:
        if f == t:
            return Decimal(1)
        if (f, t) in self.rates:
            r, d = self.rates[(f, t)]
            self.used[(f, t)] = {"pair": f"{f}{t}", "rate": float(r), "date": d, "source": self.source, "is_synthetic": False}
            return r
        if (t, f) in self.rates:
            r, d = self.rates[(t, f)]
            self.used[(t, f)] = {"pair": f"{t}{f}", "rate": float(r), "date": d, "source": self.source, "is_synthetic": False}
            return Decimal(1) / r
        return None

    def rate(self, f: str, t: str, via: list[str]) -> Decimal | None:
        r = self._direct(f, t)
        if r is not None:
            return r
        for v in via:
            a, b = self._direct(f, v), self._direct(v, t)
            if a is not None and b is not None:
                return a * b
        if self.external is not None:
            x = self.external(f, t)
            if x is not None:
                self.used[(f, t)] = {"pair": f"{f}{t}", "rate": float(x["rate"]), "date": x["date"],
                                     "source": x["source"], "is_synthetic": False}
                return x["rate"]
        return None


def _q(x: Decimal) -> float:
    return float(x.quantize(Q2, rounding=ROUND_HALF_UP))


def _provenance(run: m.BrokerSyncRun) -> dict:
    if run.source == "tracker":  # Portfolio Tracker: prices from the workbook or entered in the app, valued on report_date
        stale = bool(run.report_date) and int(np.busday_count(run.report_date, date.today())) > settings.stale_after_business_days
        return {"source": "portfolio_tracker", "is_synthetic": False,
                "as_of": datetime.combine(run.report_date, datetime.min.time(), tzinfo=timezone.utc).isoformat() if run.report_date else None,
                "exchange_timezone": None, "is_delayed": True, "delay_minutes": None, "data_type": "portfolio_tracker_prices",
                "stale": stale, "latest_bar_date": run.report_date.isoformat() if run.report_date else None}
    as_of = None
    if run.generated_at:
        gen = datetime.fromisoformat(run.generated_at)
        # IBKR reports generation time in US Eastern time.
        as_of = gen.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc).isoformat()
    elif run.report_date:
        as_of = datetime.combine(run.report_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    stale = True
    if run.report_date:
        stale = int(np.busday_count(run.report_date, date.today())) > settings.stale_after_business_days
    return {"source": FLEX_SOURCE, "is_synthetic": False, "as_of": as_of, "exchange_timezone": "America/New_York (IBKR report time)",
            "is_delayed": True, "delay_minutes": None, "data_type": "end_of_day_broker_marks", "stale": stale,
            "latest_bar_date": run.report_date.isoformat() if run.report_date else None}


def _attach_analysis(db: Session, p: m.BrokerPositionRow, row: dict) -> None:
    """If real price history exists for this position (Tiingo US or EODHD Europe), add Fibonacci/trend/scores."""
    from research.market_data import eu_service
    from research.market_data.service import IBKR_US, real_listing_for_position
    from research.services.analysis import analyse_listing, load_bars, sparklines
    exch = (p.listing_exchange or "").upper()
    us = exch in IBKR_US and p.currency == "USD"
    if not us and exch not in eu_service.IBKR_EU:
        row["analysis_note"] = "Real price data for this exchange isn't available yet (US, Xetra, Euronext Amsterdam, SIX and LSE only)."
        return
    if not us and not eu_service.configured():
        row["analysis_note"] = "European prices need EODHD: add EODHD_API_KEY to .env (see docs/data-provider-evaluation.md)."
        return
    lst = real_listing_for_position(db, p)
    if lst is None:
        row["analysis_note"] = "No price history yet. Click 'Update prices' (Market Analysis) to download it."
        return
    a = analyse_listing(db, lst.id, include_series=False)
    if a["status"] != "ok":
        row["analysis_note"] = "No price history yet. Click 'Update prices' (Market Analysis) to download it."
        return
    fib = a["fibonacci"]
    row.update(
        analysis_available=True, analysis_note=None, analysis_provenance=a["provenance"],
        nearest_fibonacci=fib.get("nearest") if fib.get("status") == "ok" else None,
        fibonacci_status=fib.get("status"), fibonacci_direction=fib.get("direction"),
        classification={h: s["classification"] for h, s in a["scores"].items()},
        scores={h: s["total"] for h, s in a["scores"].items()},
        short_score_5_bars_ago=a["short_score_5_bars_ago"],
        spark=sparklines(load_bars(db, lst.id).df))
    row["listing"] = {**row["listing"], "id": lst.id}


def value_broker_portfolio(db: Session, base: str) -> dict:
    run = last_success(db)
    if run is None:
        return {"base_currency": base, "holdings_source": "tracker", "status": "not_synced",
                "totals": {"market_value": 0.0, "cost_basis": 0.0, "unrealised_pl": 0.0, "return_pct": None},
                "holdings": [], "fx_rates_used": [],
                "warnings": ["No holdings yet: upload your workbook in Portfolio Tracker (Data ▾ Import)."],
                "provenance": {"source": FLEX_SOURCE, "is_synthetic": False, "as_of": None, "exchange_timezone": None,
                               "is_delayed": True, "delay_minutes": None, "stale": True}}
    positions = db.scalars(select(m.BrokerPositionRow).where(m.BrokerPositionRow.sync_run_id == run.id)
                           .order_by(m.BrokerPositionRow.id)).all()
    from research.market_data import fx as real_fx
    on = run.report_date or date.today()
    fx = FlexFx(run, positions, external=lambda f, t: real_fx.rate(db, f, t, on))
    account_bases = sorted({b for b in (run.accounts or {}).values() if b})
    prov = _provenance(run)
    warnings = list(run.warnings or [])
    if run.skipped:
        warnings.append("Skipped (not supported yet): " + ", ".join(f"{s['symbol']} ({s['asset_category']})" for s in run.skipped))
    if prov["stale"]:
        warnings.append(f"Holdings prices dated {prov['latest_bar_date']} are more than {settings.stale_after_business_days} business days old: "
                        + ("update prices in Portfolio Tracker (Data ▾ Prices, or upload the workbook again)." if run.source == "tracker" else "sync IBKR again."))

    def build(target: str):
        rows, tot_mv, tot_cb, failed = [], Decimal(0), Decimal(0), []
        for p in positions:
            mult = p.multiplier or Decimal(1)
            mv_l = p.position_value if p.position_value is not None else p.quantity * p.mark_price * mult
            cb_l = p.cost_basis_money if p.cost_basis_money is not None else (
                p.quantity * p.cost_basis_price * mult if p.cost_basis_price is not None else None)
            acct_base = (run.accounts or {}).get(p.account_masked) or None
            r = None
            if p.currency == target:
                r = Decimal(1)
            elif acct_base and p.fx_rate_to_base:
                to_acct = Decimal(p.fx_rate_to_base) if p.currency != acct_base else Decimal(1)
                if acct_base == target:
                    r = to_acct
                else:
                    ab = fx.rate(acct_base, target, [])
                    r = to_acct * ab if ab is not None else None
                if r is not None and p.currency != acct_base:
                    fx.used[(p.currency, acct_base)] = {"pair": f"{p.currency}{acct_base}", "rate": float(p.fx_rate_to_base),
                                                        "date": p.report_date.isoformat() if p.report_date else None,
                                                        "source": FLEX_SOURCE, "is_synthetic": False}
            if r is None:
                r = fx.rate(p.currency, target, account_bases)
            row = {
                "holding_id": f"ibkr-{p.id}", "status": "ok", "account": p.account_masked,
                "listing": {"id": None, "ticker": p.symbol,
                            "exchange": IB_EXCHANGES.get((p.listing_exchange or "").upper(), (p.listing_exchange or "?", None))[0],
                            "exchange_name": IB_EXCHANGES.get((p.listing_exchange or "").upper(), (None, p.listing_exchange))[1],
                            "currency": p.currency, "name": p.description or p.symbol, "isin": p.isin,
                            "asset_class": "stock", "sector": None, "tracks": None, "is_holdable": True, "is_benchmark": False,
                            "conid": p.conid},
                "as_of": p.report_date.isoformat() if p.report_date else None,
                "quantity": float(p.quantity), "avg_cost": float(p.cost_basis_price) if p.cost_basis_price is not None else None,
                "price": float(p.mark_price),
                "market_value_local": _q(mv_l), "cost_basis_local": _q(cb_l) if cb_l is not None else None,
                "unrealised_pl_local": _q(p.unrealised_pnl if p.unrealised_pnl is not None else (mv_l - cb_l if cb_l is not None else Decimal(0))),
                "analysis_available": False,
                "analysis_note": "Charts and scores need real price history (market-data provider, Phase 2).",
                "nearest_fibonacci": None, "fibonacci_status": "no_price_history", "fibonacci_direction": None,
                "classification": {"short": None, "medium": None, "long": None},
                "scores": {"short": None, "medium": None, "long": None}, "short_score_5_bars_ago": None,
                "provenance": prov, "data_gaps": [],
            }
            _attach_analysis(db, p, row)
            if r is None:
                failed.append(p.symbol)
                row.update(status="fx_missing", market_value_base=None, cost_basis_base=None, unrealised_pl_base=None, return_pct=None)
            else:
                mv_b = mv_l * r
                cb_b = cb_l * r if cb_l is not None else None
                row.update(market_value_base=_q(mv_b), cost_basis_base=_q(cb_b) if cb_b is not None else None,
                           unrealised_pl_base=_q(mv_b - cb_b) if cb_b is not None else None,
                           return_pct=float(((mv_b - cb_b) / cb_b * 100).quantize(Q2)) if cb_b else None)
                tot_mv += mv_b
                tot_cb += cb_b if cb_b is not None else Decimal(0)
            rows.append(row)
        return rows, tot_mv, tot_cb, failed

    effective = base
    rows, tot_mv, tot_cb, failed = build(base)
    if failed and len(account_bases) == 1 and account_bases[0] != base:
        fx.used.clear()
        rows2, mv2, cb2, failed2 = build(account_bases[0])
        if not failed2:
            effective, rows, tot_mv, tot_cb, failed = account_bases[0], rows2, mv2, cb2, []
            warnings.append(f"Totals are shown in {effective} (your IBKR base currency): the IBKR report has no "
                            f"{effective}→{base} rate. Add the 'Conversion Rates' section to your Flex Query to see {base}.")
    if failed:
        warnings.append("No FX rate in the IBKR report for: " + ", ".join(failed) + ". These are excluded from totals.")

    ecb_used = [u for u in fx.used.values() if u["source"].startswith("ecb")]
    if ecb_used:
        warnings.append("The IBKR report has no rate for " + ", ".join(sorted({u["pair"] for u in ecb_used}))
                        + ": converted with the ECB reference rate of " + ", ".join(sorted({u["date"] for u in ecb_used}))
                        + " (ECB rates are for information purposes only).")
    pl = tot_mv - tot_cb
    return {
        "base_currency": effective, "requested_base_currency": base, "holdings_source": "tracker" if run.source == "tracker" else "ibkr_flex", "status": "ok",
        "sync": {"report_date": run.report_date.isoformat() if run.report_date else None, "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                 "accounts": run.accounts},
        "totals": {"market_value": _q(tot_mv), "cost_basis": _q(tot_cb), "unrealised_pl": _q(pl),
                   "return_pct": float((pl / tot_cb * 100).quantize(Q2)) if tot_cb else None},
        "holdings": rows,
        "fx_rates_used": sorted(fx.used.values(), key=lambda r: r["pair"]),
        "warnings": warnings,
        "provenance": prov,
    }
