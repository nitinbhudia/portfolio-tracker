"""Sector Rotation module: holdings, dashboard, drill-down, score settings (SECTOR_ROTATION_TASK.md §5)."""
import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from research.data.sectors import SECTOR_TICKERS
from research.market_data import holdings as H
from research.market_data import service as md
from research.market_data.tiingo import MarketDataError
from research.services import sectors as S

from .test_market_data import FakeTiingo, fresh_db, nyse_days  # noqa: F401  (fixture re-used)


class DistinctTiingo(FakeTiingo):
    """Like FakeTiingo, but each symbol gets its own deterministic price path (so sectors differ from SPY)."""

    def handle(self, req):
        import httpx
        import numpy as np
        parts = req.url.path.strip("/").split("/")
        if len(parts) == 3:
            return super().handle(req)
        self.calls.append(req)
        sym = parts[2]
        start = date.fromisoformat(req.url.params["startDate"])
        days = [d for d in nyse_days(self.session, 1400) if d >= start]
        rng = np.random.default_rng(sum(map(ord, sym)) * 7919)
        p = 100 * np.exp(np.cumsum(0.012 * rng.standard_normal(1400)))[-len(days):] if days else []
        return httpx.Response(200, json=[{"date": f"{d.isoformat()}T00:00:00.000Z", "close": c, "high": c * 1.01, "low": c * 0.99,
                                          "open": c, "volume": 1_000_000, "adjClose": c, "adjHigh": c * 1.01, "adjLow": c * 0.99,
                                          "adjOpen": c, "adjVolume": 1_000_000, "divCash": 0.0, "splitFactor": 1.0}
                                         for d, c in zip(days, p)])

XLK = (Path(__file__).parent / "fixtures" / "ssga_xlk_holdings.xlsx").read_bytes()
PROV = ("source", "is_synthetic", "as_of", "exchange_timezone", "is_delayed", "delay_minutes", "stale")


# ---------------------------------------------------------------- holdings parser (real SSGA file)

def test_parse_real_ssga_file():
    f = H.parse_ssga(XLK, expected_ticker="XLK")
    assert f.etf_ticker == "XLK" and f.as_of == date(2026, 11, 4) and "Technology" in f.fund_name
    assert len(f.holdings) == 79 and f.holdings[0].ticker == "AAPL" and f.holdings[0].rank == 1
    assert sum(h.weight_pct for h in f.holdings) == pytest.approx(100, abs=0.05)
    weights = [h.weight_pct for h in f.holdings]
    assert weights == sorted(weights, reverse=True)
    cash = [h for h in f.holdings if h.ticker is None]
    assert cash and all("DOLLAR" in h.name or "MONEY MARKET" in h.name for h in cash)  # cash lines keep no ticker


def test_parse_rejects_bad_files():
    with pytest.raises(MarketDataError, match="Expected holdings for XLF"):
        H.parse_ssga(XLK, expected_ticker="XLF")
    with pytest.raises(MarketDataError, match="not a valid"):
        H.parse_ssga(b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')
    with pytest.raises(MarketDataError, match="header"):
        H.parse_ssga(buf.getvalue())


def _fake_fetch(t):
    if t == "XLK":
        return H.parse_ssga(XLK, "XLK")
    raise MarketDataError("not_found", f"State Street has no holdings file for {t}.")


# ---------------------------------------------------------------- dashboard on the synthetic demo

def test_dashboard_synthetic_demo(client):
    d = client.get("/api/sectors").json()
    assert d["status"] == "ok" and d["data"] == "synthetic" and d["benchmark"] == "SPY" and d["timeframe"] == "3m"
    assert d["provenance"]["is_synthetic"] is True and all(k in d["provenance"] for k in PROV)
    assert any("approximation" in n for n in d["notes"]) and any("fund-flow" in n for n in d["notes"])
    rows = d["rows"]
    assert {r["ticker"] for r in rows} == SECTOR_TICKERS and all(r["status"] == "ok" for r in rows)
    assert sum(d["quadrant_counts"].values()) == 11
    assert [r["rank"] for r in rows] == list(range(1, 12))
    totals = [r["score"]["total"] for r in rows]
    assert totals == sorted(totals, reverse=True)
    for r in rows:
        assert len(r["trail"]) == 20 and r["trail"][-1]["date"] == d["as_of"]
        assert r["quadrant"] == r["trail"][-1]["quadrant"]
        assert set(r["score"]["components"]) <= set(d["score"]["weights"])
        assert r["provenance"]["is_synthetic"] is True
    assert d["highlights"]["most_attractive"]["ticker"] == rows[0]["ticker"]
    assert d["benchmark_info"]["ticker"] == "SPY" and d["benchmark_info"]["absolute_trend"] in ("up", "down", "mixed")
    for e in d["events"]:
        assert e["category"] in d["event_categories"] and e["ticker"] in SECTOR_TICKERS


@pytest.mark.parametrize("tf", ["10d", "1m", "3m", "6m", "12m"])
def test_every_timeframe(client, tf):
    d = client.get(f"/api/sectors?timeframe={tf}").json()
    assert d["status"] == "ok" and d["bars_needed"] <= d["aligned_bars"] and d["method"]["windows"]["label"]


def test_benchmark_choice_changes_readings(client):
    a = {r["ticker"]: r["ratio"] for r in client.get("/api/sectors").json()["rows"]}
    b = {r["ticker"]: r["ratio"] for r in client.get("/api/sectors?benchmark=QQQ").json()["rows"]}
    assert a != b


@pytest.mark.parametrize("q", ["timeframe=2y", "benchmark=TSLA", "data=maybe", "region=mars"])
def test_bad_parameters(client, q):
    assert client.get(f"/api/sectors?{q}").status_code == 400


def test_real_requested_without_real_data_shows_nothing_invented(client):
    d = client.get("/api/sectors?data=real").json()
    assert d["data"] == "real" and d["status"] == "no_benchmark" and d["rows"] == []


def test_score_weights_roundtrip(client):
    base = client.get("/api/sectors").json()["rows"]
    try:
        r = client.put("/api/sectors/score-weights", json={"relative_strength": 100, "relative_momentum": 0, "acceleration": 0,
                                                            "ma_alignment": 0, "volume": 0, "transition": 0}).json()
        assert r["weights"]["relative_strength"] == 100
        rows = client.get("/api/sectors").json()["rows"]
        for x in rows:
            assert x["score"]["total"] == pytest.approx(round(x["score"]["components"]["relative_strength"]["points"], 1))
        assert [x["ticker"] for x in rows] == [x["ticker"] for x in sorted(rows, key=lambda y: -y["ratio"])]
        assert client.put("/api/sectors/score-weights", json={"volume": 500}).status_code == 400
    finally:
        client.put("/api/sectors/score-weights", json=S.rotation.DEFAULT_WEIGHTS)
    assert [x["ticker"] for x in client.get("/api/sectors").json()["rows"]] == [x["ticker"] for x in base]


def test_sector_detail_synthetic(client):
    d = client.get("/api/sectors/XLK").json()
    assert d["sector"] == "Technology" and d["data"] == "synthetic" and d["listing_id"]
    assert len(d["trail"]) == 60 and d["relative_chart"]["relative"][0] == pytest.approx(100)
    assert len(d["relative_chart"]["dates"]) == 252
    tickers = {x["ticker"] for x in d["constituents_in_app"]}
    assert {"AAPL", "MSFT", "NVDA"} <= tickers  # synthetic stocks classified as Technology
    assert all(x["namespace"] == "synthetic" for x in d["constituents_in_app"])
    for x in d["constituents_in_app"]:
        assert x["beats_sector"] == (x["rs_ratio_vs_sector"] > 100)
    assert d["holdings"]["top10"] == [] or all("analysis" not in h for h in d["holdings"]["top10"])  # real weights never get synthetic prices
    assert client.get("/api/sectors/AAPL").status_code == 404


def test_holdings_refresh_and_status(client):
    with client.Session() as db:
        out = S.refresh_holdings(db, ["XLK", "XLF"], fetch=_fake_fetch)
        assert [r["status"] for r in out["results"]] == ["updated", "failed"]
        st = {x["ticker"]: x for x in S.holdings_status(db)}
        assert st["XLK"]["count"] == 79 and st["XLK"]["as_of"] == "2026-11-04" and st["XLF"]["count"] == 0
    d = client.get("/api/sectors/XLK").json()
    h = d["holdings"]
    assert h["as_of"] == "2026-11-04" and [x["ticker"] for x in h["top10"][:3]] == ["AAPL", "NVDA", "MSFT"]
    assert h["top10_weight_pct"] == pytest.approx(sum(x["weight_pct"] for x in h["top10"]))
    assert h["missing_prices"] == []  # synthetic mode doesn't ask for real prices


# ---------------------------------------------------------------- real data path (simulated Tiingo)

def test_real_mode_end_to_end(fresh_db, monkeypatch):  # noqa: F811
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    fake = DistinctTiingo(session)
    with fresh_db() as db:
        md.refresh_all(db, fake.client)
        d = S.dashboard(db)
        assert d["data"] == "real" and d["status"] == "ok" and d["provenance"]["is_synthetic"] is False
        assert d["provenance"]["source"] == "tiingo" and d["last_refresh"] is not None
        assert all(r["status"] == "ok" for r in d["rows"])
        syn = S.dashboard(db, data="synthetic")
        assert syn["provenance"]["is_synthetic"] is True  # still available on request, never mixed in
        S.refresh_holdings(db, ["XLK"], fetch=_fake_fetch)
        res = S.download_constituents(db, "XLK", add=lambda db_, t: md.add_symbol(db_, t, fake.client))
        assert len(res["results"]) == 10 and all(r["status"] == "updated" for r in res["results"])
        det = S.sector_detail(db, "XLK")
        top = det["holdings"]["top10"]
        assert all(x["analysis"]["status"] == "ok" and x["analysis"]["namespace"] == "real" for x in top)
        assert det["holdings"]["missing_prices"] == [] and det["constituents_in_app"] == [] or \
            all(x["namespace"] == "real" for x in det["constituents_in_app"])
        assert len(det["strongest"]) == 3 and det["strongest"][0]["change_20d_pct"] >= det["weakest"][0]["change_20d_pct"]
        assert all(x["rs_ratio_vs_sector"] > 100 for x in det["beating_sector"])
        again = S.download_constituents(db, "XLK", add=lambda db_, t: pytest.fail("should not re-download"))
        assert all(r["status"] == "already_tracked" for r in again["results"])


def test_download_constituents_needs_holdings(client):
    r = client.post("/api/sectors/XLE/constituents/download")
    assert r.status_code == 400 and "Update holdings first" in r.json()["message"]


def test_identical_series_reported_not_invented(fresh_db, monkeypatch):  # noqa: F811
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    with fresh_db() as db:
        md.refresh_all(db, FakeTiingo(session).client)  # every symbol has the same prices as SPY
        d = S.dashboard(db, data="real")
        assert d["status"] == "ok" and all(r["status"] == "rrg_unavailable" for r in d["rows"])
        assert sum(d["quadrant_counts"].values()) == 0 and d["highlights"]["most_attractive"] is None


# ---------------------------------------------------------------- Europe (iShares STOXX Europe 600 sectors)

EXV1 = (Path(__file__).parent / "fixtures" / "ishares_exv1_holdings.csv").read_bytes()


def test_parse_real_ishares_file():
    f = H.parse_ishares(EXV1, "EXV1")
    assert f.etf_ticker == "EXV1" and f.as_of == date(2026, 11, 4)
    top = f.holdings[0]
    assert (top.ticker, top.exchange, top.currency, top.weight_pct) == ("HSBA", "London Stock Exchange", "GBP", 13.5)
    eq = [h for h in f.holdings if h.ticker]
    assert sum(h.weight_pct for h in eq) == pytest.approx(99.4, abs=0.2)
    assert all(h.ticker is None for h in f.holdings if h.name in ("PLN/EUR", "STOXX 600 BANK DEC 26"))  # FX / futures
    with pytest.raises(MarketDataError, match="as of"):
        H.parse_ishares(b"Ticker,Name\n", "EXV1")
    with pytest.raises(MarketDataError, match="header"):
        H.parse_ishares('Fund Holdings as of,"04/Nov/2026"\n\nfoo,bar\n'.encode(), "EXV1")


def test_eu_region_definition_is_complete():
    from research.data.sectors import EU, EU_BENCHMARK
    assert len(EU.etfs) == 19 and len({e.ticker for e in EU.etfs}) == 19 and len({e.isin for e in EU.etfs}) == 19
    assert all(e.mic == "XETR" and e.isin.startswith("DE000") and e.holdings_path.startswith("/ch/individual/en/products/")
               for e in (*EU.etfs, EU_BENCHMARK))
    assert EU.default_benchmark == "EXSA" and EU_BENCHMARK.isin == "DE0002635307"


def test_eu_dashboard_synthetic(client):
    d = client.get("/api/sectors?region=eu").json()
    assert d["status"] == "ok" and d["data"] == "synthetic" and d["benchmark"] == "EXSA"
    assert d["region"]["id"] == "eu" and "ICB" in d["region"]["classification"] and d["region"]["currency"] == "EUR"
    assert len(d["rows"]) == 19 and all(r["status"] == "ok" for r in d["rows"]) and sum(d["quadrant_counts"].values()) == 19
    assert d["provenance"]["exchange_timezone"] == "Europe/Berlin" and any("not GICS" in n or "GICS" in n for n in d["notes"])
    assert {x["id"] for x in d["regions"]} == {"us", "eu"}
    assert client.get("/api/sectors?region=eu&benchmark=SPY").status_code == 400
    assert client.get("/api/sectors?region=asia").status_code == 400
    us = client.get("/api/sectors").json()
    assert {r["ticker"] for r in us["rows"]} == SECTOR_TICKERS  # the US view is unchanged


def test_eu_detail_keeps_regions_apart(client):
    d = client.get("/api/sectors/EXV3?benchmark=SPY").json()  # a US benchmark carried over falls back to EXSA
    assert d["benchmark"] == "EXSA" and d["region"]["id"] == "eu" and d["sector"] == "Technology"
    assert {x["ticker"] for x in d["constituents_in_app"]} == {"ASML", "SAP"}  # European Technology stocks only
    us = client.get("/api/sectors/XLK").json()
    assert not {"ASML", "SAP"} & {x["ticker"] for x in us["constituents_in_app"]}


def test_eu_holdings_refresh_and_exchange_support(client):
    with client.Session() as db:
        out = S.refresh_holdings(db, ["EXV1"], fetch_ishares=lambda t, path: H.parse_ishares(EXV1, t))
        assert out["results"] == [{"ticker": "EXV1", "status": "updated", "holdings": 80, "as_of": "2026-11-04"}]
    d = client.get("/api/sectors/EXV1").json()
    h = d["holdings"]
    assert h["source"].startswith("iShares") and h["as_of"] == "2026-11-04" and h["top10"][0]["exchange"] == "London Stock Exchange"
    by = {x["ticker"]: x for x in h["top10"]}
    assert by["HSBA"]["price_supported"] and by["INGA"]["price_supported"] and by["BNP"]["price_supported"]
    assert not by["SAN"]["price_supported"] and "Bolsa De Madrid" in h["unsupported_exchanges"]


class DistinctEodhd:
    """Simulated EODHD with a distinct deterministic price path per symbol."""

    def __init__(self, data_end):
        import httpx
        import numpy as np
        from research.market_data.eodhd import EodhdClient
        from .test_eodhd import KEY, MIC_OF, trading_days
        self.calls = []

        def handle(req):
            self.calls.append(req)
            sym = req.url.path.rsplit("/", 1)[-1]
            ticker, suffix = sym.rsplit(".", 1)
            start = date.fromisoformat(req.url.params["from"])
            days = [d for d in trading_days(MIC_OF[suffix], data_end, 1400) if d >= start]
            rng = np.random.default_rng(sum(map(ord, sym)) * 104729)
            p = 50 * np.exp(np.cumsum(0.012 * rng.standard_normal(1400)))[-len(days):] if days else []
            return httpx.Response(200, json=[{"date": d.isoformat(), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                                              "adjusted_close": c, "volume": 5000} for d, c in zip(days, p)])
        self.client = EodhdClient(KEY, httpx.Client(transport=httpx.MockTransport(handle)))


def test_eu_real_mode_end_to_end(fresh_db, monkeypatch):  # noqa: F811
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from pydantic import SecretStr

    from research.core.config import settings
    from research.market_data import eu_service as eu
    monkeypatch.setattr(settings, "eodhd_api_key", SecretStr("k"))
    now = datetime(2025, 12, 30, 22, tzinfo=ZoneInfo("Europe/Berlin"))
    fake = DistinctEodhd(date(2025, 12, 30))
    with fresh_db() as db:
        eu.refresh_all(db, fake.client, now=now)
        d = S.dashboard(db, "eu")
        assert d["data"] == "real" and d["status"] == "ok" and d["provenance"]["source"] == "eodhd"
        assert d["provenance"]["is_synthetic"] is False and all(r["status"] == "ok" for r in d["rows"])
        S.refresh_holdings(db, ["EXV1"], fetch_ishares=lambda t, path: H.parse_ishares(EXV1, t))
        res = S.download_constituents(db, "EXV1", add=lambda db_, t, mic: eu.add_symbol(db_, t, mic, fake.client))
        st = {r["ticker"]: r["status"] for r in res["results"]}
        assert st["HSBA"] == "updated" and st["BNP"] == "updated" and st["SAN"] == "unsupported_exchange"
        det = S.sector_detail(db, "EXV1")
        top = {x["ticker"]: x for x in det["holdings"]["top10"]}
        assert top["HSBA"]["analysis"]["status"] == "ok" and top["HSBA"]["analysis"]["namespace"] == "real"
        assert top["SAN"].get("analysis") is None and det["holdings"]["missing_prices"] == []
        assert eu.find_listing(db, "BNP", "XPAR").currency == "EUR"  # Euronext Paris via EODHD ".PA"
