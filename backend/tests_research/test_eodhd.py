"""EODHD European prices (PHASE_2B_TASK.md §1, §6.1). All HTTP is simulated."""
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from research.core.calendars import eu_holidays
from research.core.config import settings
from research.db import models as m
from research.market_data import eu_service as eu
from research.market_data import service as md
from research.market_data.eodhd import EodhdClient, eodhd_symbol
from research.market_data.tiingo import MarketDataError
from research.services import analysis as an

KEY = "eodhd-secret-token-9876543210"
FLEX = (Path(__file__).parent / "fixtures" / "flex_sample.xml").read_text()
MIC_OF = {"XETRA": "XETR", "AS": "XAMS", "SW": "XSWX", "LSE": "XLON", "PA": "XPAR"}


def trading_days(mic: str, end: date, n: int) -> list[date]:
    hol, out, d = eu_holidays(mic), [], end
    while len(out) < n:
        if np.is_busday(np.datetime64(d, "D"), holidays=hol):
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


class FakeEodhd:
    """Serves EU-calendar bars up to `data_end`. `factor(d)` = adjusted_close / close on day d."""

    def __init__(self, data_end: date, factor=lambda d: 1.0, status: int = 200, unknown=("NOPE",)):
        self.data_end, self.factor, self.status, self.unknown = data_end, factor, status, unknown
        self.calls: list[httpx.Request] = []
        self.client = EodhdClient(KEY, httpx.Client(transport=httpx.MockTransport(self.handle)))

    def handle(self, req: httpx.Request):
        self.calls.append(req)
        assert req.url.params["api_token"] == KEY and req.url.params["fmt"] == "json"
        if self.status != 200:
            return httpx.Response(self.status, text="nope")
        sym = req.url.path.rsplit("/", 1)[-1]
        ticker, suffix = sym.rsplit(".", 1)
        if ticker in self.unknown:
            return httpx.Response(404, text="Ticker Not Found.")
        start = date.fromisoformat(req.url.params["from"])
        days = [d for d in trading_days(MIC_OF[suffix], self.data_end, 1400) if d >= start]
        rows = []
        for d in days:
            c = 100.0 + (d.toordinal() % 50)
            rows.append({"date": d.isoformat(), "open": c - 1, "high": c + 2, "low": c - 2, "close": c,
                         "adjusted_close": round(c * self.factor(d), 4), "volume": 1000})
        return httpx.Response(200, json=rows)


def berlin(y, mo, d, h):
    return datetime(y, mo, d, h, tzinfo=ZoneInfo("Europe/Berlin"))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from research.data.seed import seed_universe
    from research.db.session import Base, make_engine
    eng = make_engine(f"sqlite:///{tmp_path / 'eu.db'}")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, expire_on_commit=False)
    with S() as db:
        seed_universe(db, n=60)
        db.commit()
    monkeypatch.setattr(settings, "eodhd_api_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "eodhd_daily_budget", 1000)
    return S


def _import_flex(db):
    from research.broker import service as broker
    from research.broker.ibkr_flex import parse_flex_statement
    broker.run_sync(db, lambda: parse_flex_statement(FLEX.encode()), source="ibkr_flex_file", enforce_cooldown=False)


# ---------------------------------------------------------------- client

def test_client_adjusts_ohlc_and_keeps_raw_close():
    fake = FakeEodhd(date(2025, 12, 30), factor=lambda d: 0.9)
    bars = fake.client.daily("SAP.XETRA", date(2025, 12, 15))
    b = bars[-1]
    c = 100.0 + (b.date.toordinal() % 50)
    assert b.raw_close == c and b.close == pytest.approx(c * 0.9, abs=1e-3)
    assert b.open == pytest.approx((c - 1) * 0.9 * (round(c * 0.9, 4) / (c * 0.9)), abs=1e-3)
    assert b.high == pytest.approx((c + 2) * b.close / c) and b.volume == 1000 and b.raw_volume is None
    assert [x.date for x in bars] == sorted(x.date for x in bars)


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "auth"), (402, "plan_limit"), (429, "rate_limited"), (500, "http_500")])
def test_client_errors_never_contain_token(status, code):
    with pytest.raises(MarketDataError) as e:
        FakeEodhd(date(2025, 12, 30), status=status).client.daily("SAP.XETRA", date(2025, 12, 1))
    assert e.value.code == code and KEY not in e.value.message


def test_not_found_and_network_error_redacted():
    with pytest.raises(MarketDataError) as e:
        FakeEodhd(date(2025, 12, 30)).client.daily("NOPE.XETRA", date(2025, 12, 1))
    assert e.value.code == "not_found"

    def boom(req):
        raise httpx.ConnectError(f"failed to connect to {req.url}")  # message contains the token
    c = EodhdClient(KEY, httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(MarketDataError) as e2:
        c.daily("SAP.XETRA", date(2025, 12, 1))
    assert e2.value.code == "network" and KEY not in e2.value.message and "ConnectError" in e2.value.message


def test_symbol_mapping():
    assert eodhd_symbol("sap", "XETR") == "SAP.XETRA" and eodhd_symbol("BP", "XLON") == "BP.LSE"
    assert eodhd_symbol("ASML", "XAMS") == "ASML.AS" and eodhd_symbol("NESN", "XSWX") == "NESN.SW"
    assert eodhd_symbol("BNP", "XPAR") == "BNP.PA"
    with pytest.raises(MarketDataError):
        eodhd_symbol("X", "XMIL")


def test_last_completed_session_per_exchange():
    assert eu.last_completed_session("XETR", berlin(2025, 12, 10, 19)) == date(2025, 12, 9)   # not published yet
    assert eu.last_completed_session("XETR", berlin(2025, 12, 10, 21)) == date(2025, 12, 10)
    assert eu.last_completed_session("XETR", berlin(2025, 4, 21, 22)) == date(2025, 4, 17)   # Easter Monday -> Thursday
    london = datetime(2025, 12, 10, 19, 31, tzinfo=ZoneInfo("Europe/London"))
    assert eu.last_completed_session("XLON", london) == date(2025, 12, 10)


# ---------------------------------------------------------------- refresh

def test_refresh_ibkr_eu_holdings(fresh_db):
    now = berlin(2025, 12, 30, 22)
    fake = FakeEodhd(date(2025, 12, 31))  # provider already has a bar for an unfinished session
    with fresh_db() as db:
        _import_flex(db)
        targets = eu.all_targets(db)
        assert {(t["ticker"], t["mic"]) for t in targets if t["origin"] == "ibkr"} == {("ASML", "XAMS"), ("NESN", "XSWX"), ("VWRL", "XAMS")}
        assert sum(t["origin"] == "sector" for t in targets) == 20  # EXSA + 19 sector ETFs for Sector Rotation
        res = eu.refresh_all(db, fake.client, now=now)
        assert all(r["status"] == "updated" for r in res["results"]) and len(res["results"]) == 23
        exv1 = eu.find_listing(db, "EXV1", "XETR")
        assert exv1.instrument.asset_class == "etf" and exv1.instrument.sector == "Banks" and exv1.instrument.isin == "DE000A0F5UJ7"
        asml = eu.find_listing(db, "ASML", "XAMS")
        assert asml.provider_symbol == "ASML.AS" and asml.currency == "EUR" and asml.instrument.isin == "NL0010273215"
        last = db.scalar(select(func.max(m.PriceBar.date)).where(m.PriceBar.listing_id == asml.id))
        assert last == date(2025, 12, 30)  # the 31st was not finished yet
        a = an.analyse_listing(db, asml.id)
        assert a["status"] == "ok" and a["provenance"]["source"] == "eodhd" and a["provenance"]["is_synthetic"] is False
        assert a["provenance"]["price_adjustment"] == "split_dividend"
        assert a["data_quality"]["gaps"] == [] and a["data_quality"]["calendar"] == "Euronext holidays"
        nesn = eu.find_listing(db, "NESN", "XSWX")
        assert an.analyse_listing(db, nesn.id)["data_quality"]["gaps"] == []  # Ascension, Whit Monday, 1 Aug...
        # same session again: no requests
        n = len(fake.calls)
        again = eu.refresh_all(db, fake.client, now=now)
        assert all(r["status"] == "up_to_date" for r in again["results"]) and len(fake.calls) == n
        # usage is logged under the eodhd provider
        assert eu.requests_used(db)["last_day"] == 23


def test_incremental_then_corporate_action_triggers_full(fresh_db):
    with fresh_db() as db:
        lst = eu.ensure_listing(db, "SAP", "XETR", "SAP SE", None, "EUR")
        db.commit()
        eu.refresh_listing(db, FakeEodhd(date(2025, 12, 10)).client, lst, now=berlin(2025, 12, 10, 22))
        inc = eu.refresh_listing(db, FakeEodhd(date(2025, 12, 12)).client, lst, now=berlin(2025, 12, 12, 22))
        assert inc["mode"] == "incremental" and inc["bars_added"] == 2
        # a dividend on 15 Dec re-scales all earlier adjusted closes
        div = FakeEodhd(date(2025, 12, 16), factor=lambda d: 0.98 if d < date(2025, 12, 15) else 1.0)
        r = eu.refresh_listing(db, div.client, lst, now=berlin(2025, 12, 16, 22))
        assert r["mode"] == "full (corporate action)" and len(div.calls) == 2 and r["bars_added"] == 2
        first = db.scalar(select(m.PriceBar).where(m.PriceBar.listing_id == lst.id).order_by(m.PriceBar.date).limit(1))
        assert float(first.close) == pytest.approx(float(first.raw_close) * 0.98, abs=1e-3)


def test_budget_and_auth_stop(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "eodhd_daily_budget", 1)
    with fresh_db() as db:
        _import_flex(db)
        res = eu.refresh_all(db, FakeEodhd(date(2025, 12, 30)).client, now=berlin(2025, 12, 30, 22))
        st = [r["status"] for r in res["results"]]
        assert st[0] == "updated" and set(st[1:]) == {"skipped_budget"} and len(st) == 23
    monkeypatch.setattr(settings, "eodhd_daily_budget", 1000)
    with fresh_db() as db:
        res = eu.refresh_all(db, FakeEodhd(date(2025, 12, 30), status=401).client, now=berlin(2025, 12, 30, 22))
        statuses = [(r["ticker"], r["status"], r.get("error_code")) for r in res["results"]]
        assert statuses == [("EXSA", "up_to_date", None), ("EXV5", "failed", "auth")]  # stops after the first auth error


def test_add_symbol_and_unknown_symbol(fresh_db):
    with fresh_db() as db:
        r = eu.add_symbol(db, "sap", "XETR", FakeEodhd(date(2025, 12, 30)).client)
        assert r["symbol"] == "SAP.XETRA" and r["status"] == "updated"
        assert {"ticker": "SAP", "mic": "XETR"} in eu._user_symbols(db)
        with pytest.raises(MarketDataError) as e:
            eu.add_symbol(db, "NOPE", "XETR", FakeEodhd(date(2025, 12, 30)).client)
        assert e.value.code == "not_found"
        assert eu.find_listing(db, "NOPE", "XETR") is None  # no empty listing left behind
        with pytest.raises(MarketDataError):
            eu.add_symbol(db, "UCG", "XMIL", FakeEodhd(date(2025, 12, 30)).client)
        eu.remove_symbol(db, "SAP", "XETR")
        assert eu._user_symbols(db) == []
        # Tiingo never picks up a European listing as a US target
        assert all(t["mic"] in md.US_MICS for t in md.all_targets(db))


def test_ibkr_eu_holding_gets_analysis_and_is_held(fresh_db, monkeypatch):
    from research.broker import service as broker
    from research.services.screener import _held_listing_ids
    with fresh_db() as db:
        _import_flex(db)
        eu.refresh_all(db, FakeEodhd(date(2025, 12, 30)).client, now=berlin(2025, 12, 30, 22))
        p = broker.value_broker_portfolio(db, "EUR")
        rows = {h["listing"]["ticker"]: h for h in p["holdings"]}
        assert rows["ASML"]["analysis_available"] is True and rows["ASML"]["listing"]["id"] is not None
        assert rows["ASML"]["analysis_provenance"]["source"] == "eodhd"
        assert eu.find_listing(db, "ASML", "XAMS").id in _held_listing_ids(db, "ibkr_flex")


# ---------------------------------------------------------------- API

def test_api_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "eodhd_api_key", None)
    s = client.get("/api/market-data/eu/status").json()
    assert s["configured"] is False and s["unverified_suffixes"] == ["XAMS", "XSWX"] and "provenance" in s
    r = client.post("/api/market-data/eu/symbols", json={"ticker": "SAP", "exchange": "XETR"})
    assert r.status_code == 400 and r.json()["error_code"] == "not_configured"
    assert client.post("/api/refresh").json()["eu_prices"]["error_code"] == "not_configured"
