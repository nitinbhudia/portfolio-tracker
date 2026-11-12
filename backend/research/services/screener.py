"""Screener: one row per listing with the latest analysis, for filtering and sorting in the UI."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from research.db import models as m

from . import analysis as an


def _pct(a: float, b: float | None) -> float | None:
    return None if not b else (a / b - 1) * 100


def _held_listing_ids(db: Session, holdings_source: str) -> set[int]:
    if holdings_source in ("ibkr_flex", "tracker"):
        from research.broker.service import last_success
        from research.market_data.service import real_listing_for_position
        run = last_success(db)
        if run is None:
            return set()
        ids = set()
        for p in db.scalars(select(m.BrokerPositionRow).where(m.BrokerPositionRow.sync_run_id == run.id)).all():
            lst = real_listing_for_position(db, p)
            if lst:
                ids.add(lst.id)
        return ids
    return set(db.scalars(select(m.Holding.listing_id)).all())


def screener(db: Session, sensitivity: str, holdings_source: str, namespace: str = "all") -> dict:
    q = select(m.Listing).order_by(m.Listing.namespace, m.Listing.id)
    if namespace in ("real", "synthetic"):
        q = q.where(m.Listing.namespace == namespace)
    held = _held_listing_ids(db, holdings_source)
    rows = []
    for lst in db.scalars(q).all():
        bars = an.load_bars(db, lst.id)
        a = an.compute_analysis(bars, sensitivity, include_series=False)
        base = {"listing": a["listing"], "namespace": lst.namespace, "held": lst.id in held,
                "provenance": a["provenance"], "status": a["status"]}
        if a["status"] != "ok":
            rows.append(base)
            continue
        df = bars.df
        closes, dates = df["close"].tolist(), df["date"].tolist()
        last = closes[-1]
        year = dates[-1].year
        prior = [c for d, c in zip(dates, closes) if d.year < year]
        ytd_base = prior[-1] if prior else next(c for d, c in zip(dates, closes) if d.year == year)
        ind = {k: v["value"] for k, v in a["latest"]["indicators"].items()}
        fib = a["fibonacci"]
        near = fib.get("nearest") if fib.get("status") == "ok" else None
        sc = a["scores"]
        rows.append({
            **base,
            "as_of": a["as_of"],
            "close": last,
            "change_1d_pct": _pct(last, closes[-2] if len(closes) > 1 else None),
            "change_1m_pct": _pct(last, closes[-22] if len(closes) > 21 else None),
            "change_ytd_pct": _pct(last, ytd_base),
            "score_short": sc["short"]["total"], "score_medium": sc["medium"]["total"], "score_long": sc["long"]["total"],
            "class_short": sc["short"]["classification"], "class_medium": sc["medium"]["classification"],
            "class_long": sc["long"]["classification"],
            "rsi14": ind.get("rsi14"), "macd_hist": ind.get("macd_hist"),
            "atr_pct": (ind["atr14"] / last * 100) if ind.get("atr14") else None,
            "relvol20": ind.get("relvol20"),
            "above_sma50": (last > ind["sma50"]) if ind.get("sma50") else None,
            "above_sma200": (last > ind["sma200"]) if ind.get("sma200") else None,
            "fib_direction": fib.get("direction"),
            "fib_nearest_ratio": near["ratio"] if near else None,
            "fib_nearest_price": near["price"] if near else None,
            "fib_distance_pct": near["distance_pct"] if near else None,
            "fib_distance_atr": near["distance_atr"] if near else None,
            "data_gaps": len(a["data_quality"]["gaps"]),
            "spark": an.sparklines(df),
        })
    return {"rows": rows, "sensitivity": sensitivity, "generated_for": date.today().isoformat(),
            "provenance": {"source": ",".join(sorted({r["provenance"]["source"] or "none" for r in rows})),
                           "is_synthetic": any(r["provenance"]["is_synthetic"] for r in rows),
                           "as_of": max((r["provenance"]["as_of"] for r in rows if r["provenance"]["as_of"]), default=None),
                           "exchange_timezone": "multiple", "is_delayed": False, "delay_minutes": None,
                           "stale": any(r["provenance"]["stale"] for r in rows), "mixed_sources": True}}
