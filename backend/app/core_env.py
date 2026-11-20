"""Load KEY=VALUE pairs from the app folder's .env (git-ignored) into the environment, without overriding
variables that are already set. Used for ANTHROPIC_API_KEY."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None) -> None:
    from app import demo
    if demo.DEMO:  # the demo copy never sees your price or broker keys, even ones set in the shell
        for k in ("TIINGO_API_KEY", "TIINGO_TOKEN", "EODHD_API_KEY", "IBKR_FLEX_TOKEN", "IBKR_FLEX_QUERY_ID"):
            os.environ.pop(k, None)
        os.environ["TIINGO_API_KEY"] = "demo"  # answered by app.demo.network with synthetic prices
    p = path or ROOT / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
        if demo.DEMO and k not in demo.ALLOWED_ENV_KEYS:
            continue
        if k and v and k not in os.environ:
            os.environ[k] = v
