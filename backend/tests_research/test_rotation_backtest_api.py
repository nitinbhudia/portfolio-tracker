"""Rotation backtest API and storage (ROTATION_BACKTEST_TASK.md §5.4)."""
from datetime import date

import pytest

from research.market_data import service as md
from research.services import analysis as an
from research.services import backtest as BT

from .test_market_data import fresh_db  # noqa: F401  (fixture re-used)
from .test_sectors import DistinctTiingo

PROV = ("source", "is_synthetic", "as_of", "exchange_timezone", "is_delayed", "delay_minutes", "stale")
URL = "/api/backtest/rotation/run"


def test_catalog(client):
    s = client.get("/api/backtest/rotation/strategies").json()
    ids = {x["id"]: x for x in s["strategies"]}
    assert ids["quadrant_hold"]["grid_size"] == 6 and ids["top_score"]["grid_size"] == 18
    assert {r["id"] for r in s["regions"]} == {"us", "eu"}
    assert s["disclaimer"].startswith("Past performance") and all(k in s["provenance"] for k in PROV)


@pytest.mark.parametrize("region,bench,n", [("us", "SPY", 11), ("eu", "EXSA", 19)])
def test_synthetic_single_run_stored_and_reproducible(client, region, bench, n):
    body = {"region": region, "strategy": "quadrant_hold", "params": {"hold": "improving_leading", "timeframe": "1m"}}
    a = client.post(URL, json=body).json()
    b = client.post(URL, json=body).json()
    assert a["id"] != b["id"] and a["result"] == b["result"] and a["input_hash"] == b["input_hash"]
    r = a["result"]
    assert r["kind"] == "rotation" and r["strategy"] == "rotation:quadrant_hold" and r["benchmark"] == bench
    assert len(r["sectors"]) == n and r["namespace"] == "synthetic" and r["excluded_sectors"] == []
    assert r["provenance"]["is_synthetic"] is True and any("SYNTHETIC" in x for x in r["notes"])
    assert any("approximation" in x for x in r["notes"]) and all(k in a["provenance"] for k in PROV)
    assert a["listing"]["ticker"] == bench and {"equal_weight", "time_in_sector_pct"} <= set(r["main"])
    runs = client.get("/api/backtest/runs").json()["runs"]
    top = runs[0]
    assert top["id"] == b["id"] and top["kind"] == "rotation" and top["ticker"] == f"{bench} sectors"
    assert top["main_equal_weight_pct"] == r["main"]["equal_weight"]["total_return_pct"]
    assert client.get(f"/api/backtest/runs/{a['id']}").json()["result"] == r


def test_walk_forward_discloses_combinations(client):
    r = client.post(URL, json={"region": "us", "strategy": "top_score", "mode": "walk_forward", "folds": 2}).json()["result"]
    assert r["combinations_tested"] == 18 * 3 and len(r["folds"]) == 2 and r["final_params"]["n"] in (2, 3, 5)


@pytest.mark.parametrize("body,msg", [
    ({"region": "mars", "strategy": "top_score"}, "unknown region"),
    ({"region": "us", "benchmark": "EXSA", "strategy": "top_score"}, "benchmark must be"),
    ({"strategy": "nope"}, "unknown rotation"),
    ({"strategy": "top_score", "params": {"n": 4}}, "n must be"),
    ({"strategy": "top_score", "mode": "walk_forward", "params": {"n": 2}}, "chooses parameters"),
    ({"strategy": "top_score", "holdout_pct": 0.6}, "holdout"),
    ({"strategy": "top_score", "commission_bps": 500}, "basis points"),
    ({"strategy": "top_score", "data": "real"}, "no real price history"),
])
def test_validation(client, body, msg):
    res = client.post(URL, json=body)
    assert res.status_code == 400 and msg in res.text


def test_real_data_path_never_mixed(fresh_db, monkeypatch):  # noqa: F811
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    with fresh_db() as db:
        md.refresh_all(db, DistinctTiingo(session).client)
        out = BT.run_rotation(db, "us", None, "auto", "top_score", "single", {"n": 3, "every": 10, "timeframe": "1m"},
                              5, 10, 0.2, 2)
        r = out["result"]
        assert r["namespace"] == "real" and r["provenance"]["is_synthetic"] is False and r["provenance"]["source"] == "tiingo"
        assert out["listing"]["namespace"] == "real" and not any("SYNTHETIC" in x for x in r["notes"])
        assert len(r["sectors"]) == 11 and r["main"]["metrics"]["trades"] > 0
        with pytest.raises(an.BadRequest, match="synthetic price history"):  # no synthetic sectors here: nothing filled in from real
            BT.run_rotation(db, "us", None, "synthetic", "top_score", "single", None, 5, 10, 0.2, 2)
