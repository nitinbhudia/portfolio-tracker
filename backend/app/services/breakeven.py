"""Break-even calculator: your own lists of buys (any stock, held or not), saved in the app's database.
The maths runs in the page (frontend/lib/breakeven.ts); this only keeps what you typed."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models as m

from .portfolio import BadRequest

KEY = "breakeven_calcs"
MAX_CALCS, MAX_LOTS, MAX_STEPS = 50, 50, 20


def _num(v, field: str, positive: bool = False, allow_none: bool = True) -> float | None:
    if v in (None, ""):
        if allow_none:
            return None
        raise BadRequest(f"{field} is needed")
    try:
        x = float(v)
    except (TypeError, ValueError) as e:
        raise BadRequest(f"{field} must be a number") from e
    if x != x or x < 0 or (positive and x == 0) or x > 1e12:
        raise BadRequest(f"{field} must be {'above' if positive else 'at least'} 0")
    return x


def _clean(c: dict, i: int) -> dict:
    if not isinstance(c, dict):
        raise BadRequest("each calculation must be an object")
    lots = c.get("lots") or []
    if not isinstance(lots, list) or len(lots) > MAX_LOTS:
        raise BadRequest(f"at most {MAX_LOTS} buys per stock")
    steps = [int(_num(x, "additional shares", positive=True)) for x in (c.get("steps") or [])][:MAX_STEPS]
    return {
        "id": str(c.get("id") or f"c{i}")[:40],
        "name": str(c.get("name") or "").strip()[:80],
        "currency": str(c.get("currency") or "USD").strip().upper()[:5],
        "lots": [{"shares": _num(lot.get("shares"), "shares"), "price": _num(lot.get("price"), "price"), "fee": _num(lot.get("fee"), "fee"),
                  "date": str(lot.get("date") or "")[:10] or None} for lot in lots if isinstance(lot, dict)],
        "price": _num(c.get("price"), "current price"),
        "buy_price": _num(c.get("buy_price"), "buy price"),
        "buy_fee": _num(c.get("buy_fee"), "fee"),
        "steps": steps,
        "target": _num(c.get("target"), "target average"),
        "budget": _num(c.get("budget"), "budget"),
        "pool": (str(c["pool"])[:240] if c.get("pool") else None),
        "notes": str(c.get("notes") or "")[:2000] or None,
    }


def get(db: Session) -> dict:
    row = db.get(m.Setting, KEY)
    return {"calcs": (row.value or {}).get("calcs", []) if row else []}


def put(db: Session, calcs: list) -> dict:
    if not isinstance(calcs, list) or len(calcs) > MAX_CALCS:
        raise BadRequest(f"at most {MAX_CALCS} stocks")
    value = {"calcs": [_clean(c, i) for i, c in enumerate(calcs)]}
    row = db.get(m.Setting, KEY)
    if row is None:
        db.add(m.Setting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()
    return value
