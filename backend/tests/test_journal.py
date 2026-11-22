"""Trade journal: stable keys, the context prices give, plan vs reality, what works, and the API."""
from datetime import date, timedelta
from types import SimpleNamespace as T

import pytest

from app.engine import journal as J

from .test_api import client, upload  # noqa: F401  (fixture re-used)


def test_keys_are_stable_when_rows_move_and_tell_twins_apart():
    a = [T(id="B5", kind="buy", date=date(2024, 1, 2), stock_key="x", currency="USD", shares=10.0, price=5.0, row=5),
         T(id="B6", kind="buy", date=date(2024, 1, 2), stock_key="x", currency="USD", shares=10.0, price=5.0, row=6)]
    b = [T(id="B9", kind="buy", date=date(2024, 1, 2), stock_key="x", currency="USD", shares=10.0, price=5.0, row=9),
         T(id="B10", kind="buy", date=date(2024, 1, 2), stock_key="x", currency="USD", shares=10.0, price=5.0, row=10)]
    ka, kb = J.trade_keys(a), J.trade_keys(b)
    assert ka["B5"] == kb["B9"] and ka["B6"] == kb["B10"] and ka["B5"] != ka["B6"]


def series(start, values):
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_excursion_from_high_and_market():
    s = series(date(2024, 1, 1), [100, 120, 80, 110])
    e = J.excursion(s, date(2024, 1, 1), date(2024, 1, 4), 100)
    assert e["best_pct"] == pytest.approx(20) and e["worst_pct"] == pytest.approx(-20) and e["best_date"] == "2024-01-02"
    year = series(date(2023, 1, 1), [100 + i * 0.1 for i in range(400)])
    assert J.from_high(year, date(2024, 1, 31), 90) == pytest.approx((90 / max(v for d, v in year if d <= date(2024, 1, 31)) - 1) * 100)
    assert J.market_trend(year, date(2024, 1, 31))["above_200d"] is True
    assert J.from_high(s, date(2024, 1, 4), 100) is None  # too little history


def test_plan_check():
    exc = {"best_price": 130.0, "worst_price": 85.0}
    codes = lambda plan, price, days: [c["code"] for c in J.plan_check(plan, price, days, exc)]  # noqa: E731
    assert codes({"stop": 90}, 80, 10) == ["below_stop"]
    assert codes({"stop": 90}, 90.5, 10) == ["at_stop"]
    assert codes({"stop": 90}, 110, 10) == ["stop_crossed"]
    assert codes({"target": 125}, 124, 10) == ["at_target"]
    assert codes({"target": 125}, 110, 10) == ["gave_back"]
    assert codes({"target": 140}, 110, 10) == ["before_target"]
    assert codes({"horizon_days": 30}, 110, 60) == ["held_longer"] and codes({"horizon_days": 30}, 110, 5) == ["sold_sooner"]


def test_stats():
    s = [{"gain_usd": 100, "gain_pct": 10, "days": 20, "reasons": ["Breakout"], "group": "Trading", "confidence": 4, "sell_reason": "Hit target",
          "plan": [{"code": "at_target", "good": True}]},
         {"gain_usd": -50, "gain_pct": -5, "days": 400, "reasons": ["Breakout", "Dip buy"], "group": None, "confidence": None, "sell_reason": None,
          "plan": [{"code": "below_stop", "good": False}]}]
    st = J.stats(s)
    br = {r["label"]: r for r in st["by_reason"]}
    assert br["Breakout"]["sales"] == 2 and br["Breakout"]["win_rate"] == 50 and br["Dip buy"]["total_gain_usd"] == -50
    assert {r["label"] for r in st["by_group"]} == {"Trading", "Not grouped"}
    assert {r["label"] for r in st["by_holding"]} == {"under 1 month", "over 1 year"}
    assert st["plan"]["followed"] == 1 and st["plan"]["broke"] == 1 and st["journaled_sales"] == 2


def test_api_write_skip_stats_and_entries_survive_a_reimport(client):  # noqa: F811
    assert upload(client).status_code == 200
    v = client.get("/api/journal").json()
    buy = next(r for r in v["rows"] if r["kind"] == "buy")
    sell = next(r for r in v["rows"] if r["kind"] == "sell")
    r = client.put("/api/journal/entry", params={"key": buy["key"]}, json={"reasons": ["Breakout"], "target": 200, "confidence": 3, "notes": "n"})
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["entry"]["reasons"] == ["Breakout"]
    assert client.put("/api/journal/entry", params={"key": buy["key"]}, json={"confidence": 7}).status_code == 400
    assert client.put("/api/journal/entry", params={"key": "nope"}, json={}).status_code == 404
    r = client.put("/api/journal/entry", params={"key": sell["key"]}, json={"sell_reason": "Hit stop", "lesson": "l"})
    assert r.json()["entry"]["sell_reason"] == "Hit stop"
    v = client.post("/api/journal/skip", json={"older": True}).json()
    assert v["counts"]["todo_older"] == 0 and v["counts"]["done"] == 2
    assert upload(client).status_code == 200  # same workbook again: entries still attached
    v = client.get("/api/journal").json()
    assert next(r for r in v["rows"] if r["key"] == buy["key"])["entry"]["notes"] == "n"
    st = client.get("/api/journal/stats").json()
    assert any(r["label"] == "Hit stop" for r in st["by_sell_reason"]) and st["lessons"][0]["lesson"] == "l"
    assert "reasons" in client.get("/api/journal/export.csv").text.splitlines()[0]
    t = client.put("/api/journal/tags", json={"reasons": ["Mine", "Mine", " "]}).json()
    assert t["reasons"] == ["Mine"] and t["sell_reasons"] == J.SELL_REASONS


def test_check_levels():
    d = date(2024, 3, 1)
    bars = [(d, 101, 99, 100), (d + timedelta(days=1), 103, 98, 102), (d + timedelta(days=2), 96, 90, 92)]
    lv = [{"label": "entry", "price": 95}, {"label": "near", "price": 104}, {"label": "far", "price": 50}]
    ev = {(e["label"], e["kind"]): e for e in J.check_levels(lv, bars, set(), 3.0, hit_from=d + timedelta(days=1))}
    assert set(ev) == {("entry", "hit"), ("near", "near")}  # 95 touched on day 3; 104 within 3% of 102 on day 2
    assert ev[("entry", "hit")]["date"] == d + timedelta(days=2)
    assert J.check_levels(lv, bars, {("entry", "hit"), ("near", "near")}, 3.0) == []  # each fires once
    early = [{"label": "x", "price": 100}]
    assert [e["kind"] for e in J.check_levels(early, bars[:1], set(), 3.0, hit_from=d + timedelta(days=1))] == ["near"]  # before: near only
    assert J.distances([{"label": "a", "price": 110}], 100)[0]["distance_pct"] == pytest.approx(10)


def test_ideas_api(client, monkeypatch):  # noqa: F811
    from app.services import ideas as IS
    today = date.today()
    bars = [(today - timedelta(days=1), 52.0, 49.0, 50.0), (today, 51.0, 44.0, 45.0)]
    monkeypatch.setattr(IS, "_track", lambda t, ex: (7, None))
    monkeypatch.setattr(IS, "_bars", lambda lid, since: ([b for b in bars if b[0] >= since], {"date": today.isoformat(), "close": 45.0}))
    assert upload(client).status_code == 200
    r = client.post("/api/journal/ideas", json={"ticker": "abc", "stock": "Alpha", "levels": [
        {"label": "entry", "kind": "entry", "price": 46}, {"label": "target", "kind": "target", "price": 46.5}, {"label": "far", "kind": "alert", "price": 80}]})
    assert r.status_code == 200, r.text
    i = r.json()
    assert i["ticker"] == "ABC" and {(e["label"], e["kind"]) for e in i["events"]} == {("entry", "hit"), ("target", "hit")}
    assert client.get("/api/journal/ideas/unseen").json() == {"unseen": 2}
    client.post("/api/journal/ideas/seen")
    assert client.get("/api/journal/ideas/unseen").json() == {"unseen": 0}
    # moving a level re-arms it
    i = client.put(f"/api/journal/ideas/{i['id']}", json={"levels": [{"label": "entry", "kind": "entry", "price": 30},
                                                                    {"label": "far", "kind": "alert", "price": 80}]}).json()
    assert [e["label"] for e in i["events"]] == [] and i["levels"][0]["distance_pct"] == pytest.approx((30 / 45 - 1) * 100)
    assert client.put(f"/api/journal/ideas/{i['id']}", json={"levels": [{"label": "a", "price": -1}]}).status_code == 400
    assert client.post("/api/journal/ideas", json={"ticker": "A", "exchange": "XNYC"}).status_code == 400
    # carried out: the plan goes into the buy's journal entry
    buy = next(r for r in client.get("/api/journal").json()["rows"] if r["kind"] == "buy")
    client.put(f"/api/journal/ideas/{i['id']}", json={"levels": [{"label": "t", "kind": "target", "price": 99}], "reasons": ["Breakout"]})
    out = client.post(f"/api/journal/ideas/{i['id']}/bought", json={"key": buy["key"]}).json()
    assert out["status"] == "done" and out["bought_key"] == buy["key"]
    e = client.get("/api/journal/entry", params={"key": buy["key"]}).json()["entry"]
    assert e["reasons"] == ["Breakout"] and e["target"] == 99 and "From idea of" in e["notes"]
    assert client.delete(f"/api/journal/ideas/{i['id']}").json()["ideas"] == []


def test_stars_and_sectors(client, monkeypatch):  # noqa: F811
    from app.services import ideas as IS
    monkeypatch.setattr(IS, "_track", lambda t, ex: (None, "no prices in tests"))
    assert upload(client).status_code == 200
    row = client.get("/api/journal").json()["rows"][0]
    assert row["starred"] is False and row["sector"] is None
    assert client.put("/api/sectors/" + row["stock_key"], json={"sector": "Energy"}).status_code == 200
    assert client.put("/api/journal/star", json={"key": row["stock_key"], "starred": True}).json()["starred"] == [row["stock_key"]]
    rows = [r for r in client.get("/api/journal").json()["rows"] if r["stock_key"] == row["stock_key"]]
    assert all(r["starred"] and r["sector"] == "Energy" for r in rows)
    st = client.get("/api/journal/stats").json()
    assert {x["label"] for x in st["by_starred"]} <= {"★ Starred stocks", "Other stocks"} and st["by_sector"]
    i = client.post("/api/journal/ideas", json={"ticker": "NEWCO", "stock": "New Co", "sector": "Energy"}).json()
    assert i["star_key"] == "ticker:NEWCO" and i["sector"] == "Energy" and i["starred"] is False
    client.put("/api/journal/star", json={"key": i["star_key"], "starred": True})
    assert client.get("/api/journal/ideas").json()["ideas"][0]["starred"] is True
    assert client.put(f"/api/journal/ideas/{i['id']}", json={"sector": "Nonsense"}).status_code == 400
    assert client.put("/api/journal/star", json={"key": " ", "starred": True}).status_code == 400
