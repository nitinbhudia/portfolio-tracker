"""Opportunity scanner + watchlist API (PHASE_4_TASK.md §8)."""
from datetime import timedelta

from sqlalchemy import select

from research.db import models as m


def _strip(rows):
    """Comparable view of scan rows (drops per-request fields)."""
    return sorted(((r["listing"]["id"], r["status"], r.get("input_hash"), tuple(r["triggered"]),
                    r.get("score_short"), r.get("score_medium"), r.get("score_long")) for r in rows))


def test_scanner_empty_state_then_run(client):
    with client.Session() as db:  # make sure no earlier test left a run behind
        assert db.scalar(select(m.ScanRun.id).limit(1)) is None
    r = client.get("/api/scanner").json()
    assert r["status"] == "no_scan" and r["rows"] == [] and "provenance" in r
    assert len(r["setup_catalog"]) == 12
    names = [c["name"] for c in r["setup_catalog"]]
    assert not any(a != b and b in a for a in names for b in names)  # UI filters by name substring

    out = client.post("/api/scanner/run").json()
    assert out["status"] == "ok"
    run = out["run"]
    with client.Session() as db:
        n_listings = len(db.scalars(select(m.Listing.id)).all())
        stored = db.scalars(select(m.ScanResult).where(m.ScanResult.run_id == run["id"])).all()
    assert run["universe_size"] == n_listings == len(out["rows"]) == len(stored)
    assert run["scanned"] == sum(r["status"] == "ok" for r in out["rows"])
    assert out["freshness"]["out_of_date"] is False
    assert run["finished_at"].endswith("+00:00")
    p = out["provenance"]
    for k in ("source", "is_synthetic", "as_of", "exchange_timezone", "is_delayed", "delay_minutes", "stale"):
        assert k in p
    assert p["is_synthetic"] is True


def test_coverage_counts(client):
    out = client.get("/api/scanner").json()
    cov = out["run"]["coverage"]
    assert sum(cov["by_source"].values()) == out["run"]["universe_size"]
    assert sum(e["total"] for e in cov["by_exchange"].values()) == out["run"]["universe_size"]
    assert sum(e["scanned"] for e in cov["by_exchange"].values()) == out["run"]["scanned"]
    assert len(cov["not_scanned"]) == out["run"]["universe_size"] - out["run"]["scanned"]
    assert "not a scan of any whole exchange" in cov["note"]


def test_rows_match_analysis_endpoint(client):
    rows = client.get("/api/scanner").json()["rows"]
    row = next(r for r in rows if r["listing"]["ticker"] == "AAPL")
    a = client.get(f"/api/listings/{row['listing']['id']}/analysis").json()
    assert row["setups"] == a["setups"]
    assert row["score_short"] == a["scores"]["short"]["total"]
    assert row["input_hash"] == a["input_hash"]


def test_ranking_by_score_then_ticker(client):
    rows = [r for r in client.get("/api/scanner").json()["rows"] if r.get("score_medium") is not None]
    ranked = sorted(rows, key=lambda r: r["rank_medium"])
    assert [r["rank_medium"] for r in ranked] == list(range(1, len(rows) + 1))
    for a, b in zip(ranked, ranked[1:]):
        assert (a["score_medium"], b["listing"]["ticker"]) >= (b["score_medium"], a["listing"]["ticker"])


def test_indices_volume_setups_not_applicable(client):
    rows = client.get("/api/scanner").json()["rows"]
    spx = next(r for r in rows if r["listing"]["ticker"] == "SPX")
    st = {s["id"]: s["status"] for s in spx["setups"]["setups"]}
    assert st["breakout"] == st["accumulation"] == "not_applicable"
    assert spx["avg_volume20"] is None


def test_rescan_on_unchanged_data_is_identical(client):
    first = client.get("/api/scanner").json()
    second = client.post("/api/scanner/run").json()
    assert second["run"]["id"] != first["run"]["id"]
    assert second["run"]["params_hash"] == first["run"]["params_hash"]
    assert _strip(second["rows"]) == _strip(first["rows"])


def test_out_of_date_when_new_bar_arrives(client):
    out = client.get("/api/scanner").json()
    row = next(r for r in out["rows"] if r["listing"]["ticker"] == "MSFT")
    lid = row["listing"]["id"]
    with client.Session() as db:
        last = db.scalar(select(m.PriceBar).where(m.PriceBar.listing_id == lid).order_by(m.PriceBar.date.desc()).limit(1))
        extra = m.PriceBar(listing_id=lid, interval="1d", date=last.date + timedelta(days=3), open=last.open,
                           high=last.high, low=last.low, close=last.close, volume=last.volume,
                           source=last.source, is_synthetic=True)
        db.add(extra)
        db.commit()
        extra_id = extra.id
    try:
        fr = client.get("/api/scanner").json()["freshness"]
        assert fr["out_of_date"] is True and fr["newer_bars"] == ["MSFT"]
        assert client.post("/api/scanner/run").json()["freshness"]["out_of_date"] is False
    finally:
        with client.Session() as db:
            db.delete(db.get(m.PriceBar, extra_id))
            db.commit()
        client.post("/api/scanner/run")


def test_bad_sensitivity_is_400(client):
    assert client.post("/api/scanner/run", json={"sensitivity": "extreme"}).status_code == 400


def test_watchlist_add_note_remove(client):
    lid = next(x["id"] for x in client.get("/api/listings").json()["listings"] if x["ticker"] == "NVDA")
    empty = client.get("/api/watchlist").json()
    assert empty["rows"] == [] and "provenance" in empty

    r = client.post("/api/watchlist", json={"listing_id": lid, "note": "  check the 0.618  "}).json()
    assert [x["listing"]["ticker"] for x in r["rows"]] == ["NVDA"]
    assert r["rows"][0]["note"] == "check the 0.618"
    assert r["rows"][0]["setups"]["version"] == "setups-v1"
    assert r["provenance"]["is_synthetic"] is True

    # adding twice keeps a single item
    assert len(client.post("/api/watchlist", json={"listing_id": lid}).json()["rows"]) == 1
    scan = client.get("/api/scanner").json()["rows"]
    assert next(x for x in scan if x["listing"]["id"] == lid)["watchlisted"] is True

    r = client.patch(f"/api/watchlist/{lid}", json={"note": "updated"}).json()
    assert r["rows"][0]["note"] == "updated"
    assert client.patch(f"/api/watchlist/{lid}", json={"note": "x" * 501}).status_code == 422

    assert client.delete(f"/api/watchlist/{lid}").json()["rows"] == []
    assert client.patch(f"/api/watchlist/{lid}", json={"note": "gone"}).status_code == 404
    assert client.post("/api/watchlist", json={"listing_id": 99999}).status_code == 404
