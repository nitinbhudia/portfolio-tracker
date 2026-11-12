from datetime import date
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy import select

from research.data import synthetic
from research.data.seed import HoldingImportError, import_holdings
from research.db import models as m
from research.services import analysis as an


def _lid(client, ticker):
    return next(x["id"] for x in client.get("/api/listings").json()["listings"] if x["ticker"] == ticker)


def _assert_prov(p):
    for k in ("source", "is_synthetic", "as_of", "exchange_timezone", "is_delayed", "delay_minutes", "stale"):
        assert k in p
    assert p["is_synthetic"] is True


@pytest.mark.parametrize("path", ["/api/health", "/api/listings", "/api/portfolio", "/api/overview",
                                  "/api/listings/1", "/api/listings/1/bars", "/api/listings/1/analysis"])
def test_every_endpoint_has_provenance(client, path):
    r = client.get(path)
    assert r.status_code == 200
    _assert_prov(r.json()["provenance"])


def test_generator_is_deterministic():
    a = synthetic.generate_ohlcv("SAP", "XETR", 180, 0.25, date(2025, 12, 31), 600)
    b = synthetic.generate_ohlcv("SAP", "XETR", 180, 0.25, date(2025, 12, 31), 600)
    assert a == b and len(a) == 600
    assert all(r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"] for r in a)


def test_portfolio_valuation_with_dated_fx(client):
    p = client.get("/api/portfolio").json()
    assert p["base_currency"] == "USD"
    rates = {r["pair"]: r for r in p["fx_rates_used"]}
    assert set(rates) == {"EURUSD", "USDCHF"}
    total = Decimal(0)
    with client.Session() as db:
        for h in p["holdings"]:
            hd = db.get(m.Holding, h["holding_id"])
            bar = db.scalar(select(m.PriceBar).where(m.PriceBar.listing_id == hd.listing_id)
                            .order_by(m.PriceBar.date.desc()).limit(1))
            mv = Decimal(hd.quantity) * Decimal(bar.close)
            ccy = hd.listing.currency
            if ccy == "EUR":
                mv *= Decimal(str(rates["EURUSD"]["rate"]))
            elif ccy == "CHF":
                mv /= Decimal(str(rates["USDCHF"]["rate"]))
            assert h["market_value_base"] == pytest.approx(float(mv), abs=0.01)
            total += mv
    assert p["totals"]["market_value"] == pytest.approx(float(total), abs=0.05)
    assert p["totals"]["unrealised_pl"] == pytest.approx(p["totals"]["market_value"] - p["totals"]["cost_basis"], abs=0.01)


def test_portfolio_in_eur(client):
    usd = client.get("/api/portfolio").json()["totals"]["market_value"]
    eur = client.get("/api/portfolio?base=EUR").json()
    eurusd = next(r["rate"] for r in eur["fx_rates_used"] if r["pair"] == "EURUSD")
    assert eur["totals"]["market_value"] == pytest.approx(usd / eurusd, rel=1e-4)


def test_indices_not_in_holdings_and_rejected_on_import(client, tmp_path):
    tickers = {h["listing"]["ticker"] for h in client.get("/api/portfolio").json()["holdings"]}
    assert not tickers & {"SPX", "NDX", "DJI", "RUT"}
    f = tmp_path / "bad.csv"
    f.write_text("ticker,mic,quantity,avg_cost,opened_at\nSPX,INDX,1,5000,\n")
    with client.Session() as db, pytest.raises(HoldingImportError):
        import_holdings(db, f)


def test_index_analysis_excludes_volume(client):
    a = client.get(f"/api/listings/{_lid(client, 'SPX')}/analysis").json()
    assert a["latest"]["indicators"]["relvol20"]["data_quality"] == "not_applicable"
    for sc in a["scores"].values():
        assert "volume" in sc["excluded_components"]


def test_overview_index_strip(client):
    o = client.get("/api/overview").json()
    assert [i["listing"]["ticker"] for i in o["indices"]] == ["SPX", "NDX", "DJI", "RUT"]
    assert all(i["change_ytd_pct"] is not None for i in o["indices"])


def test_nesn_gap_is_reported(client):
    a = client.get(f"/api/listings/{_lid(client, 'NESN')}/analysis").json()
    assert a["data_quality"]["gaps"] == [{"after": "2025-07-16", "before": "2025-07-22", "missing_business_days": 3}]
    assert a["latest"]["indicators"]["sma200"]["data_quality"] == "gap_in_window"


def test_insufficient_history_in_warmup(client):
    lid = _lid(client, "AAPL")
    dates = [b["date"] for b in client.get(f"/api/listings/{lid}/bars").json()["bars"]]
    a = client.get(f"/api/listings/{lid}/analysis?as_of={dates[50]}").json()
    ind = a["latest"]["indicators"]
    assert ind["sma200"] == {"value": None, "data_quality": "insufficient_history"}
    assert ind["sma50"]["value"] is not None
    assert "trend" in a["scores"]["long"]["excluded_components"]
    before = client.get(f"/api/listings/{lid}/analysis?as_of=2000-01-01").json()
    assert before["status"] == "no_price_history"


def test_analysis_no_look_ahead_end_to_end(client):
    """Scores from a full-history snapshot at t == analysis computed on history truncated at t."""
    lid = _lid(client, "MSFT")
    with client.Session() as db:
        full = an.load_bars(db, lid)
        df = full.df
        o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
        from research.engine import indicators, swings
        ind = indicators.compute_all(o, h, l, c, v)
        sw = swings.detect_swings(h, l, ind["atr14"], 2.5)
        for t in np.random.default_rng(11).integers(60, len(df) - 1, 20):
            snap = an._snapshot(int(t), df, ind, sw, False)
            trunc = an.analyse_listing(db, lid, as_of=df["date"].iloc[int(t)], include_series=False)
            for hz in ("short", "medium", "long"):
                assert snap["scores"][hz]["total"] == trunc["scores"][hz]["total"]
            assert snap["fib"]["status"] == trunc["fibonacci"]["status"]
            assert snap["fib"].get("nearest") == trunc["fibonacci"].get("nearest")


def test_stored_results_reproducible(client):
    with client.Session() as db:
        for lst in db.scalars(select(m.Listing)).all():
            stored = db.scalars(select(m.TechnicalScore).where(m.TechnicalScore.listing_id == lst.id)).all()
            a = an.analyse_listing(db, lst.id, include_series=False)
            assert {s.horizon: s.total for s in stored} == {h: s["total"] for h, s in a["scores"].items()}
            assert all(s.input_hash == a["input_hash"] and s.params_hash == a["params_hash"] for s in stored)
            fib = db.scalar(select(m.FibonacciResult).where(m.FibonacciResult.listing_id == lst.id))
            assert fib.input_hash == a["input_hash"]


def test_sensitivity_changes_swings_and_validates(client):
    lid = _lid(client, "NVDA")
    hi = client.get(f"/api/listings/{lid}/analysis?sensitivity=high").json()
    lo = client.get(f"/api/listings/{lid}/analysis?sensitivity=low").json()
    assert len(hi["swings"]) > len(lo["swings"])
    assert hi["params_hash"] != lo["params_hash"]
    bad = client.get(f"/api/listings/{lid}/analysis?sensitivity=99")
    assert bad.status_code == 400 and set(bad.json()) == {"error_code", "message"}


def test_errors_have_no_stack_traces(client):
    for url in ("/api/listings/9999/analysis", "/api/listings/abc", "/api/portfolio?base=XYZ"):
        r = client.get(url)
        assert r.status_code >= 400
        body = r.text
        assert "Traceback" not in body and "File \"" not in body
        assert set(r.json()) == {"error_code", "message"}


def test_settings_roundtrip(client):
    r = client.put("/api/settings", json={"default_sensitivity": "low"})
    assert r.json()["settings"]["default_sensitivity"] == "low"
    assert client.put("/api/settings", json={"base_currency": "GBP"}).status_code == 422
    client.put("/api/settings", json={"default_sensitivity": "medium"})


def test_screener(client):
    r = client.get("/api/screener").json()
    rows = r["rows"]
    assert len(rows) == 47 and r["provenance"]["is_synthetic"] is True  # 15 demo + SPY/EXSA + 11 US + 19 EU sector ETFs
    aapl = next(x for x in rows if x["listing"]["ticker"] == "AAPL")
    a = client.get(f"/api/listings/{aapl['listing']['id']}/analysis").json()
    assert aapl["score_short"] == a["scores"]["short"]["total"]
    assert aapl["rsi14"] == a["latest"]["indicators"]["rsi14"]["value"]
    assert aapl["held"] is True
    spx = next(x for x in rows if x["listing"]["ticker"] == "SPX")
    assert spx["held"] is False and spx["relvol20"] is None
    assert client.get("/api/screener?sensitivity=bogus").status_code == 400
    assert len(client.get("/api/screener?namespace=real").json()["rows"]) == 0



def test_reseed_removes_rows_pointing_at_old_synthetic_listings(tmp_path):
    """Rebuilt demo listings get new ids, so nothing may keep pointing at the old ones."""
    from datetime import datetime, timezone

    from sqlalchemy import func
    from sqlalchemy.orm import sessionmaker

    from research.data.seed import _wipe, import_holdings, seed_universe
    from research.db.session import Base, make_engine
    eng = make_engine(f"sqlite:///{tmp_path / 'reseed.db'}")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, expire_on_commit=False)
    with S() as db:
        seed_universe(db, n=260)
        import_holdings(db)
        lid = db.scalar(select(m.Listing.id).where(m.Listing.ticker == "AAPL"))
        run = m.ScanRun(sensitivity="medium", atr_multiple=2.5, setups_version="v", score_version="v1", params_hash="x",
                        universe_size=1, scanned=1, coverage={}, finished_at=datetime.now(timezone.utc))
        db.add(run)
        db.flush()
        db.add_all([
            m.Alert(listing_id=lid, type="rsi", key="rsi:oversold", direction="bullish", bar_date=date(2025, 12, 31), title="t",
                    details={}, config_hash="c", input_hash="i", source="synthetic", is_synthetic=True),
            m.AlertState(listing_id=lid, last_bar_date=date(2025, 12, 31), config_hash="c"),
            m.ScanResult(run_id=run.id, listing_id=lid, status="ok", triggered=[], row={}),
            m.BacktestRun(listing_id=lid, strategy="ma_cross", mode="single", request={}, result={}, version="v",
                          params_hash="p", input_hash="i"),
            m.AppSetting(key="alert_rotation_state", value_json={"XLK": {"last_date": "2025-12-31"}}),
        ])
        db.commit()
        _wipe(db)
        seed_universe(db, n=260)
        db.commit()
        for model in (m.Alert, m.AlertState, m.ScanResult, m.ScanRun, m.BacktestRun):
            assert db.scalar(select(func.count()).select_from(model)) == 0, model.__name__
        assert db.get(m.AppSetting, "alert_rotation_state") is None
