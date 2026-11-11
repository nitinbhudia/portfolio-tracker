"""Phase 3: what you enter in the app — trades, fees, corrections to imported trades, dividends, prices."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.engine import rebuild as R
from app.importer import live_portfolio as L

from . import portfolio as P
from .portfolio import BadRequest, NotFound


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _date(v, field="date") -> date:
    try:
        d = date.fromisoformat(str(v))
    except (TypeError, ValueError) as e:
        raise BadRequest(f"{field} must be a date (YYYY-MM-DD)") from e
    if d > _today():
        raise BadRequest(f"{field} can't be in the future")
    return d


def _num(v, field: str, positive=False, allow_zero=True) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError) as e:
        raise BadRequest(f"{field} must be a number") from e
    if x < 0 or (positive and x == 0) or (not allow_zero and x == 0):
        raise BadRequest(f"{field} must be {'more than 0' if positive else '0 or more'}")
    return x


def _cur(v) -> str:
    c = str(v or "").strip().upper()
    if c not in R.KNOWN_CURRENCIES:
        raise BadRequest(f"currency must be one of {sorted(R.KNOWN_CURRENCIES)}")
    return c


def _ensure_rate(db: Session, cur: str, when: date):
    if cur != "USD" and not P.st_rates_cover(db, cur, when):
        P.ensure_fx_for(db, [cur], when)


# ---------------------------------------------------------------- trades

def trades(db: Session) -> dict:
    st = P._need(db)
    fees = {f.trade_id: f.amount for f in db.scalars(select(m.TradeFee))}
    sale_by_id = {s.id: s for s in st["sales"]}
    out = []
    for t in st["rb"].trades:
        s = sale_by_id.get(t.id)
        row = {"id": t.id, "kind": t.kind, "date": t.date.isoformat(), "stock": t.stock, "stock_key": t.stock_key, "pool": t.pool,
               "shares": t.shares, "price": t.price, "currency": t.currency, "pence": t.scale == 0.01, "broker": t.broker,
               "fee": t.fee, "source": t.source, "row": t.row or None, "sale_row": t.sale_row, "note": t.note,
               "gain_usd": s.gain_usd if s else None, "editable": t.source == "app",
               "correctable": t.source == "sheet" and t.id[0] in "BS", "fee_stored": fees.get(t.id)}
        out.append(row)
    out.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    names = sorted({t.stock for t in st["rb"].trades})
    return {"trades": out, "stocks": names, "stale_fees": st["stale_fees"],
            "currencies": sorted(R.KNOWN_CURRENCIES), "as_of": P.as_of(st).isoformat()}


def _trade_in(d: dict) -> dict:
    kind = d.get("kind")
    if kind not in ("buy", "sell"):
        raise BadRequest("kind must be buy or sell")
    name = str(d.get("name") or "").strip()
    if not name:
        raise BadRequest("stock name is required")
    cur = _cur(d.get("currency"))
    return {"kind": kind, "date": _date(d.get("date")), "name": name, "shares": _num(d.get("shares"), "shares", positive=True),
            "price": _num(d.get("price"), "price"), "currency": cur, "pence": bool(d.get("pence")) and cur == "GBP",
            "broker": (str(d.get("broker") or "").strip() or None), "fee": _num(d.get("fee") or 0, "fee"),
            "note": (str(d.get("note") or "").strip() or None)}


def add_trade(db: Session, d: dict) -> dict:
    P._need(db)
    v = _trade_in(d)
    db.add(m.ManualTrade(**v))
    db.commit()
    _ensure_rate(db, v["currency"], v["date"])
    P._invalidate()
    return trades(db)


def update_trade(db: Session, trade_id: int, d: dict) -> dict:
    t = db.get(m.ManualTrade, trade_id)
    if t is None:
        raise NotFound(f"trade M{trade_id} not found")
    for k, v in _trade_in(d).items():
        setattr(t, k, v)
    db.commit()
    _ensure_rate(db, t.currency, t.date)
    P._invalidate()
    return trades(db)


def delete_trade(db: Session, trade_id: int) -> dict:
    t = db.get(m.ManualTrade, trade_id)
    if t is None:
        raise NotFound(f"trade M{trade_id} not found")
    db.delete(t)
    db.commit()
    P._invalidate()
    return trades(db)


def set_fee(db: Session, trade_id: str, amount) -> dict:
    """Fee on a trade from the sheet (B12, S40, A40, L7), in the trade's currency."""
    st = P._need(db)
    if not trade_id or trade_id[0] not in "BSAL" or not trade_id[1:].isdigit():
        raise BadRequest("fees on app-entered trades are set when editing the trade")
    fp = st["fingerprints"].get(f"P{trade_id[1:]}")
    if fp is None or trade_id not in {t.id for t in st["rb"].trades}:
        raise NotFound(f"no trade {trade_id}")
    a = _num(amount, "fee")
    row = db.get(m.TradeFee, trade_id)
    if a == 0:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(m.TradeFee(trade_id=trade_id, fingerprint=fp, amount=a))
    else:
        row.amount, row.fingerprint = a, fp
    db.commit()
    P._invalidate()
    return trades(db)


CORRECTABLE = {"date": "date", "sale_date": "date", "shares": "num+", "price": "num", "live_price": "num", "currency": "cur",
               "name": "text"}  # name: e.g. a row written as "Lumentum" that was really another stock


def correct(db: Session, trade_id: str, fields: dict) -> dict:
    """Correct a trade from the sheet. Stored like a review decision (on the row, with its fingerprint), so it is
    kept across re-imports of the same row and dropped (and reported) if the row changes in the sheet."""
    st = P._need(db)
    if not trade_id or trade_id[0] not in "BS" or not trade_id[1:].isdigit():
        raise NotFound(f"no trade {trade_id} from the sheet")
    key = f"P{trade_id[1:]}"
    if trade_id not in {t.id for t in st["rb"].trades}:
        # a row waiting in Review (e.g. a sale whose purchase was renamed) can still get its name corrected
        if not (set(fields or {}) == {"name"} and key in st["fingerprints"]):
            raise NotFound(f"no trade {trade_id} from the sheet")
    clean = {}
    for k, v in (fields or {}).items():
        if k not in CORRECTABLE:
            raise BadRequest(f"can't change {k}")
        kind = CORRECTABLE[k]
        if kind == "text":
            name = str(v or "").strip()
            if not name or len(name) > 200:
                raise BadRequest("the stock name must be 1 to 200 characters")
            clean[k] = name
            continue
        clean[k] = (_date(v, k).isoformat() if kind == "date" else _cur(v) if kind == "cur"
                    else _num(v, k, positive=kind == "num+"))
    if "sale_date" in clean and trade_id[0] != "S":
        raise BadRequest("sale_date only applies to sales")
    row = db.get(m.Decision, key)
    if row is None:
        db.add(m.Decision(key=key, fingerprint=st["fingerprints"][key], decision={"action": "edit", "fields": clean}))
    else:
        dec = dict(row.decision)
        dec["fields"] = {**(dec.get("fields") or {}), **clean}
        row.decision, row.fingerprint = dec, st["fingerprints"][key]
    db.commit()
    P._invalidate()
    return trades(db)


# ---------------------------------------------------------------- dividends

def dividend_list(db: Session, st=None) -> tuple[list[dict], list[tuple[date, float, str]], list[str]]:
    st = st or P.state(db)
    rt = st["rates"] if st else P.rates(db)
    groups = st["groups"] if st else {}
    rows, flows, problems = [], [], []
    for dv in db.scalars(select(m.Dividend).order_by(m.Dividend.date.desc(), m.Dividend.id.desc())):
        r = rt.usd(dv.currency, dv.date)
        usd = dv.amount * r.rate if r else None
        k = R.name_key(dv.name)
        key = groups.get(k, k)
        if usd is None:
            problems.append(f"No ECB rate for {dv.currency} on {dv.date}: that dividend is left out.")
        else:
            flows.append((dv.date, usd, key))
        rows.append({"id": dv.id, "date": dv.date.isoformat(), "name": dv.name, "stock_key": key, "amount": dv.amount, "tax": dv.tax,
                     "currency": dv.currency, "usd": usd, "note": dv.note})
    return rows, flows, problems


def dividends(db: Session) -> dict:
    rows, flows, problems = dividend_list(db)
    by_year: dict[int, float] = {}
    by_stock: dict[str, float] = {}
    for r in rows:
        if r["usd"] is not None:
            by_year[int(r["date"][:4])] = by_year.get(int(r["date"][:4]), 0.0) + r["usd"]
            by_stock[r["name"]] = by_stock.get(r["name"], 0.0) + r["usd"]
    return {"dividends": rows, "problems": problems, "total_usd": sum(v for _, v, _ in flows),
            "by_year": [{"year": y, "usd": v} for y, v in sorted(by_year.items())],
            "by_stock": [{"name": k, "usd": v} for k, v in sorted(by_stock.items(), key=lambda x: -x[1])]}


def add_dividend(db: Session, d: dict) -> dict:
    name = str(d.get("name") or "").strip()
    if not name:
        raise BadRequest("stock name is required")
    v = {"date": _date(d.get("date")), "name": name, "amount": _num(d.get("amount"), "amount", positive=True),
         "tax": _num(d.get("tax") or 0, "tax"), "currency": _cur(d.get("currency")), "note": (str(d.get("note") or "").strip() or None)}
    db.add(m.Dividend(**v))
    db.commit()
    _ensure_rate(db, v["currency"], v["date"])
    P._invalidate()
    return dividends(db)


def delete_dividend(db: Session, div_id: int) -> dict:
    dv = db.get(m.Dividend, div_id)
    if dv is None:
        raise NotFound(f"dividend {div_id} not found")
    db.delete(dv)
    db.commit()
    P._invalidate()
    return dividends(db)


# ---------------------------------------------------------------- prices

def prices(db: Session) -> dict:
    pos = P.positions(db)
    hist = {}
    for pr in db.scalars(select(m.Price).order_by(m.Price.date.desc(), m.Price.id.desc())):
        hist.setdefault(pr.pool, []).append({"id": pr.id, "price": pr.price, "date": pr.date.isoformat(), "source": pr.source})
    rows = [{"pool": p["pool"], "stock": p["stock"], "currency": p["currency"], "pence": p["pence"], "shares": p["shares"],
             "price": p["price"], "price_date": p["price_date"], "price_source": p["price_source"], "value_usd": p["value_usd"],
             "history": hist.get(p["pool"], [])[:5]} for p in pos["positions"]]
    return {"prices": sorted(rows, key=lambda r: r["stock"].lower()), "sheet_as_of": pos["sheet_as_of"], "as_of": pos["as_of"]}


def set_price(db: Session, pool: str, d: dict) -> dict:
    pools = {p["pool"] for p in P.positions(db)["positions"]}
    if pool not in pools:
        raise NotFound("no open position for that stock")
    pd = _date(d.get("date") or _today().isoformat())
    db.add(m.Price(pool=pool, price=_num(d.get("price"), "price", positive=True), date=pd, source="typed in the app"))
    db.commit()
    _ensure_rate(db, pool.rsplit("|", 1)[1], pd)
    P._invalidate()
    return prices(db)


def delete_price(db: Session, price_id: int) -> dict:
    pr = db.get(m.Price, price_id)
    if pr is None:
        raise NotFound(f"price {price_id} not found")
    db.delete(pr)
    db.commit()
    P._invalidate()
    return prices(db)


def prices_from_workbook(db: Session, filename: str, data: bytes) -> dict:
    """Read only the Live Price of the open rows from an updated workbook; trades and review decisions are untouched."""
    st = P._need(db)
    try:
        wb = L.read(data)
    except L.ImportError_ as e:
        raise BadRequest(str(e)) from e
    when = datetime.fromisoformat(wb.saved_at).date() if wb.saved_at else _today()
    groups = st["groups"]
    held = {p["pool"] for p in P.positions(db)["positions"]}
    latest: dict[str, tuple[int, float, str]] = {}
    for p in wb.positions:
        if p.status != "open" or p.live_price is None or p.currency not in R.KNOWN_CURRENCIES:
            continue
        k = R.name_key(p.name)
        pool = f"{groups.get(k, k)}|{p.currency}"
        if pool not in latest or p.row > latest[pool][0]:
            latest[pool] = (p.row, p.live_price, p.name)
    updated, not_held = 0, []
    for pool, (row, price, name) in latest.items():
        if pool in held:
            db.add(m.Price(pool=pool, price=price, date=when, source=f"{filename} (row {row})"))
            updated += 1
        else:
            not_held.append(f"{name} ({pool.rsplit('|', 1)[1]})")
    db.commit()
    for c in {pl.rsplit("|", 1)[1] for pl in latest}:
        _ensure_rate(db, c, when)
    P._invalidate()
    missing = sorted(held - set(latest))
    return {**prices(db), "updated": updated, "workbook_saved": when.isoformat(),
            "not_held": sorted(not_held), "no_price_in_workbook": missing}
