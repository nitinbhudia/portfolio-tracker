"""Demo mode inside the running demo backend: what the Live/Demo switch shows, and Reset (rebuild the made-up data).

Reset builds a fresh demo in a separate process, into a new folder next to the demo databases, then swaps the files in
(the app's database connections are closed and reopened). The demo keeps working with the old data until then.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone

from app import demo

_lock = threading.Lock()
_state: dict = {"running": False, "started_at": None, "error": None}


def _built(db) -> dict:
    from app.db import models as m
    row = db.get(m.Setting, "demo")
    return row.value if row else {}


def info(db=None) -> dict:
    if not demo.DEMO:
        return {"demo": False}
    b = _built(db) if db is not None else {}
    return {"demo": True, "built_at": b.get("built_at"), "as_of": b.get("as_of"), "resetting": _state["running"],
            "reset_started_at": _state["started_at"], "reset_error": _state["error"]}


def _swap(tmp) -> None:
    from app.db import models as m
    from app.services import history as HS
    from app.services import portfolio as P
    from research.db import session as rs
    m.engine.dispose()
    rs.engine.dispose()
    for name in (demo.TRACKER_DB.name, demo.RESEARCH_DB.name):
        os.replace(tmp / name, demo.DEMO_DIR / name)
    m.engine.dispose()
    rs.engine.dispose()
    P._invalidate()
    HS._invalidate()


def _run() -> None:
    tmp = demo.DEMO_DIR / f".building-{os.getpid()}"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        env = {**os.environ, "PT_DEMO": "1", "PT_DEMO_DIR": str(tmp)}
        p = subprocess.run([sys.executable, "-m", "app.demo.build"], cwd=str(demo.BACKEND_DIR), env=env,
                           capture_output=True, text=True, timeout=900, check=False)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or "the build failed").strip().splitlines()[-1][:300])
        _swap(tmp)
        _state["error"] = None
    except Exception as e:  # noqa: BLE001  (shown on the switch; the old demo stays)
        _state["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _state["running"] = False


def reset(db=None) -> dict:
    """Rebuild the made-up data in the background (about half a minute)."""
    if not demo.DEMO:
        raise RuntimeError("Reset only exists in demo mode.")
    with _lock:
        if not _state["running"]:
            _state.update(running=True, started_at=datetime.now(timezone.utc).isoformat(), error=None)
            threading.Thread(target=_run, name="demo-reset", daemon=True).start()
    return info(db)
