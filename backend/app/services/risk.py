"""Risk dashboard: today's holdings from Portfolio Tracker, their daily USD prices, and the S&P 500 (see engine/risk.py)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.engine import risk as RK

from . import benchmarks as BMS
from . import history as HS
from . import portfolio as P
from . import whatif as WS


def _usd_closes(db: Session, st, pool: str, currency: str, scale: float, ticker: str | None) -> list[tuple[date, float]]:
    rows = HS._series(db, f"csv:{pool}") or (HS._series(db, ticker) if ticker else [])
    if not rows:
        return []
    out = []
    for d, c in RK.adjust_splits(rows):
        r = st["rates"].usd(currency, d)
        if r is not None:
            out.append((d, c * scale * r.rate))
    return out


def view(db: Session, window: str = "1y") -> dict:
    if window not in RK.WINDOWS:
        raise P.BadRequest(f"window must be one of {', '.join(RK.WINDOWS)}")
    st = P._need(db)
    pos = P.positions(db)
    sectors = WS.confirmed_sectors(db)
    holdings, closes = [], {}
    for p in pos["positions"]:
        if not p["value_usd"] or p["shares"] <= 0:
            continue
        per: dict[str, float] = {}
        for lot in p["lots"]:
            per[lot["broker"] or "Unknown broker"] = per.get(lot["broker"] or "Unknown broker", 0.0) + lot["shares"] / p["shares"] * p["value_usd"]
        holdings.append(RK.Holding(p["pool"], p["stock"], p["value_usd"], sectors.get(p["stock_key"]), p["currency"], per))
        closes[p["pool"]] = _usd_closes(db, st, p["pool"], p["currency"], 0.01 if p["pence"] else 1.0,
                                        st["tickers"].get(p["stock_key"]) if p["currency"] == "USD" else None)
    spx = BMS.series(db).get("spx")
    market = list(zip(spx.dates, spx.closes)) if spx else None
    end = date.fromisoformat(pos["as_of"])
    unpriced = [p["stock"] for p in pos["positions"] if p["shares"] > 0 and not p["value_usd"]]
    return {"as_of": pos["as_of"], "window": window, "windows": list(RK.WINDOWS),
            "concentration": RK.concentration(holdings), "exposure": RK.exposure(holdings),
            "market": RK.market_risk(holdings, closes, market, end, window),
            "benchmark": "S&P 500" if spx else None, "unpriced": unpriced,
            "sectors_set": sum(1 for h in holdings if h.sector), "positions": len(holdings),
            "thresholds": {"large_pct": RK.LARGE, "very_large_pct": RK.VERY_LARGE}}
