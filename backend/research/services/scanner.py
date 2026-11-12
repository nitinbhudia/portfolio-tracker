"""Opportunity scanner (PHASE_4_TASK.md) and watchlist.

A scan evaluates every listing in the database with the same engine as the analysis
page, stores one result row per listing, and reports honest coverage. Nothing here
recommends a trade: a triggered setup is a condition to research.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from research.core.hashing import stable_hash
from research.db import models as m
from research.engine import scoring, setups, swings

from . import analysis as an
from .screener import _held_listing_ids, _pct

HORIZONS = scoring.HORIZONS
VOLUME_WINDOW = 20


def _avg_volume(df) -> float | None:
    vol = df["volume"].to_numpy(dtype=float)[-VOLUME_WINDOW:]
    vol = vol[~np.isnan(vol)]
    return float(vol.mean()) if len(vol) == VOLUME_WINDOW else None


def _scan_row(lst: m.Listing, bars: an.Bars, sensitivity: str) -> dict:
    a = an.compute_analysis(bars, sensitivity, include_series=False)
    base = {"listing": a["listing"], "namespace": lst.namespace, "status": a["status"],
            "provenance": a["provenance"], "bars_available": a.get("bars_available", 0)}
    if a["status"] != "ok":
        return {**base, "triggered": [], "setups": None}
    df, sc = bars.df, a["scores"]
    closes = df["close"].tolist()
    last = closes[-1]
    is_index = lst.instrument.asset_class == "index"
    return {
        **base,
        "as_of": a["as_of"],
        "input_hash": a["input_hash"],
        "close": last,
        "change_1d_pct": _pct(last, closes[-2] if len(closes) > 1 else None),
        "change_1m_pct": _pct(last, closes[-22] if len(closes) > 21 else None),
        "avg_volume20": None if is_index else _avg_volume(df),
        **{f"score_{h}": sc[h]["total"] for h in HORIZONS},
        **{f"class_{h}": sc[h]["classification"] for h in HORIZONS},
        "rsi14": a["latest"]["indicators"]["rsi14"]["value"],
        "relvol20": a["latest"]["indicators"]["relvol20"]["value"],
        "triggered": a["setups"]["triggered"],
        "setups": a["setups"],
    }


def _coverage(rows: list[dict]) -> dict:
    by_source: Counter = Counter()
    by_exchange: dict[str, dict] = {}
    missing = []
    for r in rows:
        ok = r["status"] == "ok"
        src = "synthetic" if r["namespace"] == "synthetic" else (r["provenance"]["source"] or "none")
        by_source[src] += 1
        ex = by_exchange.setdefault(r["listing"]["exchange"], {"name": r["listing"]["exchange_name"], "total": 0, "scanned": 0})
        ex["total"] += 1
        ex["scanned"] += ok
        if not ok:
            missing.append({"ticker": r["listing"]["ticker"], "exchange": r["listing"]["exchange"],
                            "namespace": r["namespace"], "reason": r["status"],
                            "bars_available": r["bars_available"]})
    return {"by_source": dict(by_source), "by_exchange": by_exchange, "not_scanned": missing,
            "timeframe": "daily", "note": "Only instruments stored in this app are scanned. "
            "This is not a scan of any whole exchange."}


def run_scan(db: Session, sensitivity: str) -> m.ScanRun:
    k = swings.resolve_k(sensitivity)
    listings = db.scalars(select(m.Listing).order_by(m.Listing.namespace, m.Listing.id)).all()
    run = m.ScanRun(sensitivity=str(sensitivity), atr_multiple=k, setups_version=setups.SETUPS_VERSION,
                    score_version=scoring.SCORE_VERSION,
                    params_hash=stable_hash({"sensitivity": sensitivity, "atr_multiple": k,
                                             "setups": setups.PARAMS_HASH, "score": scoring.SCORE_VERSION}),
                    universe_size=len(listings), scanned=0, coverage={})
    db.add(run)
    db.flush()
    rows = []
    for lst in listings:
        row = _scan_row(lst, an.load_bars(db, lst.id), sensitivity)
        rows.append(row)
        db.add(m.ScanResult(run_id=run.id, listing_id=lst.id, status=row["status"],
                            bar_date=date.fromisoformat(row["as_of"]) if row.get("as_of") else None,
                            input_hash=row.get("input_hash"), triggered=row["triggered"], row=row))
    run.scanned = sum(r["status"] == "ok" for r in rows)
    run.coverage = _coverage(rows)
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return run


def _latest_bar_dates(db: Session) -> dict[int, date]:
    q = select(m.PriceBar.listing_id, func.max(m.PriceBar.date)).where(
        m.PriceBar.interval == an.INTERVAL).group_by(m.PriceBar.listing_id)
    return {lid: d for lid, d in db.execute(q).all()}


def _watchlist_notes(db: Session) -> dict[int, str | None]:
    return {w.listing_id: w.note for w in db.scalars(select(m.WatchlistItem)).all()}


def _ranks(rows: list[dict]) -> None:
    for h in HORIZONS:
        key = f"score_{h}"
        ranked = sorted((r for r in rows if r.get(key) is not None),
                        key=lambda r: (-r[key], r["listing"]["ticker"], r["listing"]["id"]))
        for i, r in enumerate(ranked, 1):
            r[f"rank_{h}"] = i


def merged_provenance(rows: list[dict]) -> dict:
    provs = [r["provenance"] for r in rows]
    return {"source": ",".join(sorted({p["source"] or "none" for p in provs})) or None,
            "is_synthetic": any(p["is_synthetic"] for p in provs),
            "as_of": max((p["as_of"] for p in provs if p["as_of"]), default=None),
            "exchange_timezone": "multiple", "is_delayed": any(bool(p["is_delayed"]) for p in provs),
            "delay_minutes": None, "stale": any(p["stale"] for p in provs), "mixed_sources": True}


def _utc(dt: datetime | None) -> str | None:
    """ISO timestamp in UTC. SQLite returns naive datetimes; they were stored as UTC."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def run_dict(run: m.ScanRun) -> dict:
    return {"id": run.id, "started_at": _utc(run.started_at), "finished_at": _utc(run.finished_at),
            "sensitivity": run.sensitivity, "atr_multiple": run.atr_multiple,
            "setups_version": run.setups_version, "score_version": run.score_version,
            "params_hash": run.params_hash, "universe_size": run.universe_size, "scanned": run.scanned,
            "coverage": run.coverage}


def latest_scan(db: Session, holdings_source: str) -> dict:
    run = db.scalar(select(m.ScanRun).where(m.ScanRun.finished_at.is_not(None)).order_by(m.ScanRun.id.desc()).limit(1))
    catalog = [{"id": sid, "name": name, "direction": d, "needs_volume": nv}
               for sid, (name, d, nv) in setups.SETUPS.items()]
    if run is None:
        return {"status": "no_scan", "setup_catalog": catalog, "rows": [],
                "provenance": {"source": None, "is_synthetic": None, "as_of": None, "exchange_timezone": None,
                               "is_delayed": None, "delay_minutes": None, "stale": True}}
    results = db.scalars(select(m.ScanResult).where(m.ScanResult.run_id == run.id)).all()
    held, notes = _held_listing_ids(db, holdings_source), _watchlist_notes(db)
    latest = _latest_bar_dates(db)
    current_ids = set(db.scalars(select(m.Listing.id)).all())
    scanned_ids = {r.listing_id for r in results}
    newer = []
    rows = []
    for res in results:
        row = dict(res.row)
        now = latest.get(res.listing_id)
        if now is not None and (res.bar_date is None or now > res.bar_date):
            newer.append(row["listing"]["ticker"])
        row["held"] = res.listing_id in held
        row["watchlisted"] = res.listing_id in notes
        rows.append(row)
    _ranks(rows)
    new_listings = len(current_ids - scanned_ids)
    removed = len(scanned_ids - current_ids)
    return {"status": "ok", "run": run_dict(run), "rows": rows, "setup_catalog": catalog,
            "freshness": {"out_of_date": bool(newer or new_listings or removed),
                          "newer_bars": sorted(newer), "new_listings": new_listings, "removed_listings": removed},
            "provenance": merged_provenance(rows)}


# ---------------------------------------------------------------- watchlist

def watchlist(db: Session, sensitivity: str, holdings_source: str) -> dict:
    items = db.scalars(select(m.WatchlistItem).order_by(m.WatchlistItem.added_at)).all()
    held = _held_listing_ids(db, holdings_source)
    rows = []
    for w in items:
        lst = db.get(m.Listing, w.listing_id)
        row = _scan_row(lst, an.load_bars(db, lst.id), sensitivity)
        rows.append({**row, "note": w.note, "added_at": _utc(w.added_at), "held": lst.id in held,
                     "watchlisted": True})
    prov = merged_provenance(rows) if rows else {"source": None, "is_synthetic": None, "as_of": None,
                                                  "exchange_timezone": None, "is_delayed": None,
                                                  "delay_minutes": None, "stale": False}
    return {"rows": rows, "sensitivity": sensitivity, "provenance": prov}


def add_to_watchlist(db: Session, listing_id: int, note: str | None) -> None:
    if db.get(m.Listing, listing_id) is None:
        raise an.NotFound(f"listing {listing_id} not found")
    item = db.scalar(select(m.WatchlistItem).where(m.WatchlistItem.listing_id == listing_id))
    if item is None:
        db.add(m.WatchlistItem(listing_id=listing_id, note=note))
    elif note is not None:
        item.note = note
    db.commit()


def update_note(db: Session, listing_id: int, note: str | None) -> None:
    item = db.scalar(select(m.WatchlistItem).where(m.WatchlistItem.listing_id == listing_id))
    if item is None:
        raise an.NotFound(f"listing {listing_id} is not on the watchlist")
    item.note = note
    db.commit()


def remove_from_watchlist(db: Session, listing_id: int) -> None:
    item = db.scalar(select(m.WatchlistItem).where(m.WatchlistItem.listing_id == listing_id))
    if item is not None:
        db.delete(item)
        db.commit()
