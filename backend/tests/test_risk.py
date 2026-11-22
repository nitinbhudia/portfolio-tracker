"""Risk dashboard: concentration, exposure, and market risk of today's holdings (engine/risk.py)."""
from datetime import date, timedelta

import numpy as np
import pytest

from app.engine import risk as RK

from .test_api import client  # noqa: F401  (fixture re-used)


def days(n, end=date(2026, 6, 30)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def path(rets, start=100.0):
    return list(start * np.cumprod(1 + np.concatenate([[0.0], rets])))


H = [RK.Holding("a", "Alpha", 600.0, "Information Technology", "USD", {"IBKR": 600.0}),
     RK.Holding("b", "Beta", 300.0, None, "EUR", {"IBKR": 100.0, "Saxo": 200.0}),
     RK.Holding("c", "Gamma", 100.0, "Energy", "USD", {})]


def test_concentration_and_exposure():
    c = RK.concentration(H)
    assert c["total_usd"] == 1000 and c["largest"] == "Alpha" and c["largest_pct"] == pytest.approx(60)
    assert c["hhi"] == pytest.approx(0.36 + 0.09 + 0.01) and c["effective_n"] == pytest.approx(1 / 0.46)
    assert c["top5_pct"] == pytest.approx(100) and [x["label"] for x in c["large"]] == ["Alpha", "Beta", "Gamma"]
    assert [x["very_large"] for x in c["large"]] == [True, True, False]  # 10% counts as large, 20% as very large
    e = RK.exposure(H)
    assert e["sector"][0] == {"label": "Information Technology", "value_usd": 600.0, "pct": pytest.approx(60)}
    assert {x["label"] for x in e["sector"]} == {"Information Technology", "No sector set", "Energy"}
    assert {x["label"]: x["value_usd"] for x in e["broker"]} == {"IBKR": 700.0, "Saxo": 200.0, "Unknown broker": 100.0}
    assert [x["label"] for x in e["currency"]] == ["USD", "EUR"]


def test_market_risk_with_known_numbers():
    rng = np.random.default_rng(1)
    g = days(253)
    m = rng.normal(0.0004, 0.01, 252)
    mk = list(zip(g, path(m)))
    closes = {"a": list(zip(g, path(2 * m))),                       # beta 2, moves with the market
              "b": list(zip(g, path(rng.normal(0, 0.01, 252)))),   # its own way
              "c": list(zip(g[200:], path(m)[200:]))}               # too short: left out
    r = RK.market_risk(H, closes, mk, g[-1], "1y")
    assert r["status"] == "ok" and r["days"] == 252
    assert [x["label"] for x in r["missing"]] == ["Gamma"] and r["covered_pct"] == pytest.approx(90)
    pa = {x["key"]: x for x in r["positions"]}
    assert pa["a"]["beta"] == pytest.approx(2, abs=1e-9) and abs(pa["b"]["beta"]) < 0.3
    assert sum(x["risk_share_pct"] for x in r["positions"]) == pytest.approx(100)
    assert pa["a"]["risk_share_pct"] > 80  # two thirds of the money, nearly all the risk
    rb = np.diff(np.array([v for _, v in closes["b"]])) / np.array([v for _, v in closes["b"]])[:-1]
    rp = (600 * (2 * m) + 300 * rb) / 900
    assert r["volatility_pct"] == pytest.approx(np.std(rp, ddof=1) * np.sqrt(252) * 100, rel=1e-9)
    assert r["var95_usd"] == pytest.approx(r["var95_pct"] / 100 * 900) and r["es95_pct"] >= r["var95_pct"]
    assert r["max_drawdown_pct"] < 0 and r["drawdown"]["dates"][0] == g[0].isoformat()
    assert len(r["drawdown"]["portfolio"]) == len(r["drawdown"]["market"]) == 253
    # a 10% market drop: a with its beta of 2, b with its own, c (no history) with beta 1
    s10 = r["stress"][0]
    assert s10["market_pct"] == -10 and s10["change_usd"] == pytest.approx(-(600 * 2 + 300 * pa["b"]["beta"] + 100 * 1) * 0.1)
    assert r["correlation"]["labels"] == ["Alpha", "Beta"] and r["correlation"]["matrix"][0][0] == 1


def test_drawdown_of_a_known_path():
    dd, mdd, top, trough = RK._drawdown(np.array([0.1, -0.5, 0.2]))
    assert mdd == pytest.approx(-0.5) and (top, trough) == (1, 2) and dd[-1] == pytest.approx(1.1 * 0.5 * 1.2 / 1.1 - 1)


def test_not_enough_history_and_splits():
    g = days(20)
    r = RK.market_risk(H, {"a": list(zip(g, range(1, 21)))}, None, g[-1], "1y")
    assert r["status"] == "no_data"
    raw = [(date(2026, 1, 1), 200.0, 1.0), (date(2026, 1, 2), 100.0, 2.0), (date(2026, 1, 5), 101.0, 1.0)]
    assert RK.adjust_splits(raw) == [(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 100.0), (date(2026, 1, 5), 101.0)]


def test_api(client):  # noqa: F811
    from .test_api import upload
    assert upload(client).status_code == 200
    r = client.get("/api/risk")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["concentration"]["positions"] >= 1 and d["market"]["status"] == "no_data"  # no daily prices in this book
    assert client.get("/api/risk?window=10y").status_code == 400
