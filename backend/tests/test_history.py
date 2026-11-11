"""Price history (Tiingo stand-in, CSV), the day-by-day P/L engine and the performance view.

Made-up book after FIFO (tests/test_engine.py::book): Alpha Corp B2 10 @ 100 (2024-01-10) sold 2024-06-01 @ 120,
B4 5 @ 110 (2024-02-01) still held, sheet price 125; Beta plc 200 @ 250p (GBP) bought 2024-03-01, sold 2024-06-03 @ 300p;
Epsilon 2 @ 30 (2024-05-01) held, price 33. Hand-checked numbers below.
"""
from datetime import date

import pytest

from app.engine import history as H
from app.services import history as HS

from .test_api import client, upload  # noqa: F401  (fixture re-used)


def closes(start, end, price, split_on=None):
    out, d = [], start
    from datetime import timedelta
    while d <= end:
        if d.weekday() < 5:
            out.append((d, price, 2.0 if d == split_on else 1.0))
        d += timedelta(days=1)
    return out


@pytest.fixture
def tiingo(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "test")
    calls = []

    def fake(ticker, a, b):
        calls.append((ticker, a, b))
        if ticker == "NOPE":
            raise HS.TickerNotFound("Tiingo doesn't know the ticker NOPE.")
        if ticker == "LIMIT":
            raise HS.RateLimited("hourly allocation")
        return closes(a, b, 105.0)
    monkeypatch.setattr(HS, "FETCH", fake)
    HS._invalidate()
    return calls


def test_without_history_ends_at_todays_figures(client):  # noqa: F811
    upload(client)
    p = client.get("/api/performance").json()
    assert p["dates"][0] == "2024-01-10"
    assert p["value"][-1] == pytest.approx(5 * 125 + 2 * 33)  # sheet prices on the valuation date
    assert p["cost"][-1] == pytest.approx(5 * 110 + 2 * 30)
    realised = sum(s["gain_usd"] for s in client.get("/api/sales").json()["sales"] if s["gain_usd"] is not None)
    assert p["realised"][-1] == pytest.approx(realised) and p["total"][-1] == pytest.approx(realised + 81)
    assert p["estimated_now_pct"] == pytest.approx(100)  # no price history: everything carried from trade/sheet prices
    assert sum(mo["change_usd"] for mo in p["months"]) == pytest.approx(p["total"][-1])
    i = p["dates"].index("2024-04-01")  # Alpha 15 shares at their last trade price (110), Beta 200 @ 250p
    assert p["value"][i] - p["estimated"][i] == pytest.approx(0)
    gbp = 1.10 / 0.85  # test ECB rates: USD and GBP per EUR
    assert p["cost"][i] == pytest.approx(10 * 100 + 5 * 110 + 200 * 2.5 * gbp)
    assert p["value"][i] == pytest.approx(15 * 110 + 200 * 2.5 * gbp)  # Alpha at its last trade price (110)


def test_tiingo_download_values_with_daily_closes(client, tiingo):  # noqa: F811
    upload(client)
    assert client.put("/api/price-history/ticker/alpha corp", json={"ticker": "alph"}).json()["ticker"] == "ALPH"
    st = client.get("/api/price-history").json()
    a = next(x for x in st["pools"] if x["stock"] == "Alpha Corp")
    assert a["ticker"] == "ALPH" and a["source"] == "trades" and st["queue"] == 1
    r = client.post("/api/price-history/download?wait=true").json()
    assert r["fetched"] == 1 and r["remaining"] == 0
    (tk, frm, to), = tiingo
    assert tk == "ALPH" and frm == date(2024, 1, 3)  # a week before the first purchase
    st = client.get("/api/price-history").json()
    a = next(x for x in st["pools"] if x["stock"] == "Alpha Corp")
    assert a["source"] == "tiingo" and a["coverage"]["first"] == "2024-01-03"
    assert a["warnings"] == []  # trade prices 100/110 vs closes of 105: consistent
    p = client.get("/api/performance").json()
    i = p["dates"].index("2024-04-01")
    assert p["value"][i] - p["estimated"][i] == pytest.approx(15 * 105)  # Alpha valued at the daily close
    assert "Alpha Corp" in str(client.get("/api/stocks").json())  # setting the ticker kept the name
    # nothing left to fetch: a second run makes no requests
    assert client.post("/api/price-history/download?wait=true").json()["fetched"] == 0 and len(tiingo) == 1


def test_rate_limit_not_found_and_no_key(client, tiingo, monkeypatch):  # noqa: F811
    upload(client)
    client.put("/api/price-history/ticker/alpha corp", json={"ticker": "LIMIT"})
    client.put("/api/price-history/ticker/epsilon", json={"ticker": "NOPE"})
    r = client.post("/api/price-history/download?wait=true").json()
    assert r["waiting_until"] and r["remaining"] == 2 and r["fetched"] == 0  # LIMIT (first) paused the run
    st = client.get("/api/price-history").json()
    assert st["waiting_until"] and "hourly limit" in st["message"]
    client.put("/api/price-history/ticker/alpha corp", json={"ticker": "ALPH"})
    r = client.post("/api/price-history/download?wait=true").json()
    assert r["fetched"] == 1 and r["failed"] == 1 and r["waiting_until"] is None
    e = next(x for x in client.get("/api/price-history").json()["pools"] if x["stock"] == "Epsilon")
    assert e["fetch_status"] == "not_found" and "NOPE" in e["fetch_message"]
    assert client.put("/api/price-history/ticker/alpha corp", json={"ticker": "A B"}).status_code == 400
    assert client.put("/api/price-history/ticker/nobody", json={"ticker": "X"}).status_code == 404
    monkeypatch.delenv("TIINGO_API_KEY")
    r = client.post("/api/price-history/download?wait=true")
    assert r.status_code == 400 and "TIINGO_API_KEY" in r.json()["message"]


def test_csv_for_a_foreign_stock_and_warnings(client, tiingo):  # noqa: F811
    upload(client)
    beta = next(x for x in client.get("/api/price-history").json()["pools"] if x["stock"] == "Beta plc")
    assert beta["ticker_allowed"] is False and beta["pence"]
    csv = "Date,Price\n" + "\n".join(f"{d.isoformat()},{p}" for d, p, _ in closes(date(2024, 2, 26), date(2024, 6, 7), 260.0))
    r = client.post(f"/api/price-history/csv?pool={beta['pool']}", files={"file": ("b.csv", csv.encode(), "text/csv")}).json()
    assert r["rows"] > 60 and r["first"] == "2024-02-26"
    st = client.get("/api/price-history").json()
    assert next(x for x in st["pools"] if x["pool"] == beta["pool"])["source"] == "csv" and st["counts"]["csv"] == 1
    p = client.get("/api/performance").json()
    i = p["dates"].index("2024-04-01")
    # Beta now real (from the CSV): the estimated part on 2024-04-01 is Alpha only (15 shares at 110)
    assert p["estimated"][i] == pytest.approx(15 * 110)
    assert client.post("/api/price-history/csv?pool=nope|USD", files={"file": ("b.csv", b"x", "text/csv")}).status_code == 404
    assert client.post(f"/api/price-history/csv?pool={beta['pool']}", files={"file": ("b.csv", b"nothing here", "text/csv")}).status_code == 400
    client.delete(f"/api/price-history/csv?pool={beta['pool']}")
    assert client.get("/api/price-history").json()["counts"]["csv"] == 0


def test_split_and_wrong_ticker_warnings():
    x = {"open": True, "first": date(2024, 1, 10), "last": date(2024, 2, 1),
         "trades": [type("T", (), {"date": date(2024, 1, 10), "price": 100.0})()]}
    rows = [(date(2024, 1, 10), 50.0, 1.0), (date(2024, 3, 4), 25.0, 2.0)]
    w = HS._checks(x, rows)
    assert any("Split 2-for-1 on 2024-03-04" in s for s in w) and any("2.00×" in s for s in w)
    assert HS._checks(x, [(date(2024, 1, 10), 101.0, 1.0)]) == []


def test_price_line_and_months_by_hand():
    ln = H.price_line([(date(2024, 3, 4), 10.0), (date(2024, 3, 5), 11.0)], [(date(2024, 3, 1), 9.0), (date(2024, 3, 5), 99.0),
                                                                             (date(2024, 3, 20), 12.0)])
    assert ln.at(date(2024, 2, 1)) is None and ln.at(date(2024, 3, 2)) == (9.0, False)
    assert ln.at(date(2024, 3, 5)) == (11.0, True)  # history wins inside its range
    assert ln.at(date(2024, 3, 12)) == (11.0, True) and ln.at(date(2024, 3, 18)) == (11.0, False)  # stale after 10 days
    assert ln.at(date(2024, 3, 21)) == (12.0, False)
    s = {"dates": ["2024-01-30", "2024-01-31", "2024-02-29", "2024-03-01"], "total": [5, 10, 4, 7], "realised": [0, 0, 6, 6],
         "open_pl": [5, 10, -2, 1], "value": [100, 200, 150, 160]}
    mo = H.months(s)
    assert [(x["month"], x["change_usd"]) for x in mo] == [("2024-01", 10), ("2024-02", -6), ("2024-03", 3)]
    assert mo[1]["change_pct"] == pytest.approx(-3) and mo[1]["closed_usd"] == 6 and mo[1]["open_usd"] == -12
    assert H.business_days(date(2024, 3, 8), date(2024, 3, 10)) == [date(2024, 3, 8), date(2024, 3, 10)]


def test_odd_trade_prices_are_flagged():
    from types import SimpleNamespace as NS
    ts = [NS(pool="l|USD", stock="Lumentum", kind=k, date=date(2026, 7, d), row=r, price=p)
          for k, d, r, p in [("buy", 1, 1, 810.0), ("buy", 10, 2, 6.76), ("buy", 14, 3, 820.0), ("sell", 16, 4, 728.0), ("sell", 28, 5, 6.03)]]
    out = H.odd_prices(ts)
    assert len(out) == 2 and "sheet row 2" in out[0] and "sheet row 5" in out[1]


def test_a_sheet_trade_can_be_renamed(client):  # noqa: F811
    upload(client)
    r = client.put("/api/trades/B9/correct", json={"fields": {"name": "Zeta Inc"}})
    assert r.status_code == 200
    pools = {x["stock"] for x in client.get("/api/price-history").json()["pools"]}
    assert "Zeta Inc" in pools and "Epsilon" not in pools
    assert client.put("/api/trades/B9/correct", json={"fields": {"name": "  "}}).status_code == 400


def test_rename_a_sale_waiting_in_review(client):  # noqa: F811
    upload(client)
    # rename Alpha's purchase B2 first: its sale S3 (10 shares) is left without enough Alpha shares and goes to Review
    client.put("/api/trades/B2/correct", json={"fields": {"name": "Other Co"}})
    assert "S3" not in {t["id"] for t in client.get("/api/trades").json()["trades"]}
    assert client.put("/api/trades/S3/correct", json={"fields": {"name": "Other Co"}}).status_code == 200
    ts = {t["id"]: t for t in client.get("/api/trades").json()["trades"]}
    assert ts["S3"]["stock"] == "Other Co" and ts["B2"]["stock"] == "Other Co"
    assert client.put("/api/trades/S3/correct", json={"fields": {"shares": 10}}).status_code == 200  # a trade again
    assert client.put("/api/trades/S77/correct", json={"fields": {"name": "x"}}).status_code == 404
