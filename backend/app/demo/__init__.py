"""Demo mode: the whole app running on made-up data, for showing it to other people.

The demo is a second copy of the backend (started by scripts/dev.sh on port 8002 with PT_DEMO=1). It is kept apart
from your real data by construction, not by care in each page:

- its two databases live in their own folder (backend/demo-data/, or PT_DEMO_DIR): it never opens portfolio.db or
  fibonacci_ai.db, so nothing it shows can come from them;
- it doesn't read your keys from .env (only the Claude key, so Ask works on the demo data);
- every network request it makes goes through a guard (app.demo.network): prices, exchange rates and index levels are
  answered with synthetic data on the spot, GitHub (updates) and anything unknown are refused;
- Updates & backups are switched off (they work on your real copy only).

The browser chooses Live or Demo with a cookie; the frontend sends /api/* to port 8001 (live) or 8002 (demo). There is
no fallback: if the demo backend is down, Demo pages show an error, never your data.

This module is imported very early (by the database modules), so it must not import anything from the app.
"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEMO = os.environ.get("PT_DEMO") == "1"
DEMO_DIR = Path(os.environ.get("PT_DEMO_DIR") or BACKEND_DIR / "demo-data").resolve()
TRACKER_DB = DEMO_DIR / "portfolio.db"
RESEARCH_DB = DEMO_DIR / "fibonacci_ai.db"
ALLOWED_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL")  # the only .env lines the demo reads
