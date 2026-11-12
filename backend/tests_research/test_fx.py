"""ECB reference rates (PHASE_2B_TASK.md §3)."""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from research.db import models as m
from research.market_data import fx
from research.market_data.tiingo import MarketDataError

from .conftest import ECB_CSV, fake_ecb_client

SAMPLE = (Path(__file__).parent / "fixtures" / "flex_sample.xml").read_text()


def test_client_parses_recorded_response():
    rates = fake_ecb_client().daily(["USD", "CHF"], date(2025, 12, 1))
    assert len(rates) == 20 and {r.currency for r in rates} == {"USD", "CHF"}
    first_usd = next(r for r in rates if r.currency == "USD")
    assert (first_usd.date, first_usd.rate) == (date(2025, 12, 1), 1.1646)


def test_client_empty_range_and_errors():
    assert fake_ecb_client(status=404).daily(["USD"], date(2030, 1, 1)) == []
    with pytest.raises(MarketDataError) as e:
        fake_ecb_client(status=503).daily(["USD"], date(2025, 1, 1))
    assert e.value.code == "provider_error"
    with pytest.raises(MarketDataError):
        fake_ecb_client(csv_text="TIME_PERIOD,OBS_VALUE\nnot-a-date,1.0\n").daily(["USD"], date(2025, 1, 1))


def _clear(db):
    db.execute(delete(m.FxRate).where(m.FxRate.is_synthetic.is_(False)))
    db.commit()


def test_refresh_stores_published_and_derived(client):
    with client.Session() as db:
        _clear(db)
        out = fx.refresh(db, fake_ecb_client(), today=date(2025, 12, 15))
        assert out["status"] == "updated" and out["new_days"] == 10 and out["last_date"] == "2025-12-12"
        rows = db.scalars(select(m.FxRate).where(m.FxRate.date == date(2025, 12, 1), m.FxRate.is_synthetic.is_(False))).all()
        by = {(r.base, r.quote): r for r in rows}
        assert by[("EUR", "USD")].rate == Decimal("1.1646") and by[("EUR", "USD")].source == "ecb"
        assert by[("USD", "CHF")].source == "ecb_derived"
        assert float(by[("USD", "CHF")].rate) == pytest.approx(0.9323 / 1.1646, abs=1e-9)
        # synthetic rates on the same dates are untouched
        assert db.scalar(select(m.FxRate).where(m.FxRate.date == date(2025, 12, 1), m.FxRate.is_synthetic.is_(True)))
        again = fx.refresh(db, fake_ecb_client(), today=date(2025, 12, 15))
        assert again["status"] == "up_to_date" and again["new_days"] == 0
        assert len(db.scalars(select(m.FxRate).where(m.FxRate.source == "ecb")).all()) == 20  # no duplicates
        r = fx.rate(db, "USD", "EUR", date(2025, 12, 7))  # weekend -> Friday 5th, inverted
        assert r["date"] == "2025-12-05" and r["stored_pair"] == "EURUSD"


def test_status_endpoint(client):
    s = client.post("/api/fx/refresh").json()
    assert s["result"]["status"] in ("updated", "up_to_date") and s["latest"]["EURUSD"]["source"] == "ecb"
    assert s["latest"]["USDCHF"]["source"] == "ecb_derived"
    for k in ("source", "is_synthetic", "as_of", "exchange_timezone", "is_delayed", "delay_minutes", "stale"):
        assert k in s["provenance"]
    assert client.get("/api/fx/status").json()["observations"] == 20


def test_demo_portfolio_never_uses_real_fx(client):
    with client.Session() as db:
        fx.refresh(db, fake_ecb_client(), today=date(2025, 12, 15))
    p = client.get("/api/portfolio?source=synthetic").json()
    assert p["fx_rates_used"] and all(r["is_synthetic"] is True for r in p["fx_rates_used"])


def test_ibkr_without_usd_rate_uses_ecb(client):
    with client.Session() as db:
        fx.refresh(db, fake_ecb_client(), today=date(2025, 12, 15))
    eur_only = re.sub(r"<ConversionRates>.*?</ConversionRates>", "", SAMPLE, flags=re.S)
    eur_only = "\n".join(l for l in eur_only.splitlines() if 'currency="USD"' not in l and 'currency="CHF"' not in l)
    assert client.post("/api/broker/ibkr-flex/import", files={"file": ("f.xml", eur_only, "text/xml")}).json()["status"] == "success"
    try:
        p = client.get("/api/portfolio?source=ibkr_flex&base=USD").json()
        assert p["base_currency"] == "USD"
        used = {u["pair"]: u for u in p["fx_rates_used"]}
        assert used["EURUSD"]["source"] == "ecb" and used["EURUSD"]["date"] == "2025-12-12"
        eurusd = next(float(x.split(",")[7]) for x in ECB_CSV.splitlines() if ",USD,EUR," in x and "2025-12-12" in x)
        assert p["totals"]["market_value"] == pytest.approx((1400 + 1200) * eurusd, abs=0.02)
        assert any("ECB reference rate" in w for w in p["warnings"])
    finally:
        with client.Session() as db:
            _clear(db)
        client.post("/api/broker/ibkr-flex/import", files={"file": ("flex.xml", SAMPLE, "text/xml")})
