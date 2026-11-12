import inspect
import re
from pathlib import Path

import httpx
import pytest

from research.broker import base as broker_base
from research.broker import ibkr_flex, service
from research.broker.base import BrokerError
from research.broker.ibkr_flex import IbkrFlexAdapter, parse_flex_statement
from research.db import models as m

SAMPLE = (Path(__file__).parent / "fixtures" / "flex_sample.xml").read_text()
TOKEN = "123456789012345678901234"
QUERY = "987654"


def _ok_send(ref="1111111111"):
    return f"<FlexStatementResponse timestamp='x'><Status>Success</Status><ReferenceCode>{ref}</ReferenceCode><url>u</url></FlexStatementResponse>"


def _fail(code, msg="Error"):
    return f"<FlexStatementResponse timestamp='x'><Status>Fail</Status><ErrorCode>{code}</ErrorCode><ErrorMessage>{msg}</ErrorMessage></FlexStatementResponse>"


def _adapter(responses, seen=None):
    it = iter(responses)

    def handler(req: httpx.Request):
        if seen is not None:
            seen.append(req)
        status, body = next(it)
        return httpx.Response(status, text=body)

    return IbkrFlexAdapter(TOKEN, QUERY, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


# ---------------------------------------------------------------- parsing

def test_parse_sample():
    s = parse_flex_statement(SAMPLE)
    assert s.accounts == {"U****234": "EUR"}
    assert [p.symbol for p in s.positions] == ["AAPL", "ASML", "NESN", "VWRL"]
    vwrl = s.positions[-1]
    assert vwrl.quantity == 10  # SUMMARY row only, LOT row ignored (no double counting)
    assert [x.asset_category for x in s.skipped] == ["OPT"]
    assert s.positions[0].isin == "US0378331005" and s.positions[1].isin == "NL0010273215"
    assert str(s.report_date) == "2026-01-02"
    assert ("USD", "EUR") in s.fx_rates and ("CHF", "EUR") in s.fx_rates


def test_parse_error_response_and_bad_xml():
    with pytest.raises(BrokerError) as e:
        parse_flex_statement(_fail("1012", "Token has expired."))
    assert e.value.code == "ibkr_1012" and "expired" in e.value.message
    with pytest.raises(BrokerError) as e:
        parse_flex_statement("not xml")
    assert e.value.code == "parse_error"


def test_parse_requires_open_positions_section():
    xml = SAMPLE.split("<OpenPositions>")[0] + "</FlexStatement></FlexStatements></FlexQueryResponse>"
    with pytest.raises(BrokerError) as e:
        parse_flex_statement(xml)
    assert e.value.code == "no_positions_section"


def test_xml_bomb_rejected():
    bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><FlexQueryResponse>&b;</FlexQueryResponse>'
    with pytest.raises(BrokerError):
        parse_flex_statement(bomb)


def test_mask_account():
    assert broker_base.mask_account("U1234567") == "U****567"
    assert broker_base.mask_account(None) == "unknown"


# ---------------------------------------------------------------- web service client

def test_fetch_polls_until_ready_and_only_calls_flex_endpoints():
    seen = []
    a = _adapter([(200, _ok_send()), (200, _fail("1019", "Statement generation in progress")), (200, SAMPLE)], seen)
    snap = a.fetch_snapshot()
    assert len(snap.positions) == 4
    assert [str(r.url).split("?")[0] for r in seen] == [ibkr_flex.SEND_URL, ibkr_flex.GET_URL, ibkr_flex.GET_URL]
    assert all(r.method == "GET" for r in seen)
    assert seen[1].url.params["q"] == "1111111111" and seen[0].url.params["q"] == QUERY


def test_send_request_failure_is_friendly_and_redacted():
    a = _adapter([(200, _fail("1015", f"Token {TOKEN} is invalid"))])
    with pytest.raises(BrokerError) as e:
        a.fetch_snapshot()
    assert e.value.code == "ibkr_1015" and TOKEN not in e.value.message


def test_unknown_error_message_is_redacted():
    a = _adapter([(200, _fail("1099", f"weird {TOKEN} error"))])
    with pytest.raises(BrokerError) as e:
        a.fetch_snapshot()
    assert TOKEN not in e.value.message and "***" in e.value.message


def test_http_error_and_network_error():
    a = _adapter([(503, "down")])
    with pytest.raises(BrokerError) as e:
        a.fetch_snapshot()
    assert e.value.code == "http_503"

    def boom(req):
        raise httpx.ConnectError(f"cannot connect to {req.url}")

    a = IbkrFlexAdapter(TOKEN, QUERY, client=httpx.Client(transport=httpx.MockTransport(boom)), sleep=lambda s: None)
    with pytest.raises(BrokerError) as e:
        a.fetch_snapshot()
    assert TOKEN not in e.value.message


def test_gives_up_after_max_polls():
    a = _adapter([(200, _ok_send())] + [(200, _fail("1019"))] * 6)
    with pytest.raises(BrokerError) as e:
        a.fetch_snapshot()
    assert e.value.code == "not_ready"


def test_broker_package_has_no_trading_capability():
    src = "".join(inspect.getsource(mod) for mod in (broker_base, ibkr_flex, service))
    for forbidden in ("placeOrder", "place_order", "/iserver/", "/order", "cancel_order", "modify_order", "httpx.post", ".post("):
        assert forbidden not in src, forbidden
    assert not re.search(r"def \w*order\w*\(", src, re.I)


# ---------------------------------------------------------------- sync + valuation (API)

def _set_source(client, src):
    assert client.put("/api/settings", json={"holdings_source": src}).status_code == 200


def test_sync_not_configured(client):
    r = client.post("/api/broker/ibkr-flex/sync")
    assert r.status_code == 400 and r.json()["error_code"] == "not_configured"
    st = client.get("/api/broker/ibkr-flex/status").json()
    assert st["configured"] is False and "token" not in str(st).lower().replace("ibkr_flex_token", "")


def test_import_file_and_value_portfolio_usd(client):
    r = client.post("/api/broker/ibkr-flex/import", files={"file": ("flex.xml", SAMPLE, "text/xml")})
    run = r.json()
    assert run["status"] == "success" and run["positions_count"] == 4 and len(run["skipped"]) == 1
    _set_source(client, "ibkr_flex")
    try:
        p = client.get("/api/portfolio").json()
        assert p["holdings_source"] == "ibkr_flex" and p["base_currency"] == "USD"
        assert p["provenance"]["is_synthetic"] is False and p["provenance"]["source"] == "ibkr_flex"
        rows = {h["listing"]["ticker"]: h for h in p["holdings"]}
        assert rows["AAPL"]["market_value_base"] == 2000.0  # USD, no conversion
        assert rows["ASML"]["market_value_base"] == pytest.approx(1400 / 0.92, abs=0.01)
        assert rows["NESN"]["market_value_base"] == pytest.approx(400 * 1.07 / 0.92, abs=0.01)
        assert p["totals"]["market_value"] == pytest.approx(2000 + 3028 / 0.92, abs=0.02)
        assert p["totals"]["cost_basis"] == pytest.approx(1500 + 3081.5 / 0.92, abs=0.02)
        assert all(h["analysis_available"] is False and h["listing"]["id"] is None for h in p["holdings"])
        assert rows["ASML"]["listing"]["exchange"] == "XAMS"
        assert any("OPT" in w for w in p["warnings"])
        assert all(f["is_synthetic"] is False for f in p["fx_rates_used"])
        # Overview works with real holdings; index strip stays synthetic and is labelled separately
        o = client.get("/api/overview").json()
        assert o["portfolio_provenance"]["is_synthetic"] is False
        assert o["indices_provenance"]["is_synthetic"] is True
        assert o["near_fibonacci"] == [] and len(o["best"]) == 3
    finally:
        _set_source(client, "synthetic")


def test_value_in_account_base_eur(client):
    client.post("/api/broker/ibkr-flex/import", files={"file": ("flex.xml", SAMPLE, "text/xml")})
    p = client.get("/api/portfolio?source=ibkr_flex&base=EUR").json()
    assert p["base_currency"] == "EUR"
    assert p["totals"]["market_value"] == pytest.approx(2000 * 0.92 + 1400 + 400 * 1.07 + 1200, abs=0.02)


def test_fallback_to_account_base_when_no_rate(client):
    """No USD rate in the report AND no ECB rates stored -> totals in the account base currency."""
    from sqlalchemy import delete
    with client.Session() as db:
        db.execute(delete(m.FxRate).where(m.FxRate.is_synthetic.is_(False)))
        db.commit()
    eur_only = re.sub(r"<ConversionRates>.*?</ConversionRates>", "", SAMPLE, flags=re.S)
    eur_only = "\n".join(l for l in eur_only.splitlines() if 'currency="USD"' not in l and 'currency="CHF"' not in l)
    run = client.post("/api/broker/ibkr-flex/import", files={"file": ("f.xml", eur_only, "text/xml")}).json()
    assert run["status"] == "success"
    p = client.get("/api/portfolio?source=ibkr_flex&base=USD").json()
    assert p["base_currency"] == "EUR" and p["requested_base_currency"] == "USD"
    assert any("Conversion Rates" in w for w in p["warnings"])


def test_failed_import_keeps_previous_positions(client):
    client.post("/api/broker/ibkr-flex/import", files={"file": ("flex.xml", SAMPLE, "text/xml")})
    bad = client.post("/api/broker/ibkr-flex/import", files={"file": ("x.xml", "garbage", "text/xml")}).json()
    assert bad["status"] == "failed" and bad["error_code"] == "parse_error"
    p = client.get("/api/portfolio?source=ibkr_flex").json()
    assert len(p["holdings"]) == 4


def test_sync_with_mock_adapter_and_cooldown(client, monkeypatch):
    monkeypatch.setattr(service, "default_flex_adapter",
                        lambda: _adapter([(200, _ok_send()), (200, SAMPLE)]))
    r1 = client.post("/api/broker/ibkr-flex/sync").json()
    assert r1["status"] == "success" and r1["source"] == "ibkr_flex"
    r2 = client.post("/api/broker/ibkr-flex/sync")
    assert r2.status_code == 429 and r2.json()["error_code"] == "cooldown"
    with client.Session() as db:
        runs = db.query(m.BrokerSyncRun).all()
        assert all(TOKEN not in (x.message or "") for x in runs)


def test_failed_sync_records_run_without_secret(client, monkeypatch):
    monkeypatch.setattr(service.settings, "broker_sync_cooldown_seconds", 0)
    monkeypatch.setattr(service, "default_flex_adapter", lambda: _adapter([(200, _fail("1012", f"expired {TOKEN}"))]))
    r = client.post("/api/broker/ibkr-flex/sync").json()
    assert r["status"] == "failed" and r["error_code"] == "ibkr_1012" and TOKEN not in r["message"]
    assert len(client.get("/api/portfolio?source=ibkr_flex").json()["holdings"]) == 4  # previous kept


def test_no_sync_yet_message(tmp_path):
    from sqlalchemy.orm import sessionmaker

    from research.db.session import Base, make_engine
    eng = make_engine(f"sqlite:///{tmp_path / 'e.db'}")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as db:
        p = service.value_broker_portfolio(db, "USD")
    assert p["status"] == "not_synced" and p["holdings"] == []
