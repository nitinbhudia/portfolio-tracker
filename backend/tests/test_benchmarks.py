"""Index comparison: CSV parsing, Stooq fetch, per-trade vs index, same money in the index, periods (hand-checked).

The made-up book (tests/test_engine.py::book): Alpha Corp bought 2024-01-10 (10 @ 100 = $1,000), sold 2024-06-01 for
$1,200 (gain $200); open lots Alpha (5 @ 110, 2024-02-01) and Epsilon (2 @ 30, 2024-05-01); Beta (GBP) sold 2024-06-03.
The fake index is 100 until 2024-03-31 and 110 from 2024-04-01, so $1,000 held over that step gains $100.
"""
from datetime import date as D
from datetime import timedelta

import pytest

from app.engine import benchmarks as BM
from app.engine import fx as FX
from app.services import benchmarks as BMS

from .test_api import client, upload  # noqa: F401  (fixture re-used)


def step_series(start=D(2023, 12, 1), jump=D(2024, 4, 1), before=100.0, after=110.0):
    out, d = [], start
    while d <= D.today():
        if d.weekday() < 5:
            out.append((d, before if d < jump else after))
        d += timedelta(days=1)
    return out


def csv_of(rows):
    return "Date,Open,High,Low,Close,Volume\n" + "\n".join(f"{d.isoformat()},1,1,1,{v},0" for d, v in rows)


# ---------------------------------------------------------------- parsing and fetching

def test_parse_csv_formats_and_errors():
    assert BM.parse_csv("﻿Date,Close\n2024-01-03,5\n2024-01-02,4\nbad,3\n") == [(D(2024, 1, 2), 4.0), (D(2024, 1, 3), 5.0)]
    assert BM.parse_csv("Date,Adj Close\n2024-01-02,\"1,234.5\"\n") == [(D(2024, 1, 2), 1234.5)]
    for bad, msg in [("", "Not a CSV"), ("No data", "Not a CSV"), ("Date,Close\n", "no rows"), ("Day,Value\n2024-01-02,3\n", "Couldn't find"),
                     ("Date,Close\n02/01/2024,3\n", "YYYY-MM-DD")]:
        with pytest.raises(BM.BenchmarkError, match=msg):
            BM.parse_csv(bad)


def test_fred_format_and_fetch():
    import httpx
    body = "observation_date,SP500\n2026-11-04,7688.62\n2026-11-05,\n2026-11-06,.\n2026-11-09,7353.73\n"
    assert BM.parse_csv(body) == [(D(2026, 11, 4), 7688.62), (D(2026, 11, 9), 7353.73)]  # holidays skipped

    def handler(req):
        assert req.url.host == "fred.stlouisfed.org" and req.url.params["id"] == "SP500"
        return httpx.Response(200, text=body)
    assert BM.fetch("fred", "SP500", httpx.Client(transport=httpx.MockTransport(handler)))[-1] == (D(2026, 11, 9), 7353.73)

    def html(req):
        return httpx.Response(200, text="<html>error</html>")
    with pytest.raises(BM.BenchmarkError, match="FRED returned no data"):
        BM.fetch("fred", "NOPE", httpx.Client(transport=httpx.MockTransport(html)))

    def refuse(req):
        raise httpx.ConnectError("reset")
    with pytest.raises(BM.BenchmarkError, match="Couldn't reach Stooq"):
        BM.fetch("stooq", "^rut", httpx.Client(transport=httpx.MockTransport(refuse)))

    def slow(req):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(BM.BenchmarkError, match="didn't answer in time"):
        BM.fetch("fred", "SP500", httpx.Client(transport=httpx.MockTransport(slow)))


def test_fetch_stooq_parses_and_reports_no_data():
    import httpx

    def handler(req):
        if req.url.params["s"] == "^spx":
            return httpx.Response(200, text=csv_of([(D(2024, 1, 2), 4700.0)]))
        return httpx.Response(200, text="No data")
    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert BM.fetch_stooq("^spx", c) == [(D(2024, 1, 2), 4700.0)]
    with pytest.raises(BM.BenchmarkError, match="no data for \\^xyz"):
        BM.fetch_stooq("^xyz", c)


def test_series_in_usd_and_stale_gaps():
    s = BM.Series("ukx", "GBP", [D(2024, 1, 2), D(2024, 1, 3)], [8000.0, 8100.0])
    rates = FX.Rates({"USD": [(D(2024, 1, 2), 1.10), (D(2024, 1, 3), 1.10)], "GBP": [(D(2024, 1, 2), 0.88), (D(2024, 1, 3), 0.80)]})
    assert s.usd(D(2024, 1, 2), rates) == pytest.approx(8000 * 1.10 / 0.88)
    assert s.usd(D(2024, 1, 6), rates) == pytest.approx(8100 * 1.10 / 0.80)  # Saturday: the last close (Wednesday) is within 7 days
    assert s.usd(D(2024, 2, 1), rates) is None  # older than 7 days: no level, nothing invented


# ---------------------------------------------------------------- API

def setup(client, monkeypatch, rows=None):  # noqa: F811
    upload(client)
    client.put("/api/review/P8", json={"action": "sell", "date": "2024-07-01", "price": 9.5})
    monkeypatch.setattr(BMS, "FETCH", lambda src, sym: rows or step_series())


def test_refresh_status_and_symbols(client, monkeypatch):  # noqa: F811
    setup(client, monkeypatch)
    r = client.post("/api/benchmarks/refresh").json()
    assert [x["id"] for x in r["results"]] == ["spx", "ndq", "ndx", "rut", "ukx"] and all(x["ok"] for x in r["results"])
    st = {x["id"]: x for x in client.get("/api/benchmarks/status").json()["indexes"]}
    assert (st["spx"]["source"], st["spx"]["symbol"]) == ("fred", "SP500") and (st["rut"]["source"], st["rut"]["symbol"]) == ("stooq", "^rut")
    assert st["ukx"]["currency"] == "GBP" and st["rut"]["points"] > 100
    rut = client.put("/api/benchmarks/rut", json={"symbol": "iwm.us"}).json()["indexes"][3]
    assert (rut["source"], rut["symbol"]) == ("stooq", "iwm.us")
    assert client.put("/api/benchmarks/rut", json={"symbol": "X", "source": "yahoo"}).status_code == 400
    assert client.put("/api/benchmarks/xxx", json={"symbol": "a"}).status_code == 404
    seen = []
    monkeypatch.setattr(BMS, "FETCH", lambda src, sym: seen.append((src, sym)) or step_series())
    one = client.post("/api/benchmarks/ndq/refresh").json()
    assert [r["id"] for r in one["results"]] == ["ndq"] and seen == [("fred", "NASDAQCOM")]

    def boom(src, sym):
        raise BM.BenchmarkError("Stooq answered HTTP 503. Upload a CSV instead.")
    monkeypatch.setattr(BMS, "FETCH", boom)
    r = client.post("/api/benchmarks/refresh").json()
    assert not r["results"][0]["ok"] and "503" in r["results"][0]["message"]
    assert client.get("/api/benchmarks/status").json()["indexes"][0]["points"] > 100  # earlier data kept

    def crash(src, sym):
        raise ValueError("something odd")
    monkeypatch.setattr(BMS, "FETCH", crash)
    r = client.post("/api/benchmarks/spx/refresh")
    assert r.status_code == 200 and "Unexpected problem (ValueError" in r.json()["results"][0]["message"]


def test_upload_csv(client, monkeypatch):  # noqa: F811
    setup(client, monkeypatch)
    f = {"file": ("spx.csv", csv_of(step_series()).encode(), "text/csv")}
    assert client.post("/api/benchmarks/spx/upload", files=f).json()["results"][0]["ok"]
    bad = {"file": ("x.csv", b"hello", "text/csv")}
    assert client.post("/api/benchmarks/spx/upload", files=bad).status_code == 400
    assert client.post("/api/benchmarks/nope/upload", files=f).status_code == 404


def test_per_trade_comparison_by_hand(client, monkeypatch):  # noqa: F811
    setup(client, monkeypatch)
    client.post("/api/benchmarks/refresh")
    v = client.get("/api/benchmarks").json()
    assert v["period"]["all_time"] and v["period"]["first_trade"] == "2024-01-10"
    spx = next(x for x in v["indexes"] if x["id"] == "spx")
    rl = spx["compare"]["realised"]
    sales = {s["id"]: s for s in client.get("/api/sales").json()["sales"]}
    beta = sales["S6"]  # bought 2024-03-01 (index 100), sold 2024-06-03 (110)
    assert rl["sales"] == 3 and rl["compared"] == 3
    # Alpha: $1,000 over the step = +$100; Beta: its USD cost × 10%; Delta (bought 2024-04-01, at 110): +$0
    assert rl["index_gain_usd"] == pytest.approx(100 + beta["cost_usd"] * 0.10)
    assert rl["gain_usd"] == pytest.approx(sum(s["gain_usd"] for s in sales.values()))
    op = spx["compare"]["open"]  # Alpha bought at 100 (→110: +10%), Epsilon bought 2024-05-01 at 110 (+0%)
    assert op["compared"] == 2 and op["index_gain_usd"] == pytest.approx(550 * 0.10)
    assert spx["change_pct"] == pytest.approx(10.0)
    sm = spx["same_money"]
    assert sm["index_end_value_usd"] is not None and sm["your_xirr_pct"] is not None and sm["trades_not_priced"] == 0
    assert v["cumulative"]["dates"][-1] == "2024-07-01" and v["cumulative"]["yours"][-1] == pytest.approx(rl["gain_usd"])
    assert v["index_chart"]["lines"]["spx"][0] == pytest.approx(100.0)


def test_same_money_runs_out_when_the_index_falls(client, monkeypatch):  # noqa: F811
    setup(client, monkeypatch, step_series(before=100.0, after=40.0))  # index -60% after 2024-04-01
    client.post("/api/benchmarks/refresh")
    sm = next(x for x in client.get("/api/benchmarks").json()["indexes"] if x["id"] == "spx")["same_money"]
    assert sm["ran_out"] == "2024-06-01" and sm["index_end_value_usd"] is None and sm["index_xirr_pct"] is None


def test_periods(client, monkeypatch):  # noqa: F811
    setup(client, monkeypatch)
    client.post("/api/benchmarks/refresh")
    v = client.get("/api/benchmarks", params={"start": "2024-06-02", "end": "2024-06-30"}).json()
    spx = next(x for x in v["indexes"] if x["id"] == "spx")
    assert not v["period"]["all_time"] and spx["same_money"] is None  # needs the whole history
    assert spx["compare"]["realised"]["sales"] == 1 and spx["compare"]["open"] is None  # only Beta; period ends before today
    assert spx["change_pct"] == pytest.approx(0.0)
    assert client.get("/api/benchmarks", params={"start": "2024-07-01", "end": "2024-06-01"}).status_code == 400
    assert client.get("/api/benchmarks", params={"start": "June"}).status_code == 400
    assert client.get("/api/benchmarks", params={"range": "2W"}).status_code == 400
    one = client.get("/api/benchmarks", params={"range": "1Y"}).json()["period"]
    assert one["end"] == one["valuation"] and one["start"][:4] == str(int(one["end"][:4]) - 1) and one["start"][5:] == one["end"][5:]


def test_no_index_data_yet(client, monkeypatch):  # noqa: F811
    setup(client, monkeypatch)
    v = client.get("/api/benchmarks").json()
    assert all(not x["available"] for x in v["indexes"]) and v["index_chart"]["lines"] == {}
