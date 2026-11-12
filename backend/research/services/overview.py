from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from research.data.universe import INDEX_STRIP
from research.db import models as m

from . import analysis as an
from .portfolio import merge_provenance, value_portfolio

DETERIORATION_POINTS = 10.0


def _pct(a: float, b: float | None) -> float | None:
    return None if not b else (a / b - 1) * 100


def index_strip(db: Session, sensitivity: str) -> list[dict]:
    out = []
    for sym in INDEX_STRIP:
        proxy = None
        from research.market_data.service import BENCHMARK_PROXIES, find_real_listing
        ptk, pmic, _ = BENCHMARK_PROXIES[sym]
        real = find_real_listing(db, ptk, pmic)
        if real is not None and db.scalar(select(m.PriceBar.id).where(m.PriceBar.listing_id == real.id).limit(1)):
            lst, proxy = real, sym
        else:
            lst = db.scalar(select(m.Listing).where(m.Listing.namespace == "synthetic", m.Listing.ticker == sym,
                                                    m.Listing.exchange_mic == "INDX"))
        if lst is None:
            continue
        a = an.analyse_listing(db, lst.id, sensitivity=sensitivity, include_series=True)
        if a["status"] != "ok":
            out.append({"listing": a["listing"], "status": a["status"], "provenance": a["provenance"]})
            continue
        s = a["series"]
        closes, dates = s["close"], s["dates"]
        last = closes[-1]
        year = dates[-1][:4]
        prior_year = [c for d, c in zip(dates, closes) if d[:4] < year]
        ytd_base = prior_year[-1] if prior_year else next(c for d, c in zip(dates, closes) if d[:4] == year)
        out.append({
            "listing": a["listing"], "status": "ok", "as_of": a["as_of"], "close": last,
            "proxy_for": proxy,
            "spark": an.sparklines(an.load_bars(db, lst.id).df),
            "change_1d_pct": _pct(last, closes[-2] if len(closes) > 1 else None),
            "change_1m_pct": _pct(last, closes[-22] if len(closes) > 21 else None),
            "change_ytd_pct": _pct(last, ytd_base),
            "classification": {h: sc["classification"] for h, sc in a["scores"].items()},
            "scores": {h: sc["total"] for h, sc in a["scores"].items()},
            "provenance": a["provenance"],
        })
    return out


def overview(db: Session, base: str, sensitivity: str, holdings_source: str = "synthetic") -> dict:
    if holdings_source in ("ibkr_flex", "tracker"):
        from research.broker.service import value_broker_portfolio
        p = value_broker_portfolio(db, base)
    else:
        p = value_portfolio(db, base, sensitivity)
    ok = [h for h in p["holdings"] if h["status"] == "ok"]
    ranked = sorted(ok, key=lambda h: h["return_pct"] if h["return_pct"] is not None else 0, reverse=True)
    near = [h for h in ok if h["nearest_fibonacci"] and h["nearest_fibonacci"]["distance_atr"] is not None
            and h["nearest_fibonacci"]["distance_atr"] <= 1.0]
    deteriorating = []
    for h in ok:
        now, before = h["scores"]["short"], h["short_score_5_bars_ago"]
        if now is not None and before is not None and before - now >= DETERIORATION_POINTS:
            deteriorating.append({**h, "short_score_change": now - before})
    strip = index_strip(db, sensitivity)
    return {
        "base_currency": p["base_currency"],
        "holdings_source": holdings_source,
        "portfolio_provenance": p["provenance"],
        "totals": p["totals"],
        "best": ranked[:3],
        "weakest": list(reversed(ranked[-3:])) if ranked else [],
        "near_fibonacci": near,
        "deteriorating_momentum": deteriorating,
        "deterioration_rule": f"short-term score fell >= {DETERIORATION_POINTS:g} points over 5 bars",
        "indices": strip,
        "fx_rates_used": p["fx_rates_used"],
        "warnings": p["warnings"],
        "provenance": merge_provenance([p["provenance"]] + [i["provenance"] for i in strip]),
        "indices_provenance": merge_provenance([i["provenance"] for i in strip]),
    }
