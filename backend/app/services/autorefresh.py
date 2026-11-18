"""Automatic daily price refresh: everything you'd otherwise press by hand, once a new US trading day has closed.

Every CHECK_EVERY_S the app checks whether a refresh is due:
- a new trading day has closed since the last complete run (US end-of-day data is ready about 18:00 New York time,
  so in Europe that is late evening; if the app was closed then, it runs as soon as it is opened), or
- the last run left a backlog (Tiingo's free plan allows about 50 requests an hour): it then retries about an hour later
  until everything is done.

A run does, in order, each step on its own (one failing doesn't stop the others):
1. exchange rates (ECB) for Portfolio Tracker;
2. Research: your holdings, Tiingo prices for everything it tracks (watchlist, holdings, sector ETFs, benchmarks), European
   prices if EODHD is set up, then alerts;
3. Performance's daily price history for your stocks (Tiingo; open positions only once the history is complete).
Positions and the other pages then value your stocks at the latest close (portfolio.current_prices).
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone

from app.db import models as m

SETTING = "auto_refresh"
STATE = "auto_refresh_state"
CHECK_EVERY_S = 15 * 60
RETRY_AFTER = timedelta(minutes=65)
_running = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(db, key: str, default: dict) -> dict:
    row = db.get(m.Setting, key)
    return {**default, **(row.value or {})} if row else dict(default)


def _put(db, key: str, value: dict) -> None:
    row = db.get(m.Setting, key)
    if row is None:
        db.add(m.Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def last_session() -> date:
    from research.market_data.service import last_completed_session
    return last_completed_session()


def status(db) -> dict:
    s = _get(db, SETTING, {"enabled": True})
    st = _get(db, STATE, {})
    return {"enabled": s["enabled"], "running": _running.locked(), "last_run_at": st.get("last_run_at"),
            "last_complete_session": st.get("session"), "latest_session": last_session().isoformat(),
            "backlog": st.get("backlog", False), "next_retry_at": st.get("next_retry_at"), "steps": st.get("steps", {}),
            "check_every_minutes": CHECK_EVERY_S // 60}


def set_enabled(db, enabled: bool) -> dict:
    _put(db, SETTING, {"enabled": bool(enabled)})
    return status(db)


def due(db, now: datetime | None = None) -> bool:
    now = now or _now()
    if not _get(db, SETTING, {"enabled": True})["enabled"]:
        return False
    st = _get(db, STATE, {})
    if st.get("backlog") and st.get("next_retry_at"):  # something was left over: retry only after the wait
        return now >= datetime.fromisoformat(st["next_retry_at"])
    return (st.get("session") or "") < last_session().isoformat()


def _step(fn) -> dict:
    try:
        return {"status": "ok", **(fn() or {})}
    except Exception as e:  # noqa: BLE001  (each step is independent; the reason is shown on the Price history page)
        return {"status": "failed", "message": f"{type(e).__name__}: {e}"[:300]}


def _fx(db) -> dict:
    from . import history as HS
    HS._ensure_fx(db)
    return {}


def _research() -> dict:
    from research.api.routes import refresh_everything
    from research.db.session import SessionLocal
    with SessionLocal() as rdb:
        out = refresh_everything(rdb)
    pr, eu = out.get("prices") or {}, out.get("eu_prices") or {}
    if pr.get("status") == "failed":
        raise RuntimeError(pr.get("message"))
    return {"updated": pr.get("updated", 0), "up_to_date": pr.get("up_to_date", 0), "failed": pr.get("failed", 0),
            "waiting": pr.get("skipped_budget", 0) + (eu.get("skipped_budget", 0) or 0),
            "eu_updated": eu.get("updated"), "configured": pr.get("status") != "skipped",
            "alerts": (out.get("alerts") or {}).get("status")}


def _history(db) -> dict:
    from . import history as HS
    if not HS.tiingo_key():
        return {"configured": False}
    if HS._JOB["thread"] is not None and HS._JOB["thread"].is_alive():
        return {"skipped": "a download you started is still running"}
    r = HS.run_batch(db)
    return {"fetched": r["fetched"], "failed": r["failed"], "waiting": r["remaining"] if r["waiting_until"] else 0,
            "remaining": r["remaining"]}


def run_once(db, steps=None) -> dict:
    """One refresh, now (whatever `due` says). `steps` (name -> callable) is replaced in tests."""
    if not _running.acquire(blocking=False):
        return status(db)
    try:
        session = last_session().isoformat()
        steps = steps or {"fx": lambda: _fx(db), "research": _research, "history": lambda: _history(db)}
        results = {name: _step(fn) for name, fn in steps.items()}
        backlog = any(r.get("waiting") for r in results.values())
        failed = any(r["status"] == "failed" for r in results.values())
        prev = _get(db, STATE, {})
        _put(db, STATE, {"last_run_at": _now().isoformat(), "steps": results, "backlog": backlog or failed,
                         # the day counts as done only when nothing is left; else retry in about an hour
                         "session": session if not (backlog or failed) else prev.get("session"),
                         "next_retry_at": (_now() + RETRY_AFTER).isoformat() if backlog or failed else None})
        from . import history as HS
        from . import portfolio as P
        P._invalidate()
        HS._invalidate()
    finally:
        _running.release()
    return status(db)


def run_in_background() -> None:
    def go():
        db = m.SessionLocal()
        try:
            run_once(db)
        finally:
            db.close()
    threading.Thread(target=go, name="price-refresh-now", daemon=True).start()


def start(first_delay_s: int = 60) -> None:
    """Background checks while the app runs (started by scripts/dev.sh)."""
    def loop():
        time.sleep(first_delay_s)
        while True:
            db = m.SessionLocal()
            try:
                if due(db):
                    run_once(db)
            except Exception:  # noqa: BLE001  (never stop the app; the next check tries again)
                pass
            finally:
                db.close()
            time.sleep(CHECK_EVERY_S)
    threading.Thread(target=loop, name="price-refresh", daemon=True).start()
