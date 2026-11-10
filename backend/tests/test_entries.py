"""Phase 3: trades entered in the app, fees, corrections, dividends, prices (SPEC.md §5.9, §8.3). Hand-checked numbers.

The made-up book (tests/test_engine.py::book): Alpha Corp purchase row 2 (10 @ 100, 2024-01-10), sale row 3 (10 @ 120,
2024-06-01), open row 4 (5 @ 110, 2024-02-01, sheet price 125); Epsilon open row 9 (2 @ 30, price 33). USD = 1.10 per EUR.
"""
from datetime import date as D

import pytest

from .fixture_book import make, position
from .test_api import client, upload  # noqa: F401  (fixture re-used)

T = {"kind": "sell", "date": "2024-08-01", "name": "Alpha Corp", "shares": 5, "price": 130, "currency": "USD", "fee": 2, "broker": "IBKR"}


def sales(c):
    return {s["id"]: s for s in c.get("/api/sales").json()["sales"]}


def pos(c):
    return {p["stock"]: p for p in c.get("/api/positions").json()["positions"]}


def test_app_trades_join_fifo_and_can_be_edited(client):  # noqa: F811
    upload(client)
    r = client.post("/api/trades", json=T).json()
    mid = next(t["id"] for t in r["trades"] if t["source"] == "app")
    s = sales(client)[mid]
    assert s["matches"][0]["buy_row"] == 4 and s["gain_usd"] == pytest.approx(5 * 130 - 2 - 5 * 110)  # 98
    assert "Alpha Corp" not in pos(client) and s["sheet_pl"] is None
    client.put(f"/api/trades/{mid}", json={**T, "price": 120, "fee": 0})
    assert sales(client)[mid]["gain_usd"] == pytest.approx(5 * 10)
    assert client.delete(f"/api/trades/{mid}").status_code == 200 and pos(client)["Alpha Corp"]["shares"] == 5
    for bad in ({**T, "kind": "swap"}, {**T, "shares": 0}, {**T, "date": "2099-01-01"}, {**T, "currency": "XYZ"}, {**T, "name": " "}):
        assert client.post("/api/trades", json=bad).status_code == 400
    assert client.put("/api/trades/B2", json=T).status_code == 400  # sheet trades are corrected, not edited
    assert client.delete("/api/trades/M999").status_code == 404


def test_new_stock_needs_a_price(client):  # noqa: F811
    upload(client)
    client.post("/api/trades", json={**T, "kind": "buy", "name": "Omega Inc", "shares": 10, "price": 20, "fee": 1})
    o = pos(client)["Omega Inc"]
    assert o["price"] is None and o["cost_usd"] == pytest.approx(201) and o["unrealised_usd"] is None
    client.put("/api/prices", params={"pool": o["pool"]}, json={"price": 25})
    o = pos(client)["Omega Inc"]
    assert o["price"] == 25 and o["price_source"] == "typed in the app" and o["unrealised_usd"] == pytest.approx(250 - 201)


def test_fees_on_sheet_trades(client):  # noqa: F811
    upload(client)
    client.put("/api/trades/B2/fee", json={"fee": 3})
    client.put("/api/trades/S3/fee", json={"fee": 1})
    assert sales(client)["S3"]["gain_usd"] == pytest.approx(200 - 3 - 1)
    client.put("/api/trades/B2/fee", json={"fee": 0})  # 0 removes it
    assert sales(client)["S3"]["gain_usd"] == pytest.approx(199)
    assert client.put("/api/trades/B99/fee", json={"fee": 1}).status_code == 404
    assert client.put("/api/trades/M1/fee", json={"fee": 1}).status_code == 400
    assert client.put("/api/trades/S3/fee", json={"fee": -1}).status_code == 400
    # the check against the sheet ignores fees (the sheet has none)
    assert client.get("/api/check").json()["sales_log"]["lines_matching"] == 2


def test_corrections_to_sheet_trades(client):  # noqa: F811
    upload(client)
    client.put("/api/trades/S3/correct", json={"fields": {"live_price": 125, "sale_date": "2024-06-10"}})
    s = sales(client)["S3"]
    assert s["gain_usd"] == pytest.approx(10 * 125 - 1000) and s["date"] == "2024-06-10"
    client.put("/api/trades/B4/correct", json={"fields": {"shares": 6}})
    assert pos(client)["Alpha Corp"]["shares"] == 6
    assert client.put("/api/trades/B4/correct", json={"fields": {"sale_date": "2024-06-10"}}).status_code == 400
    assert client.put("/api/trades/B4/correct", json={"fields": {"broker": "x"}}).status_code == 400
    assert client.put("/api/trades/M3/correct", json={"fields": {"shares": 1}}).status_code == 404
    upload(client)  # same rows: corrections are kept
    assert pos(client)["Alpha Corp"]["shares"] == 6


def test_dividends_count_in_returns_years_and_per_stock(client):  # noqa: F811
    upload(client)
    before = client.get("/api/analysis").json()
    d = client.post("/api/dividends", json={"date": "2024-07-01", "name": "alpha  corp", "amount": 10, "currency": "EUR", "tax": 1.5}).json()
    assert d["total_usd"] == pytest.approx(11.0) and d["by_year"] == [{"year": 2024, "usd": pytest.approx(11.0)}]
    a = client.get("/api/analysis").json()
    assert a["returns"]["dividends_usd"] == pytest.approx(11.0)
    assert a["returns"]["total_gain_usd"] == pytest.approx(before["returns"]["total_gain_usd"] + 11.0)
    y = next(y for y in a["years"] if y["year"] == 2024)
    assert y["dividends_usd"] == pytest.approx(11.0) and y["income_usd"] == pytest.approx(y["gain_usd"] + 11.0)
    alpha = next(r for r in client.get("/api/by-stock").json()["stocks"] if r["stock"] == "Alpha Corp")
    assert alpha["dividends_usd"] == pytest.approx(11.0)
    assert client.post("/api/dividends", json={"date": "2024-07-01", "name": "A", "amount": 0, "currency": "USD"}).status_code == 400
    assert client.delete(f"/api/dividends/{d['dividends'][0]['id']}").json()["total_usd"] == 0


def test_prices_typed_and_from_an_updated_workbook(client):  # noqa: F811
    upload(client)
    alpha = pos(client)["Alpha Corp"]
    old = client.put("/api/prices", params={"pool": alpha["pool"]}, json={"price": 99, "date": "2024-12-01"}).json()
    assert next(r for r in old["prices"] if r["stock"] == "Alpha Corp")["price"] == 125  # older than the workbook: not used
    p = client.put("/api/prices", params={"pool": alpha["pool"]}, json={"price": 140}).json()  # today
    row = next(r for r in p["prices"] if r["stock"] == "Alpha Corp")
    assert row["price"] == 140 and row["history"][0]["price"] == 140
    assert client.put("/api/prices", params={"pool": "nope|USD"}, json={"price": 1}).status_code == 404
    for h in row["history"]:
        client.delete(f"/api/prices/{h['id']}")
    assert pos(client)["Alpha Corp"]["price"] == 125  # back to the sheet's price
    newer = make({4: position(4, D(2024, 2, 1), "Alpha Corp", 5, 110, 150, "Open"),
                  9: position(9, D(2024, 5, 1), "Epsilon", 2, 30, 31, "Open"),
                  10: position(10, D(2024, 5, 1), "Zed New", 2, 30, 31, "Open")}, 20, {})
    r = client.post("/api/prices/workbook", files={"file": ("newer.xlsx", newer, "application/octet-stream")}).json()
    assert r["updated"] == 2 and r["not_held"] == ["Zed New (USD)"]
    p = pos(client)
    assert p["Alpha Corp"]["price"] == 150 and "newer.xlsx" in p["Alpha Corp"]["price_source"]
    assert client.get("/api/status").json()["review_pending"] == 5  # trades and review untouched
