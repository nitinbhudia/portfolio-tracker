"""API: import, review, stocks, results, FX (SPEC.md §7)."""
from datetime import date, timedelta
from datetime import date as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db import models as m
from app.engine import fx as FX
from app.services import portfolio as P

from .test_engine import book


def fake_fx(curs, start):
    out, d = [], start
    while d <= date.today():
        if d.weekday() < 5:
            out.append((d, "USD", 1.10))
            out += [(d, c, {"GBP": 0.85, "CAD": 1.5}.get(c, 1.0)) for c in curs]
        d += timedelta(days=1)
    return out


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    m.init_db(eng)
    S = sessionmaker(bind=eng, expire_on_commit=False)

    def db():
        s = S()
        try:
            yield s
        finally:
            s.close()
    main.app.dependency_overrides[main.get_db] = db
    monkeypatch.setattr(P, "FX_FETCH", fake_fx)
    P._invalidate()
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()
    P._invalidate()


def upload(client, data=None, name="live.xlsx"):
    return client.post("/api/import", files={"file": (name, data if data is not None else book(), "application/octet-stream")})


def test_nothing_imported(client):
    assert client.get("/api/status").json() == {"imported": False}
    r = client.get("/api/sales")
    assert r.status_code == 404 and "upload your workbook" in r.json()["message"]


def test_import_status_and_reimport_is_idempotent(client):
    a = upload(client).json()
    assert a["imported"] and a["accounting"]["position_rows"] == 10 and a["review_pending"] == 5
    assert a["fx"]["status"] == "updated" and a["fx_latest"]
    b = upload(client).json()
    assert {k: b[k] for k in ("accounting", "review_pending", "trades")} == {k: a[k] for k in ("accounting", "review_pending", "trades")}


def test_bad_uploads(client):
    assert upload(client, b"").status_code == 400
    r = upload(client, b"\xd0\xcf\x11\xe0" + b"\0" * 600)
    assert r.status_code == 400 and "password-protected" in r.json()["message"]


def test_review_flow_and_decisions_survive_reimport(client):
    upload(client)
    items = {i["key"]: i for i in client.get("/api/review").json()["items"]}
    assert set(items) == {"P7", "P8", "P10", "P11", "S24"} and items["P8"]["actions"] == ["sell", "exclude"]
    assert client.put("/api/review/P8", json={"action": "sell", "date": "2024-07-01"}).status_code == 400
    assert client.put("/api/review/P8", json={"action": "fly"}).status_code == 400
    assert client.put("/api/review/P99", json={"action": "exclude"}).status_code == 404
    s = client.put("/api/review/P8", json={"action": "sell", "date": "2024-07-01", "price": 9.5}).json()
    assert s["review_pending"] == 3  # Delta's sale now uses Delta's purchase (row 11)
    s = client.post("/api/review/bulk", json={"kind": "unsold_buy", "action": "exclude"}).json()
    assert s["applied"] == 1 and s["review_pending"] == 2
    assert client.post("/api/review/bulk", json={"kind": "sale_missing_buy", "action": "exclude"}).status_code == 400
    upload(client)  # same rows, same fingerprints: decisions still apply
    assert client.get("/api/status").json()["review_pending"] == 2
    assert client.delete("/api/review/P8").json()["review_pending"] == 4
    resolved = client.get("/api/review?which=resolved").json()["items"]
    assert [i["key"] for i in resolved] == ["P7"]
    assert client.put("/api/review/P2", json={"action": "add_buy", "date": "2024-01-01", "price": 1}).status_code == 400


def test_results_sales_positions_and_check(client):
    upload(client)
    client.put("/api/review/P8", json={"action": "sell", "date": "2024-07-01", "price": 9.5})
    s = client.get("/api/sales").json()
    by = {x["id"]: x for x in s["sales"]}
    assert set(by) == {"S3", "S6", "S8"}
    assert by["S3"]["gain_usd"] == pytest.approx(200.0) and by["S3"]["sheet_pl"] == pytest.approx(200.0)
    assert by["S3"]["days_held"] == (D(2024, 6, 1) - D(2024, 1, 10)).days
    # Beta plc in pence: 200 × (300 − 250)/100 = 100 GBP, at USD/GBP = 1.10/0.85 on both dates
    assert by["S6"]["gain_local"] == pytest.approx(100.0) and by["S6"]["gain_usd"] == pytest.approx(100 * 1.10 / 0.85)
    assert s["by_year"][0]["year"] == 2024 and s["totals"]["sales"] == 3
    pos = client.get("/api/positions").json()
    names = {p["stock"]: p for p in pos["positions"]}
    assert set(names) == {"Alpha Corp", "Epsilon"}
    assert names["Alpha Corp"]["shares"] == 5 and names["Alpha Corp"]["price"] == 125
    assert names["Alpha Corp"]["unrealised_usd"] == pytest.approx(5 * (125 - 110))
    c = client.get("/api/check").json()
    assert c["sales_log"]["lines_matching"] == 2 and c["open_positions"]["stocks_matching"] == 2


def test_stock_merge_split_and_ticker(client):
    upload(client)
    st = client.get("/api/stocks").json()
    assert {g["display_name"] for g in st["stocks"]} >= {"Alpha Corp", "Epsilon"}
    assert client.post("/api/stocks/merge", json={"name_keys": ["alpha corp"]}).status_code == 400
    st = client.post("/api/stocks/merge", json={"name_keys": ["alpha corp", "epsilon"], "display_name": "Alpha"}).json()
    alpha = next(g for g in st["stocks"] if g["display_name"] == "Alpha")
    assert {n["name_key"] for n in alpha["names"]} == {"alpha corp", "epsilon"}
    pos = client.get("/api/positions").json()["positions"]
    assert [p["stock"] for p in pos] == ["Alpha"] and pos[0]["shares"] == 7
    st = client.put("/api/stocks/alpha corp", json={"ticker": "alph"}).json()
    assert next(g for g in st["stocks"] if g["group_key"] == "alpha corp")["ticker"] == "ALPH"
    st = client.post("/api/stocks/split", json={"name_key": "epsilon"}).json()
    assert len([g for g in st["stocks"] if g["display_name"] in ("Alpha", "Epsilon")]) == 2


def test_fx_failure_is_reported_not_invented(client, monkeypatch):
    def boom(curs, start):
        raise FX.FxError("Could not reach the ECB data service (ConnectError).")
    monkeypatch.setattr(P, "FX_FETCH", boom)
    r = upload(client).json()
    assert r["fx"]["status"] == "error"
    by = {x["id"]: x for x in client.get("/api/sales").json()["sales"]}
    assert by["S3"]["gain_usd"] == pytest.approx(200.0)  # USD needs no rate
    assert by["S6"]["gain_usd"] is None and "No ECB rate" in by["S6"]["problems"][0]
