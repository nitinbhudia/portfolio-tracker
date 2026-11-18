"""Backups of your databases, and one-click updates of the app from GitHub.

Backups: a copy of both databases (Portfolio Tracker's `portfolio.db` and Research's `fibonacci_ai.db`) in `backups/`
in the app's folder, made with SQLite's own backup method, so it is consistent even while the app runs. One a day
automatically, one before every update or restore, and whenever you press Back up now. Restoring copies a backup back
into the live databases (after backing up the current state) and restarts the app.

Updates: compare this copy's version with the newest on GitHub (main branch), download that version's ZIP, check it,
back up, and copy the new files over this folder. Never touched: your data and keys (`*.db`, `.env`, `backups/`), the
installed packages (`.venv/`, `node_modules/`) and build caches. Files removed upstream are removed too, but only files
a previous update installed. The app then restarts itself (scripts/dev.sh watches for the restart request).
"""
from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.db import models as m
from app.engine.fx import USER_AGENT

from .portfolio import BadRequest, NotFound

REPO = "nitinbhudia/portfolio-tracker"
BRANCH = "main"
ROOT = m.BACKEND_DIR.parent  # the app's folder
MAX_ZIP = 60 * 1024 * 1024
KEEP = {"daily": 14, "manual": 20, "before-update": 5, "before-restore": 5}
# Never written or deleted by an update (relative paths, fnmatch patterns).
PROTECTED = [".env", "*.db", "*.db-journal", "*.db-wal", "*.db-shm", "*.sqlite", "backups/*", ".venv/*", "*/node_modules/*",
             "node_modules/*", "*/.next/*", "*/.next-prod/*", ".git/*", ".run/*", "uploads/*", "version.json", ".installed-files.json",
             ".restart-requested"]
REQUIRED = ["scripts/dev.sh", "backend/app/main.py", "frontend/package.json", "backend/requirements.txt"]

_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- databases


def databases() -> dict[str, Path]:
    """name -> live SQLite file of each database the app uses."""
    from research.core.config import settings as research_settings
    out = {}
    for name, url in (("portfolio.db", m.DATABASE_URL), ("fibonacci_ai.db", research_settings.database_url)):
        if url.startswith("sqlite:///"):
            out[name] = Path(url[len("sqlite:///"):])
    return out


def _copy_db(src: Path, dst: Path) -> None:
    """Consistent copy of a live SQLite database (SQLite's online backup)."""
    with sqlite3.connect(str(src)) as s, sqlite3.connect(str(dst)) as d:
        s.backup(d)


# ---------------------------------------------------------------- backups


def backups_dir() -> Path:
    return ROOT / "backups"


def backup(reason: str = "manual") -> dict:
    if reason not in KEEP:
        raise BadRequest(f"reason must be one of {list(KEEP)}")
    with _lock:
        stamp = _now().strftime("%Y-%m-%d_%H%M%S")
        folder = backups_dir() / f"{stamp}_{reason}"
        folder.mkdir(parents=True, exist_ok=False)
        files = {}
        for name, path in databases().items():
            if path.exists():
                _copy_db(path, folder / name)
                files[name] = (folder / name).stat().st_size
        meta = {"id": folder.name, "reason": reason, "at": _now().isoformat(), "files": files, "version": current_version().get("sha")}
        (folder / "backup.json").write_text(json.dumps(meta, indent=1))
        _prune()
        return meta


def list_backups() -> list[dict]:
    out = []
    d = backups_dir()
    if not d.exists():
        return out
    for f in sorted(d.iterdir(), reverse=True):
        meta = f / "backup.json"
        if f.is_dir() and meta.exists():
            try:
                out.append(json.loads(meta.read_text()))
            except ValueError:
                continue
    return out


def _prune() -> None:
    by_reason: dict[str, list[dict]] = {}
    for b in list_backups():
        by_reason.setdefault(b["reason"], []).append(b)
    for reason, items in by_reason.items():
        for b in items[KEEP.get(reason, 10):]:
            shutil.rmtree(backups_dir() / b["id"], ignore_errors=True)


def _folder(backup_id: str) -> Path:
    f = (backups_dir() / backup_id).resolve()
    if f.parent != backups_dir().resolve() or not (f / "backup.json").exists():
        raise NotFound(f"no backup {backup_id}")
    return f


def delete_backup(backup_id: str) -> list[dict]:
    shutil.rmtree(_folder(backup_id))
    return list_backups()


def backup_zip(backup_id: str) -> bytes:
    f = _folder(backup_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in f.iterdir():
            z.write(p, f"{backup_id}/{p.name}")
    return buf.getvalue()


def restore(backup_id: str, restart=None) -> dict:
    """Back up the current state, copy the backup into the live databases, then restart the app."""
    f = _folder(backup_id)
    safety = backup("before-restore")
    restored = []
    with _lock:
        for name, live in databases().items():
            src = f / name
            if src.exists():
                _copy_db(src, live)
                restored.append(name)
    from . import history as HS
    from . import portfolio as P
    P._invalidate()
    HS._invalidate()
    restarting = (restart or request_restart)("restore")
    return {"restored": restored, "safety_backup": safety["id"], "restarting": bool(restarting)}


def daily_backup_if_due() -> dict | None:
    today = _now().strftime("%Y-%m-%d")
    if any(b["id"].startswith(today) and b["reason"] == "daily" for b in list_backups()):
        return None
    if not any(p.exists() for p in databases().values()):
        return None
    return backup("daily")


def start_daily_backups(interval_s: int = 3 * 3600) -> None:
    def loop():
        while True:
            try:
                daily_backup_if_due()
            except Exception:  # noqa: BLE001  (a failed backup must never stop the app; it is retried later)
                pass
            time.sleep(interval_s)
    threading.Thread(target=loop, name="daily-backup", daemon=True).start()


# ---------------------------------------------------------------- versions and updates


def current_version() -> dict:
    f = ROOT / "version.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    return {"sha": None, "date": None, "note": "Installed by hand (version not recorded yet): the first update records it."}


def _http() -> httpx.Client:
    return httpx.Client(timeout=60.0, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})


def fetch_latest(client: httpx.Client | None = None) -> dict:
    http = client or _http()
    try:
        r = http.get(f"https://api.github.com/repos/{REPO}/commits", params={"sha": BRANCH, "per_page": 30})
    except httpx.HTTPError as e:
        raise BadRequest(f"Couldn't reach GitHub ({type(e).__name__}). Check your internet connection.") from e
    if r.status_code != 200:
        raise BadRequest(f"GitHub answered {r.status_code}; try again later.")
    commits = r.json()
    if not commits:
        raise BadRequest("GitHub returned no versions.")
    return {"sha": commits[0]["sha"], "date": commits[0]["commit"]["committer"]["date"],
            "commits": [{"sha": c["sha"], "date": c["commit"]["committer"]["date"], "title": c["commit"]["message"].splitlines()[0]}
                        for c in commits]}


def check(client: httpx.Client | None = None) -> dict:
    cur = current_version()
    latest = fetch_latest(client)
    shas = [c["sha"] for c in latest["commits"]]
    if cur.get("sha") and cur["sha"] in shas:
        new = latest["commits"][:shas.index(cur["sha"])]
    else:
        new = latest["commits"][:10]
    # merge commits of pull requests carry the feature names; the PR's own title is on the second line
    whats_new = [c["title"] for c in new if not c["title"].startswith("Merge pull request")] or [c["title"] for c in new]
    return {"current": cur, "latest": {"sha": latest["sha"], "date": latest["date"]},
            "update_available": cur.get("sha") != latest["sha"], "whats_new": whats_new[:12]}


def _protected(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch("/" + rel, "*/" + p) for p in PROTECTED)


def _hash(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def download(sha: str, client: httpx.Client | None = None) -> bytes:
    http = client or _http()
    try:
        r = http.get(f"https://codeload.github.com/{REPO}/zip/{sha}")
    except httpx.HTTPError as e:
        raise BadRequest(f"Couldn't download the update ({type(e).__name__}).") from e
    if r.status_code != 200 or len(r.content) > MAX_ZIP:
        raise BadRequest(f"The update download failed (HTTP {r.status_code}).")
    return r.content


def apply_zip(data: bytes, sha: str, date: str | None) -> dict:
    """Install a GitHub ZIP of the app into ROOT, keeping data, keys and installed packages."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise BadRequest("The download isn't a valid ZIP file.") from e
    names = [n for n in z.namelist() if not n.endswith("/")]
    tops = {n.split("/", 1)[0] for n in z.namelist()}
    if len(tops) != 1:
        raise BadRequest("Unexpected update file layout.")
    top = tops.pop() + "/"
    files: dict[str, zipfile.ZipInfo] = {}
    for info in z.infolist():
        if info.is_dir():
            continue
        rel = info.filename[len(top):]
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise BadRequest(f"Unsafe path in the update: {info.filename}")
        files[rel] = info
    missing = [r for r in REQUIRED if r not in files]
    if missing:
        raise BadRequest(f"The update is missing {', '.join(missing)}; not installed.")
    del names

    deps_before = {k: _hash(ROOT / k) for k in ("backend/requirements.txt", "frontend/package-lock.json")}
    written, skipped = 0, []
    for rel, info in files.items():
        if _protected(rel):
            skipped.append(rel)
            continue
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".upd-")
        with os.fdopen(fd, "wb") as out, z.open(info) as src:
            shutil.copyfileobj(src, out)
        mode = (info.external_attr >> 16) & 0o777
        os.chmod(tmp, mode if mode else 0o644)
        os.replace(tmp, dest)  # a new file, so a running script keeps reading its old copy
        written += 1
    # files a previous update installed that this version no longer has
    manifest = ROOT / ".installed-files.json"
    removed = []
    if manifest.exists():
        try:
            old = set(json.loads(manifest.read_text()))
        except ValueError:
            old = set()
        for rel in sorted(old - set(files)):
            p = ROOT / rel
            if not _protected(rel) and p.is_file():
                p.unlink()
                removed.append(rel)
    manifest.write_text(json.dumps(sorted(r for r in files if not _protected(r))))
    (ROOT / "version.json").write_text(json.dumps({"sha": sha, "date": date, "installed_at": _now().isoformat()}))
    deps_changed = [k for k, h in deps_before.items() if h != _hash(ROOT / k)]
    return {"written": written, "removed": removed, "skipped_protected": len(skipped), "deps_changed": deps_changed}


def request_restart(reason: str, exit_after_s: float = 1.5) -> bool:
    """Ask scripts/dev.sh to restart the app: write the marker, then end this backend process shortly after the reply.
    Returns False (and does nothing) when the app wasn't started by a starter that can restart it."""
    if not supervised():
        return False
    (ROOT / ".restart-requested").write_text(json.dumps({"reason": reason, "at": _now().isoformat()}))
    threading.Timer(exit_after_s, lambda: os._exit(3)).start()
    return True


def update(client: httpx.Client | None = None, restart=None) -> dict:
    latest = fetch_latest(client)
    cur = current_version()
    if cur.get("sha") == latest["sha"]:
        return {"status": "up_to_date", "version": cur}
    safety = backup("before-update")
    data = download(latest["sha"], client)
    res = apply_zip(data, latest["sha"], latest["date"])
    restarting = (restart or request_restart)("update")
    return {"status": "updated", "safety_backup": safety["id"], "version": {"sha": latest["sha"], "date": latest["date"]},
            **res, "restarting": bool(restarting)}


def supervised() -> bool:
    """True when started by scripts/dev.sh with automatic restart (older starters can't restart by themselves)."""
    return os.environ.get("PT_SUPERVISED") == "1"
