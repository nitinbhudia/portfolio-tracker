"""Holdings from Portfolio Tracker: positions -> broker-style snapshot (no database needed)."""
from datetime import date
from decimal import Decimal

from research.broker import tracker as tr

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
