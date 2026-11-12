"""Portfolio valuation in Decimal with explicit, dated FX rates.

Amounts are stored in each listing's currency and converted to the base currency
using the FX rate dated on (or most recently before) the price date. Every rate
used is returned so the UI can show it.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from research.db import models as m

from . import analysis as an

SUPPORTED_BASE = ("USD", "EUR", "CHF")
Q2 = Decimal("0.01")


class FxMissing(LookupError):
    pass


class FxBook:
    """Converts via USD using stored EURUSD and USDCHF rates."""

    def __init__(self, db: Session, synthetic: bool = True):
        # The demo portfolio is valued with synthetic FX only; real (ECB) rates are never mixed in.
        self.db, self.synthetic = db, synthetic
        self.used: dict[tuple[str, str, str], dict] = {}

    def _rate(self, base: str, quote: str, on: date) -> tuple[Decimal, date, bool]:
        r = self.db.scalar(select(m.FxRate).where(m.FxRate.base == base, m.FxRate.quote == quote,
                                                  m.FxRate.date <= on, m.FxRate.is_synthetic.is_(self.synthetic))
                           .order_by(m.FxRate.date.desc()).limit(1))
        if r is None:
            raise FxMissing(f"no {base}{quote} rate on or before {on}")
        self.used[(base, quote, r.date.isoformat())] = {
            "pair": f"{base}{quote}", "rate": float(r.rate), "date": r.date.isoformat(),
            "source": r.source, "is_synthetic": r.is_synthetic}
        return Decimal(r.rate), r.date, r.is_synthetic

    def to_usd(self, amount: Decimal, ccy: str, on: date) -> Decimal:
        if ccy == "USD":
            return amount
        if ccy == "EUR":
            return amount * self._rate("EUR", "USD", on)[0]
        if ccy == "CHF":
            return amount / self._rate("USD", "CHF", on)[0]
        raise FxMissing(f"unsupported currency {ccy}")

    def from_usd(self, amount: Decimal, ccy: str, on: date) -> Decimal:
        if ccy == "USD":
            return amount
        if ccy == "EUR":
            return amount / self._rate("EUR", "USD", on)[0]
        if ccy == "CHF":
            return amount * self._rate("USD", "CHF", on)[0]
        raise FxMissing(f"unsupported currency {ccy}")

    def convert(self, amount: Decimal, ccy: str, to: str, on: date) -> Decimal:
        return amount if ccy == to else self.from_usd(self.to_usd(amount, ccy, on), to, on)


def _q(x: Decimal) -> float:
    return float(x.quantize(Q2, rounding=ROUND_HALF_UP))


def value_portfolio(db: Session, base: str = "USD", sensitivity: str = "medium") -> dict:
    if base not in SUPPORTED_BASE:
        raise an.BadRequest(f"base currency must be one of {SUPPORTED_BASE}")
    fx = FxBook(db)
    holdings = db.scalars(select(m.Holding).order_by(m.Holding.id)).all()
    rows, warnings = [], []
    tot_mv = tot_cost = Decimal(0)
    provs = []
    for hd in holdings:
        a = an.analyse_listing(db, hd.listing_id, sensitivity=sensitivity, include_series=False)
        provs.append(a["provenance"])
        lst = hd.listing
        if a["status"] != "ok":
            warnings.append(f"{lst.ticker}: {a['status']}")
            rows.append({"holding_id": hd.id, "listing": a["listing"], "status": a["status"]})
            continue
        price = Decimal(str(a["latest"]["close"]))
        on = date.fromisoformat(a["as_of"])
        qty, cost = Decimal(hd.quantity), Decimal(hd.avg_cost)
        mv_l, cb_l = qty * price, qty * cost
        try:
            mv_b, cb_b = fx.convert(mv_l, lst.currency, base, on), fx.convert(cb_l, lst.currency, base, on)
        except FxMissing as e:
            warnings.append(f"{lst.ticker}: {e}")
            rows.append({"holding_id": hd.id, "listing": a["listing"], "status": "fx_missing"})
            continue
        tot_mv += mv_b
        tot_cost += cb_b
        pl_b = mv_b - cb_b
        fib = a["fibonacci"]
        if a["provenance"]["stale"]:
            warnings.append(f"{lst.ticker}: price data is stale")
        if any(i["data_quality"] == "gap_in_window" for i in a["latest"]["indicators"].values()):
            warnings.append(f"{lst.ticker}: data gap inside an indicator window")
        rows.append({
            "holding_id": hd.id, "status": "ok", "listing": a["listing"], "as_of": a["as_of"],
            "quantity": float(qty), "avg_cost": float(cost), "price": float(price),
            "market_value_local": _q(mv_l), "cost_basis_local": _q(cb_l),
            "unrealised_pl_local": _q(mv_l - cb_l),
            "market_value_base": _q(mv_b), "cost_basis_base": _q(cb_b),
            "unrealised_pl_base": _q(pl_b),
            "return_pct": float((pl_b / cb_b * 100).quantize(Q2)) if cb_b else None,
            "nearest_fibonacci": fib.get("nearest") if fib.get("status") == "ok" else None,
            "fibonacci_status": fib.get("status"),
            "fibonacci_direction": fib.get("direction"),
            "classification": {h: s["classification"] for h, s in a["scores"].items()},
            "scores": {h: s["total"] for h, s in a["scores"].items()},
            "short_score_5_bars_ago": a["short_score_5_bars_ago"],
            "provenance": a["provenance"],
            "data_gaps": a["data_quality"]["gaps"],
            "spark": an.sparklines(an.load_bars(db, hd.listing_id).df),
        })
    pl = tot_mv - tot_cost
    return {
        "base_currency": base,
        "holdings_source": "synthetic",
        "status": "ok",
        "totals": {"market_value": _q(tot_mv), "cost_basis": _q(tot_cost),
                   "unrealised_pl": _q(pl),
                   "return_pct": float((pl / tot_cost * 100).quantize(Q2)) if tot_cost else None},
        "holdings": rows,
        "fx_rates_used": sorted(fx.used.values(), key=lambda r: (r["pair"], r["date"])),
        "warnings": warnings,
        "provenance": merge_provenance(provs),
    }


def merge_provenance(provs: list[dict]) -> dict:
    provs = [p for p in provs if p.get("as_of")]
    if not provs:
        return {"source": None, "is_synthetic": None, "as_of": None, "exchange_timezone": None,
                "is_delayed": None, "delay_minutes": None, "stale": True}
    return {
        "source": ",".join(sorted({p["source"] for p in provs})),
        "is_synthetic": any(p["is_synthetic"] for p in provs),
        "as_of": max(p["as_of"] for p in provs),
        "oldest_as_of": min(p["as_of"] for p in provs),
        "exchange_timezone": "multiple" if len({p["exchange_timezone"] for p in provs}) > 1
        else provs[0]["exchange_timezone"],
        "is_delayed": any(p["is_delayed"] for p in provs),
        "delay_minutes": max((p["delay_minutes"] for p in provs if p.get("delay_minutes") is not None), default=None),
        "mixed_sources": len({p["source"] for p in provs}) > 1,
        "data_type": next(iter({p.get("data_type") for p in provs})) if len({p.get("data_type") for p in provs}) == 1 else None,
        "price_adjustment": next(iter({p.get("price_adjustment") for p in provs})) if len({p.get("price_adjustment") for p in provs}) == 1 else None,
        "stale": any(p["stale"] for p in provs),
    }
