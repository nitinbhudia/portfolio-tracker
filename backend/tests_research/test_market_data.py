import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest
from sqlalchemy import func, select

from research.core.calendars import us_holidays
from research.db import models as m
from research.market_data import service as md
from research.market_data.tiingo import MarketDataError, TiingoClient, to_tiingo_symbol
from research.services import analysis as an

KEY = "tiingo-secret-key-abcdef123456"
FLEX = (Path(__file__).parent / "fixtures" / "flex_sample.xml").read_text()


def nyse_days(end: date, n: int) -> list[date]:
    hol = us_holidays()
    out, d = [], end
    while len(out) < n:
        if np.is_busday(np.datetime64(d, "D"), holidays=hol):
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def bars_json(days, start_price=100.0, div_on=None):
    rng = np.random.default_rng(len(days))
    p = start_price * np.exp(np.cumsum(0.01 * rng.standard_normal(len(days))))
    out = []
    for d, c in zip(days, p):
        out.append({"date": f"{d.isoformat()}T00:00:00.000Z", "close": c * 1.01, "high": c * 1.02, "low": c * 0.99,
                    "open": c, "volume": 1_000_000, "adjClose": c, "adjHigh": c * 1.01, "adjLow": c * 0.98,
                    "adjOpen": c * 0.995, "adjVolume": 1_000_000, "divCash": 0.5 if d == div_on else 0.0, "splitFactor": 1.0})
    return out


class FakeTiingo:
    """MockTransport-backed Tiingo returning NYSE-calendar bars up to `session`."""

    def __init__(self, session: date, div_on: date | None = None, exchange="NASDAQ"):
        self.session, self.div_on, self.exchange = session, div_on, exchange
        self.calls = []
        self.client = TiingoClient(KEY, httpx.Client(transport=httpx.MockTransport(self.handle)))

    def handle(self, req: httpx.Request):
        self.calls.append(req)
        assert req.headers["Authorization"] == f"Token {KEY}"
        assert KEY not in str(req.url)
        parts = req.url.path.strip("/").split("/")  # tiingo/daily/{sym}[/prices]
        sym = parts[2]
        if sym == "nosuch":
            return httpx.Response(404, json={"detail": "Not found."})
        if len(parts) == 3:
            return httpx.Response(200, json={"ticker": sym.upper(), "name": f"{sym.upper()} Inc",
                                             "exchangeCode": self.exchange, "startDate": "2000-01-03", "endDate": self.session.isoformat()})
        start = date.fromisoformat(req.url.params["startDate"])
        all_days = nyse_days(self.session, 1400)
        days = [d for d in all_days if d >= start]
        return httpx.Response(200, json=bars_json(days, div_on=self.div_on)[-len(days):] if days else [])


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from research.data.seed import seed_universe
    from research.db.session import Base, make_engine
    eng = make_engine(f"sqlite:///{tmp_path / 'md.db'}")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, expire_on_commit=False)
    with S() as db:
        seed_universe(db, n=60)
        db.commit()
    return S


def test_us_holidays_2025_2026():
    h = {str(d) for d in us_holidays()}
    for d in ["2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
              "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25", "2026-04-03", "2026-07-03", "2026-11-26"]:
        assert d in h, d
    assert "2021-12-31" not in h  # Saturday New Year is not observed on Friday by NYSE


def test_symbol_mapping():
    assert to_tiingo_symbol("BRK B") == "brk-b" and to_tiingo_symbol("BRK.B") == "brk-b"


def test_last_completed_session():
    # Thursday 2026-11-26 is Thanksgiving; at 20:00 ET that day the last session is Wed 25th
    t = datetime(2026, 11, 27, 1, 0, tzinfo=timezone.utc)
    assert md.last_completed_session(t) == date(2026, 11, 25)
    # Monday before 18:00 ET -> previous Friday
    assert md.last_completed_session(datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)) == date(2026, 10, 30)


def test_refresh_downloads_history_and_is_real_not_synthetic(fresh_db, monkeypatch):
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    fake = FakeTiingo(session)
    with fresh_db() as db:
        res = md.refresh_all(db, fake.client)
        from research.data.sectors import SECTOR_TICKERS
        assert {r["ticker"] for r in res["results"]} == {"SPY", "QQQ", "DIA", "IWM"} | SECTOR_TICKERS
        xlk = md.find_real_listing(db, "XLK", "ARCX")
        assert xlk.instrument.asset_class == "etf" and xlk.instrument.sector == "Technology"
        assert all(r["status"] == "updated" for r in res["results"])
        spy = md.find_real_listing(db, "SPY", "ARCX")
        assert spy.namespace == "real"
        a = an.analyse_listing(db, spy.id)
        assert a["status"] == "ok" and a["provenance"]["is_synthetic"] is False and a["provenance"]["source"] == "tiingo"
        assert a["provenance"]["price_adjustment"] == "split_dividend"
        assert a["data_quality"]["gaps"] == []  # NYSE holidays are not reported as missing data
        assert a["latest"]["indicators"]["sma200"]["value"] is not None
        # synthetic AAPL and real listings coexist without collision (the fixture seeds the synthetic demo)
        assert db.scalar(select(func.count()).select_from(m.Listing).where(m.Listing.namespace == "synthetic")) == 47
        # second refresh on the same session makes no requests
        n = len(fake.calls)
        res2 = md.refresh_all(db, fake.client)
        assert all(r["status"] == "up_to_date" for r in res2["results"]) and len(fake.calls) == n


def test_incremental_then_dividend_triggers_full_refetch(fresh_db, monkeypatch):
    s1, s2 = date(2026, 10, 28), date(2026, 10, 30)
    with fresh_db() as db:
        monkeypatch.setattr(md, "last_completed_session", lambda now=None: s1)
        md.refresh_all(db, FakeTiingo(s1).client, only=["SPY"])
        spy = md.find_real_listing(db, "SPY")
        monkeypatch.setattr(md, "last_completed_session", lambda now=None: s2)
        f = FakeTiingo(s2)
        r = md.refresh_all(db, f.client, only=["SPY"])["results"][0]
        assert r["mode"] == "incremental" and r["bars_added"] == 2 and len(f.calls) == 1
        assert md._last_bar_date(db, spy.id) == s2
        s3 = date(2026, 11, 2)
        monkeypatch.setattr(md, "last_completed_session", lambda now=None: s3)
        f = FakeTiingo(s3, div_on=s3)
        r = md.refresh_all(db, f.client, only=["SPY"])["results"][0]
        assert r["mode"].startswith("full") and len(f.calls) == 2
        dupes = db.execute(select(m.PriceBar.date, func.count()).where(m.PriceBar.listing_id == spy.id)
                           .group_by(m.PriceBar.date).having(func.count() > 1)).all()
        assert dupes == []


def test_budget_stops_requests(fresh_db, monkeypatch):
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    monkeypatch.setattr(md, "HOURLY_BUDGET", 2)
    f = FakeTiingo(session)
    with fresh_db() as db:
        res = md.refresh_all(db, f.client)["results"]
        assert [r["status"] for r in res].count("updated") == 2
        assert [r["status"] for r in res].count("skipped_budget") == len(res) - 2  # 4 benchmarks + 11 sector ETFs
        assert len(f.calls) == 2


def test_add_symbol_and_errors(fresh_db, monkeypatch):
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    with fresh_db() as db:
        r = md.add_symbol(db, "msft", FakeTiingo(session).client)
        assert r["ticker"] == "MSFT" and r["status"] == "updated"
        assert "MSFT" in [t["ticker"] for t in md.all_targets(db)]
        with pytest.raises(MarketDataError) as e:
            md.add_symbol(db, "nosuch", FakeTiingo(session).client)
        assert e.value.code == "not_found"
        with pytest.raises(MarketDataError) as e:
            md.add_symbol(db, "OTCX", FakeTiingo(session, exchange="OTC").client)
        assert e.value.code == "unsupported_exchange"
        with pytest.raises(MarketDataError):
            md.add_symbol(db, "DROP TABLE;", FakeTiingo(session).client)
        md.remove_symbol(db, "MSFT")
        assert "MSFT" not in [t["ticker"] for t in md.all_targets(db)]


def test_auth_error_redacts_key():
    def h(req):
        return httpx.Response(200, json={"detail": f"Invalid token {KEY}"})
    c = TiingoClient(KEY, httpx.Client(transport=httpx.MockTransport(h)))
    with pytest.raises(MarketDataError) as e:
        c.daily("spy", date(2026, 1, 1))
    assert KEY not in e.value.message
    c2 = TiingoClient(KEY, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    with pytest.raises(MarketDataError) as e:
        c2.meta("spy")
    assert e.value.code == "auth"


def test_ibkr_holding_gets_real_analysis(fresh_db, monkeypatch):
    from research.broker.ibkr_flex import parse_flex_statement
    from research.broker.service import run_sync, value_broker_portfolio
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    with fresh_db() as db:
        run_sync(db, lambda: parse_flex_statement(FLEX), "ibkr_flex_file", enforce_cooldown=False)
        targets = md.all_targets(db)
        assert ("AAPL", "XNAS", "ibkr") in [(t["ticker"], t["mic"], t["origin"]) for t in targets]
        assert not any(t["ticker"] in ("ASML", "NESN") for t in targets)  # non-US not requested
        md.refresh_all(db, FakeTiingo(session).client)
        p = value_broker_portfolio(db, "USD")
        rows = {h["listing"]["ticker"]: h for h in p["holdings"]}
        assert rows["AAPL"]["analysis_available"] is True and rows["AAPL"]["listing"]["id"] is not None
        assert rows["AAPL"]["scores"]["short"] is not None
        assert rows["AAPL"]["market_value_base"] == 2000.0  # valuation still uses the IBKR mark
        assert rows["ASML"]["analysis_available"] is False
        assert "EODHD_API_KEY" in rows["ASML"]["analysis_note"]


def test_overview_uses_real_proxies(fresh_db, monkeypatch):
    from research.services.overview import index_strip
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    with fresh_db() as db:
        before = index_strip(db, "medium")
        assert all(i["provenance"]["is_synthetic"] for i in before)
        md.refresh_all(db, FakeTiingo(session).client)
        after = index_strip(db, "medium")
        assert [i["listing"]["ticker"] for i in after] == ["SPY", "QQQ", "DIA", "IWM"]
        assert all(i["provenance"]["is_synthetic"] is False and i["proxy_for"] for i in after)


def test_reseed_keeps_real_data(fresh_db, monkeypatch):
    from research.data.seed import _wipe, seed_universe
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    with fresh_db() as db:
        md.refresh_all(db, FakeTiingo(session).client, only=["SPY"])
        spy = md.find_real_listing(db, "SPY")
        nbars = db.scalar(select(func.count()).select_from(m.PriceBar).where(m.PriceBar.listing_id == spy.id))
        _wipe(db); seed_universe(db, n=60); db.commit()
        assert db.scalar(select(func.count()).select_from(m.PriceBar).where(m.PriceBar.listing_id == spy.id)) == nbars


def test_api_not_configured(client):
    r = client.post("/api/market-data/refresh")
    assert r.status_code == 400 and r.json()["error_code"] == "not_configured"
    st = client.get("/api/market-data/status").json()
    assert st["configured"] is False and [t["ticker"] for t in st["tracked"]][:4] == ["SPY", "QQQ", "DIA", "IWM"]


def test_sparklines_shapes_and_changes():
    import pandas as pd
    days = nyse_days(date(2026, 3, 31), 120)
    df = pd.DataFrame({"date": days, "close": [100 + i for i in range(120)]})
    s = an.sparklines(df)
    assert len(s["m3"]) <= an.SPARK_POINTS and s["m3"][-1] == 219
    # 3M = last 64 closes -> from 156 to 219
    assert s["m3_change_pct"] == pytest.approx((219 / 156 - 1) * 100)
    # YTD basis = last close of 2025
    last_2025 = max(i for i, d in enumerate(days) if d.year == 2025)
    assert s["ytd_change_pct"] == pytest.approx((219 / (100 + last_2025) - 1) * 100)
    assert s["ytd_start"] == days[last_2025].isoformat()
    assert an.sparklines(pd.DataFrame({"date": [], "close": []}))["m3"] == []


def test_force_refresh_and_refresh_one(fresh_db, monkeypatch):
    session = date(2026, 10, 30)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: session)
    with fresh_db() as db:
        md.refresh_all(db, FakeTiingo(session).client, only=["SPY"])
        spy = md.find_real_listing(db, "SPY")
        f = FakeTiingo(session)
        assert md.refresh_one(db, spy.id, client=f.client)["status"] == "up_to_date" and len(f.calls) == 0
        r = md.refresh_one(db, spy.id, force=True, client=f.client)
        assert r["mode"] == "full" and len(f.calls) == 1 and "usage" in r
        syn = db.scalar(select(m.Listing).where(m.Listing.namespace == "synthetic").limit(1))
        with pytest.raises(MarketDataError) as e:
            md.refresh_one(db, syn.id, client=f.client)
        assert e.value.code == "synthetic"


def test_refresh_everything_endpoint_reports_each_step(client):
    r = client.post("/api/refresh").json()
    assert r["prices"]["status"] == "skipped" and r["prices"]["error_code"] == "not_configured"
    assert r["ibkr"] is None  # holdings source is synthetic in the test DB
    assert client.post("/api/listings/1/refresh").status_code == 400  # synthetic listing


def test_screener_and_portfolio_include_sparklines(client):
    row = client.get("/api/screener").json()["rows"][0]
    assert 0 < len(row["spark"]["m3"]) <= 60 and row["spark"]["ytd_change_pct"] is not None
    h = client.get("/api/portfolio").json()["holdings"][0]
    assert len(h["spark"]["ytd"]) > 1


def test_unfinished_session_bar_is_not_stored(fresh_db, monkeypatch):
    """If Tiingo returns a bar for a session that hasn't finished, it is dropped."""
    completed = date(2026, 10, 29)
    monkeypatch.setattr(md, "last_completed_session", lambda now=None: completed)
    fake = FakeTiingo(date(2026, 10, 30))  # provider already has a (partial) bar for the 30th
    with fresh_db() as db:
        md.refresh_all(db, fake.client)
        spy = md.find_real_listing(db, "SPY", "ARCX")
        last = db.scalar(select(func.max(m.PriceBar.date)).where(m.PriceBar.listing_id == spy.id))
        assert last == completed
