"""Backtest API and storage (PHASE_7_TASK.md §4, §7.6)."""
import pytest

PROV = ("source", "is_synthetic", "as_of", "exchange_timezone", "is_delayed", "delay_minutes", "stale")


def _lid(client, ticker):
    return next(x["id"] for x in client.get("/api/listings").json()["listings"] if x["ticker"] == ticker)


def test_strategies_catalog(client):
    s = client.get("/api/backtest/strategies").json()
    ids = {x["id"]: x for x in s["strategies"]}
    assert set(ids) == {"ma_cross", "rsi_reversion", "macd_cross", "fib_pullback", "setup_hold"}
    assert ids["ma_cross"]["grid_size"] == 8 and ids["setup_hold"]["grid_size"] == 18
    assert s["defaults"] == {"commission_bps": 5.0, "slippage_bps": 10.0, "holdout_pct": 0.2, "folds": 3, "mode": "single"}
    assert s["disclaimer"] == "Past performance does not guarantee future results."
    for k in PROV:
        assert k in s["provenance"]


def test_single_run_is_stored_and_reproducible(client):
    lid = _lid(client, "AAPL")
    body = {"listing_id": lid, "strategy": "ma_cross", "mode": "single", "params": {"fast": 20, "slow": 50}}
    a = client.post("/api/backtest/run", json=body).json()
    b = client.post("/api/backtest/run", json=body).json()
    assert a["id"] != b["id"] and a["result"] == b["result"]
    assert a["input_hash"] == b["input_hash"] and a["params_hash"] == b["params_hash"]
    r = a["result"]
    assert r["final_params"] == {"fast": 20, "slow": 50} and r["combinations_tested"] == 1
    assert r["provenance"]["is_synthetic"] is True and any("SYNTHETIC" in n for n in r["notes"])
    assert r["disclaimer"].startswith("Past performance")
    for k in PROV:
        assert k in a["provenance"]
    got = client.get(f"/api/backtest/runs/{a['id']}").json()
    assert got["result"] == r and got["listing"]["ticker"] == "AAPL"
    lst = client.get("/api/backtest/runs").json()
    assert lst["runs"][0]["id"] == b["id"] and lst["runs"][0]["mode"] == "single" and "provenance" in lst


def test_walk_forward_run(client):
    lid = _lid(client, "MSFT")
    out = client.post("/api/backtest/run", json={"listing_id": lid, "strategy": "rsi_reversion", "mode": "walk_forward",
                                                 "folds": 2, "holdout_pct": 0.2}).json()
    r = out["result"]
    assert r["combinations_tested"] == 9 * 3 and len(r["folds"]) == 2
    assert r["main"]["label"].startswith("Out-of-sample") and r["holdout"]["start_date"] > r["main"]["end_date"]
    assert r["final_params"] in [g["params"] for g in r["final_selection"]["grid_scores"]]


def test_index_and_costs(client):
    lid = _lid(client, "SPX")
    r = client.post("/api/backtest/run", json={"listing_id": lid, "strategy": "macd_cross", "commission_bps": 0,
                                               "slippage_bps": 0}).json()["result"]
    assert r["costs"] == {"commission_bps": 0.0, "slippage_bps": 0.0}
    assert any("Indices can't be bought" in n for n in r["notes"])


@pytest.mark.parametrize("body,status", [
    ({"strategy": "nope"}, 400),
    ({"strategy": "ma_cross", "params": {"fast": 7}}, 400),
    ({"strategy": "ma_cross", "commission_bps": 500}, 400),
    ({"strategy": "ma_cross", "mode": "walk_forward", "folds": 6}, 400),  # not enough history on 600 synthetic bars
    ({"strategy": "ma_cross", "holdout_pct": 0.9}, 400),
])
def test_bad_requests(client, body, status):
    r = client.post("/api/backtest/run", json={"listing_id": _lid(client, "AAPL"), **body})
    assert r.status_code == status, r.text


def test_missing_listing_and_delete(client):
    assert client.post("/api/backtest/run", json={"listing_id": 99999, "strategy": "ma_cross"}).status_code == 404
    rid = client.post("/api/backtest/run", json={"listing_id": _lid(client, "SAP"), "strategy": "macd_cross"}).json()["id"]
    assert all(x["id"] != rid for x in client.delete(f"/api/backtest/runs/{rid}").json()["runs"])
    assert client.get(f"/api/backtest/runs/{rid}").status_code == 404
