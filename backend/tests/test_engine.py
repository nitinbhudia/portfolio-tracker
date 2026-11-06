"""Importer, rebuild, FIFO, FX and check figures (SPEC.md §7.1–7.3), on made-up workbooks."""
from datetime import date

import pytest

from app.engine import check as C
from app.engine import fifo as FIFO
from app.engine import fx as FX
from app.engine import names
from app.engine import rebuild as R
from app.importer import live_portfolio as L

from .fixture_book import make, position, sale

D = date


def rates(**per_eur):
    """Flat ECB rates (units per EUR) from 2023-01-02 on every weekday, or explicit [(date, v)] lists."""
    out = {}
    for cur, v in per_eur.items():
        out[cur] = v if isinstance(v, list) else [(D(2023, 1, 2), v)]
    return FX.Rates(out)


# ---------------------------------------------------------------- importer

def book():
    """Made-up sheet in the user's style: a purchase row closed with P/L 0, plus a sale row dated on the sale day."""
    pos = {
        2: position(2, D(2024, 1, 10), "Alpha Corp", 10, 100, 100, "Closed", cost=0, pl=0),   # purchase, sold later
        3: position(3, D(2024, 6, 1), "Alpha Corp", 10, 100, 120, "Closed"),                  # the sale (row dated on sale day)
        4: position(4, D(2024, 2, 1), "Alpha Corp", 5, 110, 125, "Open", live_formula=True),  # still held
        5: position(5, D(2024, 3, 1), "Beta plc", 200, 250, 250, "Closed", cur="GBP", pence=True, cost=0, pl=0),
        6: position(6, D(2024, 6, 3), "Beta plc", 200, 250, 300, "Closed", cur="GBP", pence=True),
        7: position(7, D(2024, 3, 5), "Gamma AG", 4, 50, 40, "Closed", cur="EUR", cost=0, pl=0),  # purchase nobody sold
        8: position(8, D(2024, 7, 1), "Delta", 3, 10, 9, "Closed", live_formula=True),         # sold, price still live
        9: position(9, D(2024, 5, 1), "Epsilon", 2, 30, 33, "open "),                          # trailing space in status
        10: position(10, D(2020, 5, 1), "Old Co", 10, 5, 7, "Closed", pl=20.0),                # sold in place, no date
        11: position(11, D(2024, 4, 1), "Delta", 3, 10, 10, "Closed", cost=0, pl=0),          # Delta's purchase
    }
    sales = {
        21: sale(21, D(2024, 6, 1), "Alpha", 3, 200.0, 0.2),
        22: sale(22, D(2024, 6, 3), "Beta", 6, 100.0, 0.2),
        23: sale(23, D(2024, 7, 1), "Delta", 8, -3.0),
        24: sale(24, D(2023, 12, 1), "Old sale", None, 55.5, typed=True),
    }
    return make(pos, 20, sales)


def test_reads_only_the_live_portfolio_tab_and_all_rows():
    w = L.read(book())
    assert w.sheet_name == "Live Portfolio " and [p.row for p in w.positions] == list(range(2, 12))
    assert w.positions[7].status == "open"
    assert [(s.row, s.link, s.linked_rows) for s in w.sales] == [(21, "single", [3]), (22, "single", [6]),
                                                                   (23, "single", [8]), (24, "typed", [])]
    assert w.positions[2].live_price_is_formula and not w.positions[1].live_price_is_formula
    assert w.skipped == []


def test_rejects_wrong_files():
    with pytest.raises(L.ImportError_, match="No tab called 'Live Portfolio'"):
        L.read(make({}, 20, {}, tab="Something else", extra_tabs=()))
    with pytest.raises(L.ImportError_, match="password-protected"):
        L.read(b"\xd0\xcf\x11\xe0" + b"\0" * 600)
    with pytest.raises(L.ImportError_, match="Can't read"):
        L.read(b"not a workbook")


def test_round_trip_through_json():
    w = L.read(book())
    assert L.from_dict(w.to_dict()) == w


# ---------------------------------------------------------------- rebuild

def test_rows_become_purchases_and_sales():
    w = L.read(book())
    rb = R.rebuild(w)
    assert rb.roles == {2: "closed_buy", 3: "sale", 4: "open_buy", 5: "closed_buy", 6: "sale", 7: "closed_buy",
                        8: "out", 9: "open_buy", 10: "out", 11: "closed_buy"}
    t = {x.id: x for x in rb.trades}
    assert set(t) == {"B2", "S3", "B4", "B5", "S6", "B9"}  # B7's 4 unsold shares are left out while pending
    assert t["S3"].date == D(2024, 6, 1) and t["S3"].price == 120 and t["S3"].sale_row == 21 and t["S3"].ref_price == 100
    assert t["B5"].scale == 0.01 and t["B5"].value == pytest.approx(500.0)  # pence
    pend = {i.key: i.kind for i in rb.review if i.status == "pending"}
    assert pend == {"P7": "unsold_buy", "P8": "sell_price_missing", "P10": "closed_no_sale", "S24": "sale_unlinked",
                    "P11": "unsold_buy"}  # Delta's purchase is unsold while its sale (row 8) waits for a price
    a = rb.accounting
    assert a["open_buys"] + a["closed_buys"] + a["sales"] + a["excluded"] + a["not_classified"] == a["position_rows"] == 10


def test_decisions_resolve_every_kind():
    w = L.read(book())
    rb = R.rebuild(w, {"P7": {"action": "exclude", "scope": "leftover"}, "P8": {"action": "sell", "date": "2024-07-01", "price": 9.5},
                       "P10": {"action": "sell", "date": "2020-09-01", "price": 7.0}, "S24": {"action": "sheet_only"}})
    assert all(i.status == "resolved" for i in rb.review)
    ids = {x.id for x in rb.trades}
    assert {"S8", "B10", "S10", "B11"} <= ids and "B7" not in ids
    bad = R.rebuild(w, {"P10": {"action": "sell", "date": "2020-01-01", "price": 7.0}})  # before the buy date
    assert "before the buy date" in next(i.detail for i in bad.review if i.key == "P10")
    whole = R.rebuild(w, {"P3": {"action": "exclude"}})  # excluding a sale leaves its purchase unsold
    assert "P2" in {i.key for i in whole.review if i.kind == "unsold_buy"}


def test_sold_in_place_row_as_a_sale_row():
    pos = {2: position(2, D(2021, 5, 17), "Mu Ltd", 300, 120.0, 120.0, "Closed", cur="GBP", pence=True, cost=0, pl=0),
           3: position(3, D(2021, 9, 16), "Mu Ltd", 300, 120.0, 90.0, "Closed", cur="GBP", pence=True, pl=-90.0)}
    w = L.read(make(pos, 20, {}))
    assert {i.key: i.kind for i in R.rebuild(w).review} == {"P2": "unsold_buy", "P3": "closed_no_sale"}
    rb = R.rebuild(w, {"P3": {"action": "sale_row"}})
    assert all(i.status == "resolved" for i in rb.review)
    assert [(t.id, t.date) for t in rb.trades] == [("B2", D(2021, 5, 17)), ("S3", D(2021, 9, 16))]


def test_sale_without_a_purchase_and_entering_one():
    pos = {2: position(2, D(2024, 6, 1), "Kappa", 10, 100, 120, "Closed")}
    w = L.read(make(pos, 20, {21: sale(21, D(2024, 6, 1), "Kappa", 2, 200.0)}))
    rb = R.rebuild(w)
    (it,) = [i for i in rb.review if i.status == "pending"]
    assert it.kind == "sale_missing_buy" and it.data["missing_shares"] == 10 and rb.trades == []
    ok = R.rebuild(w, {"P2": {"action": "add_buy", "date": "2024-01-02", "price": 100, "shares": 10}})
    assert [x.id for x in ok.trades] == ["A2", "S2"] and not [i for i in ok.review if i.status == "pending"]


def test_partial_sales_consume_oldest_purchases():
    pos = {2: position(2, D(2024, 1, 2), "Lambda", 10, 50, 50, "Closed", cost=0, pl=0),
           3: position(3, D(2024, 2, 1), "Lambda", 10, 60, 60, "Closed", cost=0, pl=0),
           4: position(4, D(2024, 3, 1), "Lambda", 15, 55, 70, "Closed"),
           5: position(5, D(2024, 4, 1), "Lambda", 5, 55, 80, "Closed")}
    sales = {21: sale(21, D(2024, 3, 1), "L", 4, 1.0), 22: sale(22, D(2024, 4, 1), "L", 5, 1.0)}
    rb = R.rebuild(L.read(make(pos, 20, sales)))
    assert not [i for i in rb.review if i.status == "pending"]


def test_name_groups_merge_stocks():
    w = L.read(book())
    rb = R.rebuild(w, groups={"epsilon": "alpha corp"}, group_names={"alpha corp": "Alpha"})
    assert {t.stock for t in rb.trades if t.row in (2, 9)} == {"Alpha"}
    assert names.suggestions(["dollar gen", "dollar general", "micron", "micron 26", "apple"]) == \
        [["dollar gen", "dollar general"], ["micron", "micron 26"]]


def test_price_unit_flag_and_fix():
    pos = {2: position(2, D(2024, 1, 2), "Nu plc", 100, 400, 410, "Open", cur="EUR", cost=400.0, pl=10.0)}
    w = L.read(make(pos, 20, {}))
    assert R.rebuild(w).review[0].kind == "price_unit"
    fixed = R.rebuild(w, {"P2": {"action": "fix", "fields": {"currency": "GBP"}}})
    assert fixed.trades[0].value == pytest.approx(400.0) and not [i for i in fixed.review if i.status == "pending"]
    kept = R.rebuild(w, {"P2": {"action": "keep"}})
    assert kept.trades[0].value == pytest.approx(40000.0) and kept.review[0].status == "resolved"


# ---------------------------------------------------------------- FX

def test_fx_cross_rates_and_holidays():
    r = rates(USD=[(D(2024, 1, 5), 1.10), (D(2024, 1, 8), 1.20)], GBP=[(D(2024, 1, 5), 0.88), (D(2024, 1, 8), 0.80)])
    assert r.usd("USD", D(2024, 1, 6)).rate == 1.0
    eur = r.usd("EUR", D(2024, 1, 7))  # Sunday -> Friday's rate
    assert eur.rate == 1.10 and eur.rate_date == D(2024, 1, 5)
    assert r.usd("GBP", D(2024, 1, 8)).rate == pytest.approx(1.20 / 0.80)
    assert r.usd("EUR", D(2024, 1, 4)) is None  # before the first rate
    assert r.usd("EUR", D(2024, 2, 1)) is None  # stale beyond 7 days: not used
    assert r.usd("CHF", D(2024, 1, 8)) is None


# ---------------------------------------------------------------- FIFO

def T(id_, kind, d, shares, price, cur="USD", pool="x", row=None):
    return R.Trade(id_, kind, d, "X", "x", f"{pool}|{cur}", shares, price, cur, 1.0, "IBKR", row or int(id_[1:]))


def test_fifo_partial_lots_by_hand():
    tr = [T("B1", "buy", D(2024, 1, 2), 10, 100), T("B2", "buy", D(2024, 2, 1), 10, 120),
          T("S3", "sell", D(2024, 3, 1), 15, 130), T("S4", "sell", D(2024, 4, 1), 5, 90)]
    sales, lots = FIFO.run(tr, rates(USD=1.1))
    s3, s4 = sales
    assert [(m.buy_id, m.shares) for m in s3.matches] == [("B1", 10), ("B2", 5)]
    assert s3.cost_usd == pytest.approx(10 * 100 + 5 * 120) and s3.gain_usd == pytest.approx(15 * 130 - 1600)
    assert s3.days_held == pytest.approx((10 * 59 + 5 * 29) / 15)
    assert [(m.buy_id, m.shares) for m in s4.matches] == [("B2", 5)] and s4.gain_usd == pytest.approx(5 * (90 - 120))
    assert lots == []


def test_fifo_oversell_is_flagged_not_computed():
    sales, _ = FIFO.run([T("B1", "buy", D(2024, 1, 2), 5, 10), T("S2", "sell", D(2024, 2, 1), 8, 12)], rates(USD=1.1))
    assert sales[0].gain_usd is None and sales[0].unmatched_shares == 3 and "more shares" in sales[0].problems[0]


def test_fifo_currency_effect_by_hand():
    r = rates(USD=[(D(2024, 1, 2), 1.10), (D(2024, 6, 3), 1.20)])
    tr = [T("B1", "buy", D(2024, 1, 2), 10, 100, cur="EUR"), T("S2", "sell", D(2024, 6, 3), 10, 110, cur="EUR")]
    (s,), _ = FIFO.run(tr, r)
    assert s.cost_usd == pytest.approx(1100) and s.proceeds_usd == pytest.approx(1320)
    assert s.gain_usd == pytest.approx(220)
    assert s.price_effect_usd == pytest.approx(10 * 10 * 1.20) and s.fx_effect_usd == pytest.approx(1000 * 0.10)
    assert s.price_effect_usd + s.fx_effect_usd == pytest.approx(s.gain_usd)
    assert s.sell_rate_date == D(2024, 6, 3) and s.matches[0].buy_rate == 1.10


def test_fifo_pools_are_separate_and_open_lots_remain():
    tr = [T("B1", "buy", D(2024, 1, 2), 10, 100, pool="a"), T("B2", "buy", D(2024, 1, 3), 10, 50, pool="b"),
          T("S3", "sell", D(2024, 2, 1), 4, 60, pool="b")]
    sales, lots = FIFO.run(tr, rates(USD=1.1))
    assert sales[0].matches[0].buy_id == "B2"
    assert sorted((lot.buy_id, lot.shares) for lot in lots) == [("B1", 10), ("B2", 6)]


def test_fifo_differs_from_the_sheets_specific_matching():
    """The sheet sells a specific purchase; FIFO takes the oldest. Totals agree once the stock is fully sold."""
    pos = {2: position(2, D(2024, 1, 2), "Zeta", 10, 100, 100, "Closed", cost=0, pl=0),
           3: position(3, D(2024, 2, 1), "Zeta", 10, 200, 200, "Closed", cost=0, pl=0),
           4: position(4, D(2024, 3, 1), "Zeta", 10, 200, 210, "Closed"),   # the sheet sold the 2nd purchase first
           5: position(5, D(2024, 4, 1), "Zeta", 10, 100, 150, "Closed")}
    sales = {21: sale(21, D(2024, 3, 1), "Zeta", 4, 100.0), 22: sale(22, D(2024, 4, 1), "Zeta", 5, 500.0)}
    w = L.read(make(pos, 20, sales))
    rb = R.rebuild(w)
    fs, lots = FIFO.run(rb.trades, rates(USD=1.1), {p.row: p.pl for p in w.positions})
    assert [s.gain_local for s in fs] == [pytest.approx(10 * 210 - 1000), pytest.approx(10 * 150 - 2000)]
    assert [s.sheet_pl for s in fs] == [100.0, 500.0]
    assert sum(s.gain_local for s in fs) == pytest.approx(600.0) and lots == []


# ---------------------------------------------------------------- check figures

def test_check_figures_match_and_explain_differences():
    w = L.read(book())
    c = C.check(w, R.rebuild(w))
    sl = c["sales_log"]
    assert sl["total_sheet"] == pytest.approx(200 + 100 - 3 + 55.5)
    assert sl["lines_matching"] == 2  # Alpha and Beta reproduce exactly
    diffs = {d["row"]: d["causes"][0] for d in sl["differences"]}
    assert "waiting on the review page" in diffs[23] and "typed in the sales log" in diffs[24]
    years = {y["year"]: y for y in sl["by_year"]}
    assert years[2024]["sheet"] == pytest.approx(297) and years[2024]["app"] == pytest.approx(300)
    op = c["open_positions"]
    assert op["stocks"] == 2 and op["stocks_matching"] == 2


def test_check_names_a_hand_typed_pl():
    pos = {2: position(2, D(2024, 1, 2), "Eta", 10, 100, 100, "Closed", cost=0, pl=0),
           3: position(3, D(2024, 3, 1), "Eta", 10, 100, 120, "Closed", pl=250.0)}
    w = L.read(make(pos, 20, {21: sale(21, D(2024, 3, 1), "Eta", 3, 250.0)}))
    (d,) = C.check(w, R.rebuild(w))["sales_log"]["differences"]
    assert "typed by hand" in d["causes"][0] and d["app"] == pytest.approx(200)
