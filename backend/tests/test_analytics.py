"""Analysis (SPEC.md §5, phase 2): statistics, months/years, timeline, XIRR, returns, per stock, capital API."""
from datetime import date as D

import pytest

from app.engine import analytics as AN
from app.engine.fifo import Match, Sale

from .test_api import client, upload  # noqa: F401  (fixture re-used)


def S(id_, d, gain, cost, days, stock="X", cur="USD", fx=0.0):
    return Sale(id=id_, row=1, sale_row=None, date=d, stock=stock, stock_key=stock.lower(), currency=cur, broker="B",
                shares=1, price=cost + gain, proceeds_local=cost + gain, proceeds_usd=cost + gain, sell_rate=1, sell_rate_date=None,
                matches=[Match("B1", 1, d, "B", 1, cost, cost, cost, 1, None, days)], cost_local=cost, cost_usd=cost,
                gain_local=gain, gain_usd=gain, gain_pct=gain / cost * 100, price_effect_usd=gain - fx, fx_effect_usd=fx,
                days_held=days, sheet_pl=None)


SALES = [S("a", D(2024, 1, 15), 100, 1000, 10), S("b", D(2024, 2, 20), -50, 500, 100),
         S("c", D(2025, 3, 1), 300, 1000, 400), S("d", D(2025, 3, 9), 0, 200, 20)]


def test_xirr_known_values():
    assert AN.xirr([(D(2023, 1, 1), -1000), (D(2024, 1, 1), 1100)]) == pytest.approx(0.10, abs=1e-6)
    assert AN.xirr([(D(2020, 1, 1), -1000), (D(2022, 1, 1), 1210.0)]) == pytest.approx(0.10, abs=1e-3)  # 731 days
    assert AN.xirr([(D(2023, 1, 1), -1000), (D(2024, 1, 1), 800)]) == pytest.approx(-0.20, abs=1e-6)
    assert AN.xirr([(D(2023, 1, 1), -1000)]) is None and AN.xirr([(D(2023, 1, 1), 5), (D(2024, 1, 1), 5)]) is None


def test_statistics_by_hand():
    st = AN.statistics(SALES)
    assert (st["wins"], st["losses"], st["breakeven"]) == (2, 1, 1)
    assert st["win_rate_pct"] == pytest.approx(50.0) and st["profit_factor"] == pytest.approx(400 / 50)
    assert st["avg_win_usd"] == pytest.approx(200) and st["avg_loss_usd"] == pytest.approx(-50)
    assert st["expectancy_usd"] == pytest.approx(350 / 4)
    assert st["avg_days_winners"] == pytest.approx(205) and st["avg_days_losers"] == pytest.approx(100)
    b = {x["label"]: x for x in st["by_holding_period"]}
    assert b["up to 1 month"]["sales"] == 2 and b["1–12 months"]["gain_usd"] == -50 and b["over 1 year"]["gain_usd"] == 300
    assert [x["id"] for x in st["best_sales"]][:2] == ["c", "a"] and st["worst_sales"][0]["id"] == "b"


def test_months_timeline_and_years():
    assert [(m["month"], m["gain_usd"]) for m in AN.months(SALES)] == [("2024-01", 100), ("2024-02", -50), ("2025-03", 300)]
    buys = [(D(2024, 1, 5), 1500.0), (D(2025, 1, 10), 1200.0)]
    tl = AN.timeline(buys, SALES, D(2025, 4, 30))
    by = {p.date: p for p in tl}
    assert by[D(2024, 1, 31)].invested_usd == pytest.approx(500) and by[D(2024, 1, 31)].realised_cum_usd == 100
    assert by[D(2024, 2, 29)].invested_usd == pytest.approx(0)
    assert by[D(2025, 3, 31)].invested_usd == pytest.approx(0) and by[D(2025, 4, 30)].realised_cum_usd == 350
    ys = {y["year"]: y for y in AN.years(SALES, tl, [(D(2023, 12, 1), 2000.0), (D(2025, 6, 1), 1000.0)])}
    assert ys[2024]["gain_usd"] == 50 and ys[2024]["avg_invested_usd"] == pytest.approx(500 / 12)
    assert ys[2024]["return_on_capital_pct"] == pytest.approx(50 / 2000 * 100)
    assert ys[2025]["capital_start_usd"] == pytest.approx(2050) and ys[2025]["capital_added_usd"] == 1000
    assert ys[2025]["return_on_capital_pct"] == pytest.approx(300 / 3050 * 100)


def test_returns_trade_xirr_and_capital():
    buys = [(D(2024, 1, 1), 1000.0)]
    sale = S("x", D(2025, 1, 1), 100, 1000, 366)
    r = AN.returns(buys, [sale], None, None, D(2025, 1, 1), None)
    assert r["money_in_shares"]["xirr_pct"] == pytest.approx((1.1 ** (365 / 366) - 1) * 100, abs=1e-4)  # 366 days (leap year)
    assert r["capital"] is None
    c = AN.returns(buys, [sale], 0.0, 0.0, D(2025, 1, 1), [(D(2024, 1, 1), 2000.0)])["capital"]
    assert c["net_usd"] == 2000 and c["end_value_usd"] == 2100 and c["simple_return_pct"] == pytest.approx(5.0)


def test_cash_block_is_read_as_recorded():
    from app.importer import live_portfolio as L

    from .fixture_book import make, position
    rows = {40: {"B": "Orginal", "C": "Dollar"}, 41: {"A": "Current", "B": 1000, "C": 1100, "D": "Cash"},
            42: {"A": "IBKR EUR 2024", "B": 500, "C": 550}, 43: {"B": "Tot Cash", "C": 1650}}
    w = L.read(make({2: position(2, D(2024, 1, 2), "A", 1, 1, 1, "Open")}, 20, rows))
    (b,) = w.cash
    assert b["header_row"] == 40 and [(r["label"], r["original"], r["usd"]) for r in b["rows"]] == \
        [("Current", 1000, 1100), ("IBKR EUR 2024", 500, 550)]
    assert b["totals"] == [{"row": 43, "label": "Tot Cash", "usd": 1650}]
    older = {k: v for k, v in w.to_dict().items() if k != "cash"}  # imports made before phase 2 have no cash block
    assert L.from_dict(older).cash == []


# ---------------------------------------------------------------- API

def test_analysis_by_stock_and_capital_api(client):  # noqa: F811
    upload(client)
    client.put("/api/review/P8", json={"action": "sell", "date": "2024-07-01", "price": 9.5})
    a = client.get("/api/analysis").json()
    assert a["statistics"]["sales"] == 3 and a["capital_entries"] == 0 and a["returns"]["capital"] is None
    assert "today's prices" in a["limits"] and a["years"][0]["year"] == 2024
    assert {x["label"] for x in a["allocation"]["by_currency"]} == {"USD"} and a["timeline"]
    # money invested at the end of the timeline = FIFO cost of what is still held
    assert a["timeline"][-1]["invested_usd"] == pytest.approx(a["open"]["cost_usd"])
    st = client.get("/api/by-stock").json()["stocks"]
    alpha = next(r for r in st if r["stock"] == "Alpha Corp")
    assert alpha["buys"] == 2 and alpha["sells"] == 1 and alpha["realised_usd"] == pytest.approx(200)
    assert alpha["status"] == "open" and alpha["open_shares"] == 5
    d = client.get("/api/by-stock/detail", params={"pool": alpha["pool"]}).json()
    assert [t["kind"] for t in d["trades"]] == ["buy", "buy", "sell"] and d["trades"][2]["matches"][0]["buy_row"] == 2
    assert client.get("/api/by-stock/detail", params={"pool": "nope|USD"}).status_code == 404
    assert client.post("/api/capital", json={"date": "2024-01-02", "amount": 0}).status_code == 400
    assert client.post("/api/capital", json={"date": "2099-01-02", "amount": 5}).status_code == 400
    assert client.post("/api/capital", json={"date": "2024-01-02", "amount": 5, "currency": "XYZ"}).status_code == 400
    c = client.post("/api/capital", json={"date": "2024-01-02", "amount": 10000, "currency": "EUR", "account": "IBKR"}).json()
    assert c["flows"][0]["usd"] == pytest.approx(11000.0)  # 1.10 USD per EUR in the fake rates
    a = client.get("/api/analysis").json()
    cap = a["returns"]["capital"]
    assert cap["net_usd"] == pytest.approx(11000) and cap["xirr_pct"] is not None and a["years"][0]["return_on_capital_pct"] is not None
    fid = c["flows"][0]["id"]
    assert client.delete(f"/api/capital/{fid}").json()["flows"] == []
    assert client.delete(f"/api/capital/{fid}").status_code == 404
