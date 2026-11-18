"""Automatic daily price refresh: when it is due, one run with independent steps, backlog retry, on/off."""
from datetime import timedelta

from app.services import autorefresh as AR

from .test_api import client, upload  # noqa: F401  (fixture re-used)


def db_of(client):  # noqa: F811
    from app import main
    gen = main.app.dependency_overrides[main.get_db]()
    return next(gen)


def test_due_runs_steps_and_retries_backlog(client, monkeypatch):  # noqa: F811
    from datetime import date
    upload(client)
    db = db_of(client)
    monkeypatch.setattr(AR, "last_session", lambda: date(2026, 11, 17))
    assert AR.due(db)  # never run: due
    calls = []
    steps = {"fx": lambda: calls.append("fx"), "research": lambda: {"updated": 40, "waiting": 14},
             "history": lambda: (_ for _ in ()).throw(RuntimeError("Tiingo down"))}
    s = AR.run_once(db, steps)
    assert calls == ["fx"] and s["steps"]["fx"]["status"] == "ok" and s["steps"]["research"]["waiting"] == 14
    assert s["steps"]["history"] == {"status": "failed", "message": "RuntimeError: Tiingo down"}  # one failing step doesn't stop others
    assert s["backlog"] and s["next_retry_at"] and s["last_complete_session"] is None
    assert not AR.due(db)  # backlog: wait about an hour before retrying
    later = AR._now() + timedelta(minutes=66)
    assert AR.due(db, now=later)
    s = AR.run_once(db, {"research": lambda: {"updated": 14, "waiting": 0}})
    assert not s["backlog"] and s["last_complete_session"] == "2026-11-17" and not AR.due(db, now=later)
    monkeypatch.setattr(AR, "last_session", lambda: date(2026, 11, 18))
    assert AR.due(db)  # a new trading day closed
    assert client.put("/api/auto-refresh", json={"enabled": False}).json()["enabled"] is False
    assert not AR.due(db)
    st = client.get("/api/auto-refresh").json()
    assert st["latest_session"] == "2026-11-18" and st["steps"]["research"]["updated"] == 14


def test_positions_use_newer_daily_close(client):  # noqa: F811
    from app.db import models as m
    upload(client)
    db = db_of(client)
    client.put("/api/price-history/ticker/alpha corp", json={"ticker": "ALPH"})
    from datetime import date
    db.add(m.StockPrice(series="ALPH", date=date(2030, 1, 2), close=140.0, split=1.0))
    db.add(m.StockPrice(series="ALPH", date=date(2020, 1, 2), close=1.0, split=1.0))
    db.commit()
    from app.services import portfolio as P
    P._invalidate()
    a = next(p for p in client.get("/api/positions").json()["positions"] if p["stock"] == "Alpha Corp")
    assert a["price"] == 140.0 and a["price_date"] == "2030-01-02" and "Tiingo close (ALPH)" in a["price_source"]
