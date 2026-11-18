"""Backups (create, list, prune, restore) and updates (check, safe apply, removed files, restart) in a temporary folder."""
import io
import json
import sqlite3
import zipfile

import httpx
import pytest

from app.services import maintenance as MT


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(MT, "ROOT", tmp_path)
    dbs = {"portfolio.db": tmp_path / "backend" / "portfolio.db", "fibonacci_ai.db": tmp_path / "backend" / "fibonacci_ai.db"}
    (tmp_path / "backend").mkdir()
    for name, p in dbs.items():
        with sqlite3.connect(p) as c:
            c.execute("create table t (v text)")
            c.execute("insert into t values (?)", (f"{name} v1",))
    monkeypatch.setattr(MT, "databases", lambda: dbs)
    return tmp_path, dbs


def value(p):
    with sqlite3.connect(p) as c:
        return c.execute("select v from t").fetchone()[0]


def set_value(p, v):
    with sqlite3.connect(p) as c:
        c.execute("update t set v = ?", (v,))


def test_backup_restore_prune(root, monkeypatch):
    tmp, dbs = root
    b = MT.backup("manual")
    assert set(b["files"]) == {"portfolio.db", "fibonacci_ai.db"} and MT.list_backups()[0]["id"] == b["id"]
    set_value(dbs["portfolio.db"], "changed")
    restarts = []
    r = MT.restore(b["id"], restart=lambda why: restarts.append(why) or True)
    assert value(dbs["portfolio.db"]) == "portfolio.db v1" and r["restarting"] and restarts == ["restore"]
    safety = next(x for x in MT.list_backups() if x["id"] == r["safety_backup"])  # the state before restoring is kept
    assert safety["reason"] == "before-restore" and value(tmp / "backups" / safety["id"] / "portfolio.db") == "changed"
    with pytest.raises(MT.NotFound):
        MT.restore("../../etc")
    monkeypatch.setitem(MT.KEEP, "manual", 2)
    times = iter(range(100))
    monkeypatch.setattr(MT, "_now", lambda: MT.datetime(2026, 11, 18, 9, 0, next(times), tzinfo=MT.timezone.utc))
    for _ in range(3):
        MT.backup("manual")
    assert len([x for x in MT.list_backups() if x["reason"] == "manual"]) == 2
    assert zipfile.ZipFile(io.BytesIO(MT.backup_zip(MT.list_backups()[0]["id"]))).namelist()
    assert MT.daily_backup_if_due()["reason"] == "daily" and MT.daily_backup_if_due() is None  # once a day


def make_zip(files: dict[str, str], top="portfolio-tracker-abc123") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for rel, text in files.items():
            z.writestr(f"{top}/{rel}", text)
    return buf.getvalue()


BASE = {"scripts/dev.sh": "#!/bin/bash\necho v2\n", "backend/app/main.py": "# v2\n", "frontend/package.json": "{}",
        "backend/requirements.txt": "fastapi\n", "README.md": "v2\n"}


def fake_github(zip_bytes: bytes, sha="abc123"):
    def handle(req: httpx.Request):
        if req.url.host == "api.github.com":
            return httpx.Response(200, json=[{"sha": sha, "commit": {"committer": {"date": "2026-11-18T10:00:00Z"},
                                                                     "message": "Merge pull request #23\n\nUpdates"}},
                                             {"sha": "old111", "commit": {"committer": {"date": "2026-11-17T10:00:00Z"},
                                                                          "message": "Add the buy-zone planner"}}])
        assert req.url.host == "codeload.github.com" and req.url.path.endswith(sha)
        return httpx.Response(200, content=zip_bytes)
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_update_keeps_data_and_removes_old_files(root):
    tmp, dbs = root
    (tmp / ".env").write_text("TIINGO_API_KEY=secret\n")
    (tmp / "README.md").write_text("v1\n")
    (tmp / "old_module.py").write_text("x")
    (tmp / ".installed-files.json").write_text(json.dumps(["README.md", "old_module.py", "scripts/dev.sh"]))
    evil = make_zip({**BASE, ".env": "TIINGO_API_KEY=overwritten\n", "backend/portfolio.db": "not a db"})
    client = fake_github(evil)
    c = MT.check(client)
    assert c["update_available"] and c["current"]["sha"] is None and c["whats_new"] == ["Add the buy-zone planner"]
    restarts = []
    r = MT.update(client, restart=lambda why: restarts.append(why) or True)
    assert r["status"] == "updated" and r["restarting"] and restarts == ["update"]
    assert (tmp / "README.md").read_text() == "v2\n" and (tmp / "scripts/dev.sh").read_text().endswith("echo v2\n")
    assert (tmp / ".env").read_text() == "TIINGO_API_KEY=secret\n" and value(dbs["portfolio.db"]) == "portfolio.db v1"  # untouched
    assert not (tmp / "old_module.py").exists() and r["removed"] == ["old_module.py"]
    assert json.loads((tmp / "version.json").read_text())["sha"] == "abc123"
    assert r["deps_changed"] == ["backend/requirements.txt"]  # new requirements -> packages re-installed on restart
    assert any(b["reason"] == "before-update" for b in MT.list_backups())
    assert MT.check(client)["update_available"] is False and MT.update(client)["status"] == "up_to_date"


def test_update_rejects_bad_downloads(root):
    tmp, _ = root
    for bad, msg in [(b"not a zip", "valid ZIP"), (make_zip({"README.md": "x"}), "missing"),
                     (make_zip({**BASE, "../escape.txt": "x"}), "Unsafe")]:
        with pytest.raises(MT.BadRequest, match=msg):
            MT.apply_zip(bad, "s", None)
    assert not (tmp.parent / "escape.txt").exists() and not (tmp / "version.json").exists()


def test_restart_only_when_supervised(root, monkeypatch):
    tmp, _ = root
    monkeypatch.delenv("PT_SUPERVISED", raising=False)
    assert MT.request_restart("update") is False and not (tmp / ".restart-requested").exists()
