"""Holdings from Portfolio Tracker: positions -> broker-style snapshot; tracking a stock from the Positions page."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from research.broker import tracker as tr
from research.db import models as m

from .test_market_data import fresh_db  # noqa: F401  (fixture re-used)

POS = {"as_of": "2026-11-06", "positions": [
    {"pool": "apple|USD", "stock": "Apple", "stock_key": "apple", "currency": "USD", "shares": 26.0, "price": 340.0, "pence": False,
     "avg_cost": 318.5, "cost_local": 8281.0, "rate": 1.0, "rate_date": None, "price_date": "2026-11-06"},
    {"pool": "beta|GBP", "stock": "Beta plc", "stock_key": "beta", "currency": "GBP", "shares": 100.0, "price": 250.0, "pence": True,
     "avg_cost": 200.0, "cost_local": 20000.0, "rate": 1.3, "rate_date": "2026-11-05", "price_date": "2026-11-06"},
    {"pool": "nope|USD", "stock": "No Ticker Inc", "stock_key": "nope", "currency": "USD", "shares": 5.0, "price": None, "pence": False,
     "avg_cost": 10.0, "cost_local": 50.0, "rate": 1.0, "rate_date": None, "price_date": None},
]}


def test_snapshot_from_tracker_positions():
    s = tr.snapshot_from_positions(POS, {"apple": "AAPL"}, mic_for=lambda t: "XNAS" if t == "AAPL" else None)
    a, b = s.positions
    assert (a.symbol, a.listing_exchange, a.quantity, a.mark_price) == ("AAPL", "NASDAQ", Decimal("26.0"), Decimal("340.0"))
    assert a.cost_basis_money == Decimal("8281.0") and a.unrealised_pnl == Decimal(str(26 * 340.0 - 8281.0))
    assert b.symbol == "Beta plc" and b.listing_exchange is None and b.mark_price == Decimal("2.5")  # pence -> pounds
    assert b.cost_basis_money == Decimal("200.0") and s.fx_rates[("GBP", "USD")] == (Decimal("1.3"), date(2026, 11, 5))
    assert [x.symbol for x in s.skipped] == ["No Ticker Inc"] and s.report_date == date(2026, 11, 6)
    assert any("no ticker" in w for w in s.warnings)
    assert tr.snapshot_from_positions(POS, {"apple": "AAPL"}).positions[0].listing_exchange == "NYSE"  # exchange unknown


def test_fingerprint_changes_with_positions_and_tickers():
    a = tr.fingerprint(POS, {"apple": "AAPL"})
    assert a == tr.fingerprint(POS, {"apple": "AAPL"}) != tr.fingerprint(POS, {"apple": "AAPL", "nope": "NOPE"})


def test_find_listing_is_real_data_only(client):
    assert client.get("/api/listings/find?ticker=AAPL").status_code == 404  # only the synthetic demo AAPL exists here


def test_track_from_portfolio_tracker(fresh_db, monkeypatch):  # noqa: F811
    """POST /api/track: add a US stock, download history, store its analysis, put it on the watchlist."""
    from fastapi.testclient import TestClient

    from research.db.session import get_db
    from research.main import app
    from research.market_data import service as md

    from .test_market_data import FakeTiingo, nyse_days

    session = nyse_days(date(2026, 11, 6), 1)[-1]
    fake = FakeTiingo(session)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    monkeypatch.setattr(md, "default_client", lambda: fake.client)
    monkeypatch.setattr(md, "configured", lambda: True)

    def _db():
        db = fresh_db()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = _db
    try:
        c = TestClient(app)
        r = c.post("/api/track", json={"ticker": "pypl", "exchange": "US", "watch": True})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ticker"] == "PYPL" and d["analysis_status"] == "ok" and d["watched"] is True
        assert d["summary"]["close"] > 0 and set(d["summary"]["scores"]) == {"short", "medium", "long"}
        assert d["download"]["bars_added"] > 200
        # stored: Fibonacci result saved, on the watchlist, findable by ticker, and tracked for later refreshes
        with fresh_db() as db:
            assert db.scalar(select(m.FibonacciResult.id).where(m.FibonacciResult.listing_id == d["listing_id"]).limit(1))
        assert c.get("/api/listings/find?ticker=PYPL").json()["listing_id"] == d["listing_id"]
        assert any(w["listing"]["id"] == d["listing_id"] for w in c.get("/api/watchlist").json()["rows"])
        # second time: no new listing, just an update
        assert c.post("/api/track", json={"ticker": "PYPL"}).json()["listing_id"] == d["listing_id"]
        assert c.post("/api/track", json={"ticker": "SAP", "exchange": "XFRA"}).status_code == 400
        monkeypatch.setattr(md, "configured", lambda: False)
        r = c.post("/api/track", json={"ticker": "AAPL"})
        assert r.status_code == 400 and "TIINGO_API_KEY" in r.json()["message"]
    finally:
        app.dependency_overrides.clear()
