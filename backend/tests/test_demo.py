"""Demo mode: made-up data only, kept apart from your real data by construction (see app/demo/__init__.py)."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import demo
from app.demo import build as B
from app.demo import market
from app.importer import live_portfolio as L

from .test_api import client  # noqa: F401  (fixture re-used)

BACKEND = Path(__file__).resolve().parents[1]


def run_demo(code: str, tmp: Path, extra_env: dict | None = None) -> dict:
    """Run `code` in a fresh demo-mode process (the guard patches httpx for the whole process) and return its JSON."""
    env = {**os.environ, "PT_DEMO": "1", "PT_DEMO_DIR": str(tmp), **(extra_env or {})}
    p = subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=600, check=False)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_demo_uses_its_own_databases_and_never_your_keys(tmp_path):
    envf = tmp_path / "fake.env"
    envf.write_text("TIINGO_API_KEY=real-secret\nEODHD_API_KEY=real-eu\nANTHROPIC_API_KEY=claude-key\n")
    out = run_demo(f"""
import json, os
from app.core_env import load_env
load_env(__import__('pathlib').Path({str(envf)!r}))
from app.db import models as m
from research.core.config import settings as s
print(json.dumps({{"tracker": m.DATABASE_URL, "research": s.database_url, "tiingo": os.environ.get("TIINGO_API_KEY"),
  "eodhd": os.environ.get("EODHD_API_KEY"), "claude": os.environ.get("ANTHROPIC_API_KEY"),
  "r_tiingo": s.tiingo_api_key.get_secret_value(), "r_eodhd": s.eodhd_api_key.get_secret_value(), "ibkr": s.ibkr_flex_token}}))
""", tmp_path, {"TIINGO_API_KEY": "real-secret-in-shell", "EODHD_API_KEY": "real-eu-in-shell"})
    assert out["tracker"] == f"sqlite:///{tmp_path / 'portfolio.db'}" and out["research"] == f"sqlite:///{tmp_path / 'fibonacci_ai.db'}"
    assert out["tiingo"] == "demo" and out["eodhd"] is None and out["r_tiingo"] == "demo" and out["r_eodhd"] == "demo"
    assert out["claude"] == "claude-key" and out["ibkr"] is None  # only the Claude key is read from .env


def test_network_guard_fakes_providers_and_blocks_everything_else(tmp_path):
    out = run_demo("""
import json, httpx
from datetime import date
from app.core_env import load_env; load_env()
from app.demo import network; network.install()
from app.services import history as HS
from app.engine import fx as FX, benchmarks as BM
from research.market_data.tiingo import TiingoClient
from research.market_data.eodhd import EodhdClient
res = {}
res["tracker"] = HS.fetch_tiingo("NWRX", date(2024, 1, 2), date(2024, 1, 5))[0][1]
res["research"] = TiingoClient("demo").daily("NWRX", date(2024, 1, 2))[0].close
res["eu"] = EodhdClient("demo").daily("RHWK.XETRA", date(2024, 1, 2))[0].close
res["fx"] = FX.fetch(["GBP"], date(2024, 1, 2))[0][2]
res["fred"] = BM.fetch("fred", "SP500")[0][1]
for url in ("https://api.github.com/repos/a/b", "https://example.com/", "https://ndcdyn.interactivebrokers.com/x"):
    try:
        httpx.Client(proxy=None).get(url); res[url] = "sent"
    except httpx.ConnectError:
        res[url] = "blocked"
res["log"] = sorted({k for _, k in network.LOG})
print(json.dumps(res))
""", tmp_path)
    assert out["tracker"] == out["research"] == market.close_on("NWRX", __import__("datetime").date(2024, 1, 2))
    assert out["eu"] > 0 and 0.7 < out["fx"] < 1.1 and out["fred"] > 0
    assert all(out[u] == "blocked" for u in out if u.startswith("https://"))
    assert out["log"] == ["blocked", "fake"]


def test_market_is_deterministic_and_never_rewrites_the_past():
    from datetime import date
    a = market.bars("NWRX", date(2023, 1, 2), date(2023, 3, 1))
    b = market.bars("NWRX", date(2023, 1, 2))[: len(a)]
    assert a == b and len(a) > 30
    assert market.bars("ANYTHING", date(2024, 1, 2), date(2024, 1, 31))  # any ticker gets prices
    assert market.bars("NWRX", date(2024, 1, 2), date(2024, 1, 31)) != market.bars("HLXA", date(2024, 1, 2), date(2024, 1, 31))


def test_made_up_workbook_imports_cleanly(client):  # noqa: F811
    lots = B.plan()
    data = B.workbook(lots)
    w = L.read(data)
    assert {g["name"] for g in w.groups} == {"Long term", "Tech leaders", "Trading", "Dividend", "Europe", "Crypto"}
    r = client.post("/api/import", files={"file": ("demo.xlsx", data, "application/octet-stream")})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["review_pending"] == 1 and s["review_by_kind"] == {"sale_unlinked": 1}  # the one typed sale, to show Review
    ck = client.get("/api/check").json()["sales_log"]
    assert ck["lines_matching"] == ck["lines"] - 1 and abs(ck["difference"] + 420) < 0.01  # FIFO agrees with every linked sale
    pos = client.get("/api/positions").json()["positions"]
    assert {p["stock"] for p in pos} == {x.company.name for x in lots if not x.sale}


def test_deposits_cover_every_purchase():
    lots = B.plan()
    flows = B.deposits(lots)
    assert flows and all(d >= B.START.replace(day=1) for d, _ in flows) and sum(v for _, v in flows) > 0


def test_build_refuses_outside_demo_mode(monkeypatch):
    monkeypatch.setattr(demo, "DEMO", False)
    with pytest.raises(SystemExit):
        B.build()


def test_live_mode_has_no_demo_switches(client):  # noqa: F811
    assert client.get("/api/mode").json() == {"demo": False}
    assert client.post("/api/demo/reset").status_code == 400


def test_demo_mode_switches_off_updates_and_backups(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(demo, "DEMO", True)
    assert client.get("/api/maintenance").json()["backups"] == []
    for method, path in (("post", "/api/backups"), ("post", "/api/maintenance/update"), ("get", "/api/maintenance/check"),
                         ("post", "/api/backups/x/restore"), ("get", "/api/backups/x/download"), ("delete", "/api/backups/x")):
        r = getattr(client, method)(path)
        assert r.status_code == 400 and "demo mode" in r.json()["message"], path


def test_full_build_touches_only_the_demo_folder(tmp_path):
    real = [BACKEND / "portfolio.db", BACKEND / "fibonacci_ai.db"]
    before = {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in real if p.exists()}
    out = run_demo("import json; from app.demo import build; print(json.dumps(build.build()))", tmp_path)
    assert out["tracker"]["lots"] > 50 and out["research"]["watchlist"] >= 10
    assert {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in real if p.exists()} == before
    with sqlite3.connect(tmp_path / "portfolio.db") as c:
        assert c.execute("select count(*) from stock_prices").fetchone()[0] > 10_000
        assert c.execute("select count(*) from stock_groups where ticker is not null").fetchone()[0] == 16
    with sqlite3.connect(tmp_path / "fibonacci_ai.db") as c:
        assert c.execute("select count(*) from watchlist_items").fetchone()[0] >= 10
        assert c.execute("select count(*) from listings where namespace = 'real'").fetchone()[0] >= 16
