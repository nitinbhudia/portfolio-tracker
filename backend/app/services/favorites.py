"""Your shortcuts in the left-hand panel: pages of the app you jump to often (kept in the app's database)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models as m

from .portfolio import BadRequest

SETTING = "favorites"
MAX_ITEMS = 50
DEFAULTS = [
    {"href": "/", "label": "Overview"},
    {"href": "/positions", "label": "Positions"},
    {"href": "/performance", "label": "Performance"},
    {"href": "/research/watchlist", "label": "Research watchlist"},
    {"href": "/research/sectors", "label": "Sector rotation"},
    {"href": "/research/scanner", "label": "Scanner"},
]


def get(db: Session) -> dict:
    row = db.get(m.Setting, SETTING)
    if row is None:
        return {"items": DEFAULTS, "is_default": True}
    return {"items": list(row.value.get("items", [])), "is_default": False}


def _clean(item: dict) -> dict:
    href = str(item.get("href") or "").strip()
    label = " ".join(str(item.get("label") or "").split())
    # only pages of this app: a path, never another site
    if not href.startswith("/") or href.startswith("//") or "\\" in href or len(href) > 500:
        raise BadRequest(f"'{href}' isn't a page of this app")
    if not label:
        raise BadRequest("Give the shortcut a name.")
    return {"href": href, "label": label[:60]}


def put(db: Session, items: list[dict]) -> dict:
    if len(items) > MAX_ITEMS:
        raise BadRequest(f"At most {MAX_ITEMS} shortcuts.")
    clean, seen = [], set()
    for it in items:
        c = _clean(it)
        if c["href"] not in seen:
            seen.add(c["href"])
            clean.append(c)
    row = db.get(m.Setting, SETTING)
    if row is None:
        db.add(m.Setting(key=SETTING, value={"items": clean}))
    else:
        row.value = {"items": clean}
    db.commit()
    return get(db)
