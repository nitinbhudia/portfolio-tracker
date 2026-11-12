"""Alert evaluation, closed bars, dedup, cooldown and API (PHASE_6_TASK.md §7)."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from research.db import models as m
from research.engine import alerts as A
from research.services import alerts as svc
from research.services import analysis as an

PROV_KEYS = ("source", "is_synthetic", "as_of", "exchange_timezone", "is_delayed", "delay_minutes", "stale")


@pytest.fixture()
def fresh(client):
    """Empty alert tables, default config, empty watchlist."""
    def reset():
        with client.Session() as db:
            for model in (m.Alert, m.AlertState, m.WatchlistItem):
                db.execute(delete(model))
            for key in (svc.CONFIG_KEY, svc.LAST_EVAL_KEY, svc.ROTATION_STATE_KEY):
                row = db.get(m.AppSetting, key)
                if row:
                    db.delete(row)
            db.commit()
    reset()
    yield client
    reset()


def _put(client, cfg):
    r = client.put("/api/alerts/config", json=cfg)
    assert r.status_code == 200, r.text
    return r.json()


def _rewind(client, bars: int):
    """Move every listing's evaluation state back by `bars` closed bars (simulates new bars arriving)."""
    with client.Session() as db:
        for st in db.scalars(select(m.AlertState)).all():
            dates = [d for d in db.scalars(select(m.PriceBar.date).where(m.PriceBar.listing_id == st.listing_id)
                                           .order_by(m.PriceBar.date)).all()]
            st.last_bar_date = dates[-1 - bars]
        db.commit()


# ---------------------------------------------------------------- closed bars

NY = m.Exchange(mic="XNYS", name="NYSE", timezone="America/New_York", currency="USD", close_time="16:00")


def _ny(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo("America/New_York"))


def test_is_closed_uses_exchange_clock():
    d = date(2026, 3, 10)
    assert svc.is_closed(d, NY, _ny(2026, 3, 10, 15, 0)) is False  # session still open
    assert svc.is_closed(d, NY, _ny(2026, 3, 10, 17, 0)) is False  # closed, EOD data not yet published
    assert svc.is_closed(d, NY, _ny(2026, 3, 10, 18, 30)) is True
    assert svc.is_closed(d, NY, _ny(2026, 3, 11, 9, 0)) is True
    assert svc.is_closed(d, NY, _ny(2026, 3, 9, 20, 0)) is False  # future bar


def test_unclosed_last_bar_is_skipped(fresh):
    with fresh.Session() as db:
        now = datetime(2025, 12, 31, 15, 0, tzinfo=ZoneInfo("America/New_York"))  # before the last synthetic close
        s = svc.evaluate(db, "synthetic", "medium", now=now)
        states = db.scalars(select(m.AlertState)).all()
        us = [st for st in states if db.get(m.Listing, st.listing_id).exchange.timezone == "America/New_York"]
        europe = [st for st in states if st not in us]
        assert us and europe  # 15:00 in New York is after the close in Amsterdam, Frankfurt and Zurich
        assert s["skipped_unclosed_bars"] == len(us)
        assert all(st.last_bar_date < date(2025, 12, 31) for st in us)
        assert all(st.last_bar_date == date(2025, 12, 31) for st in europe)


# ---------------------------------------------------------------- evaluation

def test_first_evaluation_only_latest_bar_and_matches_engine(fresh):
    out = fresh.post("/api/alerts/evaluate").json()
    assert out["status"] == "ok" and out["scope"] == "holdings_and_watchlist"
    for k in PROV_KEYS:
        assert k in out["provenance"]
    with fresh.Session() as db:
        held = sorted(db.scalars(select(m.Holding.listing_id)).all())
        assert out["listings"] == len(held) == out["evaluated_listings"] == out["bars_evaluated"]
        cfg = svc.get_config(db)
        expected = 0
        for lid in held:
            b = an.load_bars(db, lid)
            expected += len(svc.events_at(b.df, len(b.df) - 1, 2.5, b.listing.instrument.asset_class == "index", cfg))
        stored = db.scalars(select(m.Alert).where(m.Alert.type != "sector_rotation")).all()
    assert out["created"] - out["rotation"]["created"] == expected == len(stored)
    assert all(a.bar_date == date(2025, 12, 31) and a.is_synthetic for a in stored)

    again = fresh.post("/api/alerts/evaluate").json()
    assert again["bars_evaluated"] == 0 and again["created"] == 0


def test_new_bars_evaluated_once_dedup_and_cooldown(fresh):
    sma_all = {"scope": "all", "rules": {"sma_cross": {"periods": [10, 20, 50]}}}
    _put(fresh, {**sma_all, "cooldown_bars": 0})
    fresh.post("/api/alerts/evaluate")
    with fresh.Session() as db:
        db.execute(delete(m.Alert))
        db.commit()
    _rewind(fresh, 10)
    no_cd = fresh.post("/api/alerts/evaluate").json()
    with fresh.Session() as db:
        n_listings = len(db.scalars(select(m.Listing.id)).all())
    assert no_cd["bars_evaluated"] == 10 * n_listings
    assert no_cd["suppressed_cooldown"] == 0 and no_cd["created"] > 0

    # same bars again: everything is a duplicate
    _rewind(fresh, 10)
    dup = fresh.post("/api/alerts/evaluate").json()
    assert dup["created"] == 0 and dup["duplicates"] == no_cd["created"]

    # with a 5-bar cooldown, repeats of the same key within 5 bars are suppressed
    with fresh.Session() as db:
        db.execute(delete(m.Alert))
        db.commit()
    _put(fresh, {**sma_all, "cooldown_bars": 5})
    fresh.post("/api/alerts/evaluate")  # config changed -> latest bar only
    with fresh.Session() as db:
        db.execute(delete(m.Alert))
        db.commit()
    _rewind(fresh, 10)
    cd = fresh.post("/api/alerts/evaluate").json()
    assert cd["suppressed_cooldown"] > 0
    assert cd["created"] + cd["suppressed_cooldown"] == no_cd["created"]
    with fresh.Session() as db:
        for lid in db.scalars(select(m.Listing.id)).all():
            dates = list(db.scalars(select(m.PriceBar.date).where(m.PriceBar.listing_id == lid).order_by(m.PriceBar.date)).all())
            idx = {d: i for i, d in enumerate(dates)}
            by_key: dict[str, list[int]] = {}
            for a in db.scalars(select(m.Alert).where(m.Alert.listing_id == lid)).all():
                by_key.setdefault(a.key, []).append(idx[a.bar_date])
            for positions in by_key.values():
                positions.sort()
                assert all(b - a > 5 for a, b in zip(positions, positions[1:]))


def test_backfill_is_capped(fresh):
    _put(fresh, {"scope": "all"})
    fresh.post("/api/alerts/evaluate")
    _rewind(fresh, 25)
    out = fresh.post("/api/alerts/evaluate").json()
    assert out["skipped_backfill_bars"] == 15 * out["evaluated_listings"]
    assert out["bars_evaluated"] == svc.MAX_BACKFILL_BARS * out["evaluated_listings"]


def test_config_change_resets_to_latest_bar(fresh):
    fresh.post("/api/alerts/evaluate")
    _rewind(fresh, 5)
    _put(fresh, {"cooldown_bars": 2})
    out = fresh.post("/api/alerts/evaluate").json()
    assert out["bars_evaluated"] == out["evaluated_listings"]  # one bar each, not five


def test_watchlist_extends_scope(fresh):
    lid = next(x["id"] for x in fresh.get("/api/listings").json()["listings"] if x["ticker"] == "SPX")
    base = fresh.post("/api/alerts/evaluate").json()["listings"]
    fresh.post("/api/watchlist", json={"listing_id": lid})
    assert fresh.post("/api/alerts/evaluate").json()["listings"] == base + 1


def test_no_lookahead_full_vs_truncated(client):
    cfg = A.validate_config({"rules": {"sma_cross": {"periods": [10, 20, 50, 100, 200]}}})
    with client.Session() as db:
        lid = db.scalar(select(m.Listing.id).where(m.Listing.ticker == "AAPL"))
        df = an.load_bars(db, lid).df
    for t in (230, 380, len(df) - 20):
        assert svc.events_at(df, t, 2.5, False, cfg) == svc.events_at(df.iloc[: t + 1], t, 2.5, False, cfg)


# ---------------------------------------------------------------- API

def test_config_api_validation(fresh):
    c = fresh.get("/api/alerts/config").json()
    assert c["config"] == A.DEFAULT_CONFIG and c["sma_choices"] == [10, 20, 50, 100, 200]
    for k in PROV_KEYS:
        assert k in c["provenance"]
    assert fresh.put("/api/alerts/config", json={"rules": {"rsi": {"overbought": 150}}}).status_code == 400
    assert fresh.put("/api/alerts/config", json={"scope": "mars"}).status_code == 400
    out = _put(fresh, {"cooldown_bars": 3, "rules": {"macd_cross": {"enabled": False}}})
    assert out["config"]["cooldown_bars"] == 3 and out["config"]["rules"]["macd_cross"]["enabled"] is False
    assert fresh.get("/api/alerts/config").json()["config"]["cooldown_bars"] == 3


def test_list_read_and_read_all(fresh):
    _put(fresh, {"scope": "all", "cooldown_bars": 0, "rules": {"sma_cross": {"periods": [10, 20]}}})
    fresh.post("/api/alerts/evaluate")
    _rewind(fresh, 2)  # 47 demo instruments: keep the list below its 500-row page
    fresh.post("/api/alerts/evaluate")
    lst = fresh.get("/api/alerts").json()
    assert lst["unread"] == len(lst["alerts"]) > 1
    for k in PROV_KEYS:
        assert k in lst["provenance"]
    a = lst["alerts"][0]
    assert {"title", "details", "type_label", "listing", "bar_date", "input_hash"} <= set(a)
    dates = [x["bar_date"] for x in lst["alerts"]]
    assert dates == sorted(dates, reverse=True)

    r = fresh.post(f"/api/alerts/{a['id']}/read").json()
    assert r["unread"] == lst["unread"] - 1
    assert all(x["id"] != a["id"] for x in fresh.get("/api/alerts?status=unread").json()["alerts"])
    assert fresh.post("/api/alerts/999999/read").status_code == 404
    assert fresh.get("/api/alerts?status=maybe").status_code == 400

    done = fresh.post("/api/alerts/read-all").json()
    assert done["unread"] == 0 and done["marked"] == lst["unread"] - 1
    s = fresh.get("/api/alerts/summary").json()
    assert s["unread"] == 0 and s["last_evaluation"]["version"] == "alerts-v1" and "provenance" in s


def test_refresh_endpoint_runs_alert_check(fresh):
    out = fresh.post("/api/refresh").json()
    assert out["alerts"]["status"] == "ok"
    assert fresh.get("/api/alerts/summary").json()["last_evaluation"] is not None


def test_timestamps_are_utc(fresh):
    _put(fresh, {"scope": "all"})
    fresh.post("/api/alerts/evaluate")
    _rewind(fresh, 3)
    fresh.post("/api/alerts/evaluate")
    a = fresh.get("/api/alerts").json()["alerts"]
    assert a and a[0]["created_at"].endswith("+00:00")
    ev = datetime.fromisoformat(fresh.get("/api/alerts/summary").json()["last_evaluation"]["at"])
    assert ev.tzinfo is not None and abs(ev - datetime.now(timezone.utc)) < timedelta(minutes=5)



# ---------------------------------------------------------------- sector rotation signals

def _rotation_alerts(client):
    with client.Session() as db:
        return db.scalars(select(m.Alert).where(m.Alert.type == "sector_rotation").order_by(m.Alert.bar_date)).all()


def _us_only(client):
    _put(client, {"rules": {"sector_rotation": {"regions": ["us"]}}})


def _dashboard_events(client, cats=("early_opportunity", "established", "exit_warning", "deterioration"), region="us"):
    d = client.get(f"/api/sectors?data=auto&region={region}").json()
    return d, [e for e in d["events"] if e["category"] in cats]


def test_rotation_first_check_latest_session_only(fresh):
    _us_only(fresh)
    out = fresh.post("/api/alerts/evaluate").json()
    rot = out["rotation"]
    assert rot["enabled"] and rot["data"] == "synthetic" and rot["sectors"] == 11 and rot["benchmark"] == "SPY"
    d, evs = _dashboard_events(fresh)
    latest = [e for e in evs if e["date"] == d["as_of"]]
    alerts = _rotation_alerts(fresh)
    assert rot["created"] == len(latest) == len(alerts)
    for a in alerts:
        assert a.is_synthetic and a.details["benchmark"] == "SPY" and a.title.startswith(a.details["sector"])
        assert a.direction in ("bullish", "bearish")
    # nothing new on the same data
    assert fresh.post("/api/alerts/evaluate").json()["rotation"]["created"] == 0


def test_rotation_new_sessions_match_the_sector_page(fresh):
    fresh.post("/api/alerts/evaluate")
    with fresh.Session() as db:  # pretend the last check was 15 sessions ago
        row = db.get(m.AppSetting, svc.ROTATION_STATE_KEY)
        d = fresh.get("/api/sectors").json()
        dates = sorted({p["date"] for r in d["rows"] for p in r["trail"]})
        back = dates[-16]
        row.value_json = {t: {**v, "last_date": back} for t, v in row.value_json.items()}
        db.execute(delete(m.Alert))
        db.commit()
    _put(fresh, {"cooldown_bars": 0, "rules": {**{k: {"enabled": False} for k in A.RULES}, "sector_rotation": {"regions": ["us"]}}})
    # a settings change resets to the latest session, so restore the state after saving the config
    with fresh.Session() as db:
        cfg = svc.get_config(db)
        rc = cfg["rules"]["sector_rotation"]
        chash = A.config_hash({"sector_rotation": rc, "data": "synthetic", "region": "us", "benchmark": "SPY"}, "rotation")
        row = db.get(m.AppSetting, svc.ROTATION_STATE_KEY)
        row.value_json = {t: {"last_date": back, "config_hash": chash} for t in row.value_json}
        db.commit()
    out = fresh.post("/api/alerts/evaluate").json()
    _, evs = _dashboard_events(fresh)
    expected = sorted((e["ticker"], e["date"], svc._rotation_key(e)) for e in evs if e["date"] > back)
    got = sorted((a.details["sector_ticker"], a.bar_date.isoformat(), a.key) for a in _rotation_alerts(fresh))
    assert got == expected and out["rotation"]["created"] == len(expected) > 0
    assert out["created"] == out["rotation"]["created"]  # per-instrument rules were all off


def test_rotation_categories_and_disable(fresh):
    _put(fresh, {"rules": {"sector_rotation": {"categories": ["exit_warning"]}}})
    fresh.post("/api/alerts/evaluate")
    assert all(a.details["category"] == "exit_warning" for a in _rotation_alerts(fresh))
    _put(fresh, {"rules": {"sector_rotation": {"enabled": False}}})
    with fresh.Session() as db:
        db.execute(delete(m.Alert))
        db.commit()
    out = fresh.post("/api/alerts/evaluate").json()
    assert out["rotation"] == {"enabled": False, "created": 0, "duplicates": 0, "suppressed_cooldown": 0, "sectors": 0}
    assert _rotation_alerts(fresh) == []


def test_rotation_unclosed_session_is_not_used(fresh):
    with fresh.Session() as db:
        now = datetime(2025, 12, 31, 15, 0, tzinfo=ZoneInfo("America/New_York"))
        rot = svc.evaluate(db, "synthetic", "medium", now=now)["rotation"]
        state = db.get(m.AppSetting, svc.ROTATION_STATE_KEY).value_json
        # 15:00 New York is after the Xetra close + 2 h, so Europe's 31 Dec counts; the US one doesn't yet
        assert rot["sectors"] == 30 and rot["regions"]["us"]["sectors"] == 11 and rot["regions"]["eu"]["sectors"] == 19
        assert {k: v["last_date"] for k, v in state.items() if k.startswith("XL")} == {k: "2025-12-30" for k in state if k.startswith("XL")}
        assert all(v["last_date"] == "2025-12-31" for k, v in state.items() if k.startswith("EX"))
        assert all(a.bar_date <= date(2025, 12, 30) for a in db.scalars(select(m.Alert).where(
            m.Alert.type == "sector_rotation", m.Alert.details["region"].as_string() == "us")).all())


@pytest.mark.parametrize("bad", [{"timeframe": "2y"}, {"benchmark": "TSLA"}, {"categories": ["buy_now"]}, {"categories": "exit_warning"},
                                 {"regions": ["asia"]}])
def test_rotation_config_validation(bad):
    with pytest.raises(ValueError):
        A.validate_config({"rules": {"sector_rotation": bad}})


def test_rotation_europe_matches_its_page(fresh):
    _put(fresh, {"rules": {"sector_rotation": {"regions": ["eu"]}}})
    out = fresh.post("/api/alerts/evaluate").json()["rotation"]
    assert out["regions"]["eu"]["benchmark"] == "EXSA" and out["regions"]["eu"]["sectors"] == 19 and "us" not in out["regions"]
    d, evs = _dashboard_events(fresh, region="eu")
    latest = sorted((e["ticker"], svc._rotation_key(e)) for e in evs if e["date"] == d["as_of"])
    got = sorted((a.details["sector_ticker"], a.key) for a in _rotation_alerts(fresh))
    assert got == latest and all(a.details["region"] == "eu" and "EXSA" in a.title for a in _rotation_alerts(fresh))
