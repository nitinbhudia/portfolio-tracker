"""Trade ideas in the journal: stocks you're watching, with price levels that trigger when the price gets near or hits them.

Prices come from Research: adding an idea tracks the stock there (downloads its daily prices), and Research's daily price
refresh keeps it up to date. Levels are checked after every refresh (the automatic one too) and whenever the Ideas tab is
opened. A trigger fires once per level (near, then hit); changing a level's price re-arms it. Unseen triggers show as a
badge on Journal in the menu.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.engine import journal as J

from . import journal as JS
from . import portfolio as P

KINDS = ("entry", "target", "stop", "alert")
SIDES = ("buy", "sell", "watch")
EXCHANGES = ("US", "XETR", "XAMS", "XPAR", "XSWX", "XLON")


def _bars(listing_id: int, since: date) -> tuple[list[tuple[date, float, float, float]], dict | None]:
    from research.db import models as rm
    from research.db.session import SessionLocal
    with SessionLocal() as rdb:
        rows = rdb.execute(select(rm.PriceBar.date, rm.PriceBar.high, rm.PriceBar.low, rm.PriceBar.close)
                           .where(rm.PriceBar.listing_id == listing_id, rm.PriceBar.interval == "1d")
                           .order_by(rm.PriceBar.date)).all()
    bars = [(d, float(h), float(lo), float(c)) for d, h, lo, c in rows]
    last = {"date": bars[-1][0].isoformat(), "close": bars[-1][3]} if bars else None
    return [b for b in bars if b[0] >= since], last


def _track(ticker: str, exchange: str) -> tuple[int | None, str | None]:
    """Make sure Research has the stock and its prices (same as the φ button)."""
    try:
        from research.api import routes as R
        from research.db.session import SessionLocal
        with SessionLocal() as rdb:
            r = R.track(R.TrackIn(ticker=ticker, exchange=exchange), rdb)
        return r["listing_id"], None
    except Exception as e:  # noqa: BLE001  (shown on the idea; the idea is kept)
        return None, (getattr(e, "message", None) or str(e))[:300]


def _clean_levels(levels) -> list[dict]:
    out = []
    for lv in levels or []:
        try:
            price = float(lv.get("price"))
        except (TypeError, ValueError, AttributeError):
            raise P.BadRequest("each level needs a price") from None
        if price <= 0:
            raise P.BadRequest("prices must be above 0")
        kind = lv.get("kind") if lv.get("kind") in KINDS else "alert"
        label = (str(lv.get("label") or "").strip() or f"{kind} {price:g}")[:60]
        out.append({"label": label, "kind": kind, "price": price})
    labels = [x["label"] for x in out]
    if len(set(labels)) != len(labels):
        raise P.BadRequest("two levels have the same name")
    return out[:20]


def _dict(db: Session, i: m.JournalIdea, check: bool = False) -> dict:
    events = list(db.scalars(select(m.JournalIdeaEvent).where(m.JournalIdeaEvent.idea_id == i.id).order_by(m.JournalIdeaEvent.date.desc())))
    last = None
    if i.listing_id:
        try:
            _, last = _bars(i.listing_id, date.today())
        except Exception:  # noqa: BLE001
            last = None
    price = last["close"] if last else None
    return {"id": i.id, "stock": i.stock, "ticker": i.ticker, "exchange": i.exchange, "side": i.side, "near_pct": i.near_pct,
            "levels": J.distances(i.levels or [], price), "reasons": i.reasons or [], "confidence": i.confidence, "notes": i.notes,
            "status": i.status, "listing_id": i.listing_id, "price_error": i.price_error, "bought_key": i.bought_key,
            "created_at": i.created_at.isoformat(), "updated_at": i.updated_at.isoformat() if i.updated_at else None,
            "last": last, "events": [{"id": e.id, "label": e.label, "level": e.level, "kind": e.kind, "date": e.date.isoformat(),
                                      "price": e.price, "seen": e.seen} for e in events]}


def check(db: Session) -> dict:
    """Look for new triggers on every idea that is being watched."""
    new = 0
    for i in db.scalars(select(m.JournalIdea).where(m.JournalIdea.status == "watching")):
        if not i.listing_id:
            continue
        start = i.created_at.date()
        bars, _ = _bars(i.listing_id, date.fromordinal(start.toordinal() - 14))
        bars = [b for b in bars if b[0] < start][-1:] + [b for b in bars if b[0] >= start]
        fired = {(e.label, e.kind) for e in db.scalars(select(m.JournalIdeaEvent).where(m.JournalIdeaEvent.idea_id == i.id))}
        for ev in J.check_levels(i.levels or [], bars, fired, i.near_pct or J.NEAR_PCT, hit_from=start):
            db.add(m.JournalIdeaEvent(idea_id=i.id, **ev))
            new += 1
    db.commit()
    return {"new": new}


def view(db: Session, run_check: bool = True) -> dict:
    if run_check:
        check(db)
    ideas = list(db.scalars(select(m.JournalIdea).order_by(m.JournalIdea.status != "watching", m.JournalIdea.updated_at.desc())))
    return {"ideas": [_dict(db, i) for i in ideas], "unseen": unseen(db), "kinds": list(KINDS), "sides": list(SIDES),
            "exchanges": list(EXCHANGES), "tags": JS.tags(db)}


def unseen(db: Session) -> int:
    return len(list(db.scalars(select(m.JournalIdeaEvent.id).where(m.JournalIdeaEvent.seen.is_(False)))))


def mark_seen(db: Session) -> dict:
    for e in db.scalars(select(m.JournalIdeaEvent).where(m.JournalIdeaEvent.seen.is_(False))):
        e.seen = True
    db.commit()
    return {"unseen": 0}


def _apply(i: m.JournalIdea, d: dict) -> None:
    if "side" in d and d["side"] is not None:
        if d["side"] not in SIDES:
            raise P.BadRequest(f"side must be one of {SIDES}")
        i.side = d["side"]
    if d.get("levels") is not None:
        i.levels = _clean_levels(d["levels"])
    if d.get("near_pct") is not None:
        if not 0.1 <= float(d["near_pct"]) <= 25:
            raise P.BadRequest("'near' must be between 0.1% and 25%")
        i.near_pct = float(d["near_pct"])
    if d.get("reasons") is not None:
        i.reasons = [str(x).strip()[:60] for x in d["reasons"] if str(x).strip()][:10]
    if "confidence" in d:
        c = d["confidence"]
        if c is not None and c not in (1, 2, 3, 4, 5):
            raise P.BadRequest("confidence must be 1 to 5")
        i.confidence = c
    if "notes" in d:
        i.notes = (str(d["notes"] or "").strip()[:10000]) or None
    if d.get("status") is not None:
        if d["status"] not in ("watching", "done", "dropped"):
            raise P.BadRequest("status must be watching, done or dropped")
        i.status = d["status"]
    if d.get("stock"):
        i.stock = str(d["stock"]).strip()[:200]
    i.updated_at = datetime.now(timezone.utc)


def create(db: Session, d: dict) -> dict:
    t = str(d.get("ticker") or "").strip().upper()
    if not t or not all(c.isalnum() or c in ".-" for c in t):
        raise P.BadRequest("a ticker is needed (letters, digits, '.' or '-')")
    ex = str(d.get("exchange") or "US").upper()
    if ex not in EXCHANGES:
        raise P.BadRequest(f"exchange must be one of {', '.join(EXCHANGES)}")
    i = m.JournalIdea(stock=str(d.get("stock") or t).strip()[:200], ticker=t, exchange=ex, levels=[], reasons=[], near_pct=J.NEAR_PCT)
    _apply(i, d)
    i.listing_id, i.price_error = _track(t, ex)
    db.add(i)
    db.commit()
    check(db)
    return _dict(db, i)


def update(db: Session, idea_id: int, d: dict) -> dict:
    i = db.get(m.JournalIdea, idea_id)
    if i is None:
        raise P.NotFound("idea not found")
    before = {lv["label"]: lv["price"] for lv in i.levels or []}
    _apply(i, d)
    after = {lv["label"]: lv["price"] for lv in i.levels or []}
    changed = [k for k in before if after.get(k) != before[k]]
    if changed:  # a moved or removed level starts afresh
        db.execute(delete(m.JournalIdeaEvent).where(m.JournalIdeaEvent.idea_id == i.id, m.JournalIdeaEvent.label.in_(changed)))
    if d.get("retry_prices") and not i.listing_id:
        i.listing_id, i.price_error = _track(i.ticker, i.exchange)
    db.commit()
    check(db)
    return _dict(db, i)


def remove(db: Session, idea_id: int) -> dict:
    db.execute(delete(m.JournalIdeaEvent).where(m.JournalIdeaEvent.idea_id == idea_id))
    db.execute(delete(m.JournalIdea).where(m.JournalIdea.id == idea_id))
    db.commit()
    return view(db, run_check=False)


def candidates(db: Session, idea_id: int) -> list[dict]:
    """Buys that could be this idea being carried out: same ticker (or a name match), on or after the day it was written."""
    i = db.get(m.JournalIdea, idea_id)
    if i is None:
        raise P.NotFound("idea not found")
    rows = JS.view(db)["rows"]
    name = i.stock.lower()
    since = i.created_at.date().isoformat()
    return [r for r in rows if r["kind"] == "buy" and r["date"] >= since and
            ((r.get("ticker") or "").upper() == i.ticker or name in r["stock"].lower() or r["stock"].lower() in name)][:20]


def bought(db: Session, idea_id: int, key: str) -> dict:
    """The idea became this buy: copy its reasons, target, stop and notes into the buy's journal entry, and close the idea."""
    i = db.get(m.JournalIdea, idea_id)
    if i is None:
        raise P.NotFound("idea not found")
    lv = {x["kind"]: x["price"] for x in reversed(i.levels or [])}
    cur = (JS.detail(db, key).get("entry") or {})
    note = f"From idea of {i.created_at.date().isoformat()}." + (f" {i.notes}" if i.notes else "")
    JS.save(db, key, {"reasons": cur.get("reasons") or i.reasons, "target": cur.get("target") or lv.get("target"),
                      "stop": cur.get("stop") or lv.get("stop"), "horizon_days": cur.get("horizon_days"),
                      "confidence": cur.get("confidence") or i.confidence,
                      "notes": (cur.get("notes") + "\n" + note) if cur.get("notes") else note})
    i.status, i.bought_key = "done", key
    db.commit()
    return _dict(db, i)
