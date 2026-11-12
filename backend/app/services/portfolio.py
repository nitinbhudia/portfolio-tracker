"""Glue between storage and the engine: import, review decisions, stock groups, FX, and computed results."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.engine import analytics as AN
from app.engine import check as C
from app.engine import fifo as FIFO
from app.engine import fx as FX
from app.engine import names as N
from app.engine import rebuild as R
from app.importer import live_portfolio as L

FX_FETCH = FX.fetch  # replaced in tests
_cache: dict = {}


class BadRequest(ValueError):
    pass


class NotFound(LookupError):
    pass


def _invalidate():
    _cache.clear()


def _jsonable(x):
    return L._jsonable(x)


# ---------------------------------------------------------------- fingerprints

def _fp(obj) -> str:
    return hashlib.sha256(json.dumps(_jsonable(obj), sort_keys=True, default=str).encode()).hexdigest()


def fingerprints(wb: L.Workbook) -> dict[str, str]:
    out = {}
    for p in wb.positions:
        out[f"P{p.row}"] = _fp([p.date, p.name, p.shares, p.price, p.live_price, p.status, p.currency, p.broker])
    for s in wb.sales:
        out[f"S{s.row}"] = _fp([s.date, s.stock, s.pl, s.pl_formula])
    return out


# ---------------------------------------------------------------- import

def active_import(db: Session) -> m.Import | None:
    return db.scalar(select(m.Import).where(m.Import.active.is_(True)).order_by(m.Import.id.desc()).limit(1))


def do_import(db: Session, filename: str, data: bytes) -> dict:
    if not data:
        raise BadRequest("The file is empty.")
    try:
        wb = L.read(data)
    except L.ImportError_ as e:
        raise BadRequest(str(e)) from e
    if not wb.positions:
        raise BadRequest("No position rows found in the Live Portfolio tab (rows with a buy date and status Open/Closed).")
    for old in db.scalars(select(m.Import).where(m.Import.active.is_(True))):
        old.active = False
    db.add(m.Import(filename=filename, sha256=wb.sha256, data=wb.to_dict(), active=True))
    db.commit()
    _invalidate()
    fx_status = ensure_fx(db)
    return {**status(db), "fx": fx_status}


# ---------------------------------------------------------------- FX

def rates(db: Session) -> FX.Rates:
    per: dict[str, list] = defaultdict(list)
    for r in db.scalars(select(m.FxRate)):
        per[r.currency].append((r.date, r.per_eur))
    return FX.Rates(per)


def ensure_fx(db: Session, force: bool = False) -> dict:
    imp = active_import(db)
    if imp is None:
        return {"status": "no_import"}
    wb = L.from_dict(imp.data)
    curs = sorted({p.currency for p in wb.positions if p.currency in R.KNOWN_CURRENCIES} - {"USD"})
    dates = [p.date for p in wb.positions if p.date] + [s.date for s in wb.sales]
    if not curs or not dates:
        return {"status": "not_needed"}
    start = min(dates) - timedelta(days=10)
    have = {c: db.scalar(select(m.FxRate.date).where(m.FxRate.currency == c).order_by(m.FxRate.date.desc()).limit(1))
            for c in ["USD", *curs] if c != "EUR"}
    firsts = {c: db.scalar(select(m.FxRate.date).where(m.FxRate.currency == c).order_by(m.FxRate.date).limit(1))
              for c in have}
    today = datetime.now(timezone.utc).date()
    stale = force or any(v is None or v < today - timedelta(days=3) for v in have.values()) or \
        any(f is None or f > start for f in firsts.values())
    if not stale:
        return {"status": "up_to_date", "latest": max(have.values()).isoformat()}
    try:
        rows = FX_FETCH(curs, start)
    except FX.FxError as e:
        _set(db, "fx_last", {"status": "error", "message": str(e), "at": datetime.now(timezone.utc).isoformat()})
        return {"status": "error", "message": str(e)}
    existing = {(r.date, r.currency) for r in db.scalars(select(m.FxRate))}
    for d, c, v in rows:
        if (d, c) not in existing:
            db.add(m.FxRate(date=d, currency=c, per_eur=v))
    db.commit()
    _invalidate()
    out = {"status": "updated", "rows": len(rows), "currencies": ["USD", *curs],
           "latest": max((d for d, _, _ in rows), default=None), "at": datetime.now(timezone.utc).isoformat()}
    _set(db, "fx_last", _jsonable(out))
    return _jsonable(out)


def _set(db: Session, key: str, value: dict):
    row = db.get(m.Setting, key)
    if row is None:
        db.add(m.Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def _get(db: Session, key: str) -> dict | None:
    row = db.get(m.Setting, key)
    return row.value if row else None


# ---------------------------------------------------------------- computed state

def _groups(db: Session) -> tuple[dict[str, str], dict[str, str], dict[str, str | None]]:
    groups = {s.name_key: s.group_key for s in db.scalars(select(m.StockName))}
    gs = list(db.scalars(select(m.StockGroup)))
    return groups, {g.group_key: g.display_name for g in gs}, {g.group_key: g.ticker for g in gs}


def state(db: Session) -> dict | None:
    imp = active_import(db)
    if imp is None:
        return None
    if "state" in _cache and _cache["state"]["import_id"] == imp.id:
        return _cache["state"]
    wb = L.from_dict(imp.data)
    fps = fingerprints(wb)
    decisions, stale = {}, []
    for d in db.scalars(select(m.Decision)):
        if fps.get(d.key) == d.fingerprint:
            decisions[d.key] = d.decision
        elif d.key in fps:
            stale.append(d.key)
    groups, gnames, tickers = _groups(db)
    manual = [{"id": t.id, "kind": t.kind, "date": t.date, "name": t.name, "shares": t.shares, "price": t.price,
               "currency": t.currency, "pence": t.pence, "broker": t.broker, "fee": t.fee, "note": t.note}
              for t in db.scalars(select(m.ManualTrade).order_by(m.ManualTrade.date, m.ManualTrade.id))]
    fees, stale_fees = {}, []
    for f in db.scalars(select(m.TradeFee)):
        if fps.get(f"P{f.trade_id[1:]}") == f.fingerprint:
            fees[f.trade_id] = f.amount
        else:
            stale_fees.append(f.trade_id)
    rb = R.rebuild(wb, decisions, groups, gnames, manual, fees)
    rt = rates(db)
    sales, lots = FIFO.run(rb.trades, rt, {p.row: p.pl for p in wb.positions})
    st = {"import_id": imp.id, "import": imp, "wb": wb, "rb": rb, "rates": rt, "sales": sales, "lots": lots,
          "decisions": decisions, "stale_decisions": stale, "tickers": tickers, "fingerprints": fps,
          "stale_fees": stale_fees, "groups": groups}
    _cache["state"] = st
    return st


def _need(db: Session) -> dict:
    st = state(db)
    if st is None:
        raise NotFound("Nothing imported yet: upload your workbook on the Import page.")
    return st


def as_of(st) -> date:
    saved = st["wb"].saved_at
    return datetime.fromisoformat(saved).date() if saved else st["import"].uploaded_at.date()


def status(db: Session) -> dict:
    st = state(db)
    if st is None:
        return {"imported": False}
    imp, wb, rb = st["import"], st["wb"], st["rb"]
    pending = Counter(i.kind for i in rb.review if i.status == "pending")
    return {
        "imported": True, "filename": imp.filename, "uploaded_at": imp.uploaded_at.isoformat(), "saved_at": wb.saved_at,
        "as_of": as_of(st).isoformat(), "sheet": wb.sheet_name, "sha256": imp.sha256,
        "position_rows": list(wb.position_rows), "sales_rows": list(wb.sales_rows) if wb.sales_rows else None,
        "accounting": rb.accounting, "review_pending": sum(pending.values()), "review_by_kind": dict(pending),
        "trades": len(rb.trades), "stale_decisions": st["stale_decisions"], "stale_fees": st["stale_fees"],
        "app_trades": sum(1 for t in rb.trades if t.source == "app"), "fx": _get(db, "fx_last"),
        "fx_latest": st["rates"].latest_date().isoformat() if st["rates"].latest_date() else None,
    }


# ---------------------------------------------------------------- review

def review(db: Session, kind: str | None = None, which: str = "pending") -> dict:
    st = _need(db)
    items = st["rb"].review
    counts = {"pending": Counter(i.kind for i in items if i.status == "pending"),
              "resolved": Counter(i.kind for i in items if i.status == "resolved")}
    sel = [i for i in items if (which == "all" or i.status == which) and (kind is None or i.kind == kind)]
    sel.sort(key=lambda i: (i.kind, i.row))
    return {"items": [_jsonable(asdict(i)) for i in sel], "kinds": R.REVIEW_KINDS,
            "counts": {k: dict(v) for k, v in counts.items()}}


def _validate_decision(key: str, d: dict, st) -> dict:
    a = d.get("action")
    if key.startswith("S"):
        if a not in R.SALE_ACTIONS:
            raise BadRequest(f"action must be one of {R.SALE_ACTIONS}")
        if a == "link":
            rows = d.get("rows") or []
            valid = {p.row for p in st["wb"].positions}
            if not rows or any(int(r) not in valid for r in rows):
                raise BadRequest("link needs one or more position rows of the Live Portfolio tab")
            return {"action": "link", "rows": [int(r) for r in rows]}
        return {"action": a}
    if a not in R.POSITION_ACTIONS:
        raise BadRequest(f"action must be one of {R.POSITION_ACTIONS}")
    out = {"action": a}
    if a == "exclude" and d.get("scope") == "leftover":
        out["scope"] = "leftover"
    if a == "add_buy":
        try:
            date.fromisoformat(d["date"])
            price, shares = float(d["price"]), float(d["shares"])
        except (KeyError, TypeError, ValueError) as e:
            raise BadRequest("add_buy needs a date (YYYY-MM-DD), a price and a number of shares") from e
        if price < 0 or shares <= 0:
            raise BadRequest("price must be ≥ 0 and shares > 0")
        out.update(date=d["date"], price=price, shares=shares)
    if a == "sell":
        try:
            date.fromisoformat(d["date"])
            price = float(d["price"])
        except (KeyError, TypeError, ValueError) as e:
            raise BadRequest("sell needs a date (YYYY-MM-DD) and a price") from e
        if price < 0:
            raise BadRequest("price can't be negative")
        out.update(date=d["date"], price=price)
    fields = d.get("fields")
    if fields:
        allowed = {"date", "shares", "price", "currency", "name", "live_price", "pence"}
        bad = set(fields) - allowed
        if bad:
            raise BadRequest(f"can't change {sorted(bad)}")
        f = dict(fields)
        if "currency" in f and str(f["currency"]).upper() not in R.KNOWN_CURRENCIES:
            raise BadRequest(f"currency must be one of {sorted(R.KNOWN_CURRENCIES)}")
        if "currency" in f:
            f["currency"] = str(f["currency"]).upper()
        if "date" in f:
            try:
                date.fromisoformat(f["date"])
            except ValueError as e:
                raise BadRequest("date must be YYYY-MM-DD") from e
        for k in ("shares", "price", "live_price"):
            if k in f:
                try:
                    f[k] = float(f[k])
                except (TypeError, ValueError) as e:
                    raise BadRequest(f"{k} must be a number") from e
        out["fields"] = f
    elif a == "fix":
        raise BadRequest("fix needs the fields to change")
    return out


def decide(db: Session, key: str, decision: dict) -> dict:
    st = _need(db)
    if key not in st["fingerprints"]:
        raise NotFound(f"no row {key} in the imported sheet")
    d = _validate_decision(key, decision, st)
    row = db.get(m.Decision, key)
    if row is None:
        db.add(m.Decision(key=key, fingerprint=st["fingerprints"][key], decision=d))
    else:
        row.fingerprint, row.decision = st["fingerprints"][key], d
    db.commit()
    _invalidate()
    return status(db)


def undo(db: Session, key: str) -> dict:
    db.execute(delete(m.Decision).where(m.Decision.key == key))
    db.commit()
    _invalidate()
    return status(db)


BULK = {"unsold_buy": ("exclude",), "closed_no_sale": ("exclude", "sale_row"), "sale_unlinked": ("sheet_only",)}


def bulk(db: Session, kind: str, action: str) -> dict:
    if action not in BULK.get(kind, ()):
        raise BadRequest(f"bulk '{action}' isn't available for '{kind}'")
    st = _need(db)
    keys = [i.key for i in st["rb"].review if i.status == "pending" and i.kind == kind]
    dec = {"action": action, **({"scope": "leftover"} if kind == "unsold_buy" else {})}
    for k in keys:
        row = db.get(m.Decision, k)
        if row is None:
            db.add(m.Decision(key=k, fingerprint=st["fingerprints"][k], decision=dec))
        else:
            row.fingerprint, row.decision = st["fingerprints"][k], dec
    db.commit()
    _invalidate()
    return {**status(db), "applied": len(keys)}


# ---------------------------------------------------------------- stocks

def stocks(db: Session) -> dict:
    st = _need(db)
    wb = st["wb"]
    groups, gnames, tickers = _groups(db)
    by_key: dict[str, dict] = {}
    for p in wb.positions:
        k = R.name_key(p.name) or f"row {p.row}"
        e = by_key.setdefault(k, {"name_key": k, "names": Counter(), "rows": 0, "open_rows": 0, "currencies": set()})
        e["names"][p.name] += 1
        e["rows"] += 1
        e["open_rows"] += p.status == "open"
        e["currencies"].add(p.currency)
    out: dict[str, dict] = {}
    for k, e in by_key.items():
        g = groups.get(k, k)
        grp = out.setdefault(g, {"group_key": g, "display_name": gnames.get(g) or by_key.get(g, e)["names"].most_common(1)[0][0],
                                 "ticker": tickers.get(g), "names": [], "rows": 0, "open_rows": 0, "currencies": set()})
        grp["names"].append({"name_key": k, "as_written": sorted(e["names"]), "rows": e["rows"]})
        grp["rows"] += e["rows"]
        grp["open_rows"] += e["open_rows"]
        grp["currencies"] |= e["currencies"]
    sugg = [s for s in N.suggestions(list(by_key)) if len({groups.get(k, k) for k in s}) > 1]
    rows = sorted(({**g, "currencies": sorted(g["currencies"])} for g in out.values()), key=lambda g: g["display_name"].lower())
    return {"stocks": rows, "suggestions": [[{"name_key": k, "group_key": groups.get(k, k),
                                             "as_written": sorted(by_key[k]["names"])} for k in s] for s in sugg]}


def merge(db: Session, name_keys: list[str], display_name: str | None) -> dict:
    st = _need(db)
    known = {R.name_key(p.name) or f"row {p.row}" for p in st["wb"].positions}
    if len(name_keys) < 2 or any(k not in known for k in name_keys):
        raise BadRequest("choose two or more stock names from the sheet")
    groups, _, _ = _groups(db)
    target = groups.get(name_keys[0], name_keys[0])
    members = {k for k, g in groups.items() if g in {groups.get(x, x) for x in name_keys}} | set(name_keys)
    for k in members:
        row = db.get(m.StockName, k)
        if row is None:
            db.add(m.StockName(name_key=k, group_key=target))
        else:
            row.group_key = target
    g = db.get(m.StockGroup, target)
    name = (display_name or "").strip() or None
    if g is None:
        db.add(m.StockGroup(group_key=target, display_name=name or name_keys[0]))
    elif name:
        g.display_name = name
    db.commit()
    _invalidate()
    return stocks(db)


def split(db: Session, name_key: str) -> dict:
    db.execute(delete(m.StockName).where(m.StockName.name_key == name_key))
    db.commit()
    _invalidate()
    return stocks(db)


def rename(db: Session, group_key: str, display_name: str | None, ticker: str | None) -> dict:
    g = db.get(m.StockGroup, group_key)
    if g is None:
        g = m.StockGroup(group_key=group_key, display_name=group_key)
        db.add(g)
    if display_name is not None and display_name.strip():
        g.display_name = display_name.strip()
    if ticker is not None:
        g.ticker = ticker.strip().upper() or None
    db.commit()
    _invalidate()
    return stocks(db)


# ---------------------------------------------------------------- results

def _sale_dict(s: FIFO.Sale) -> dict:
    return _jsonable(asdict(s))


def sales(db: Session, year: int | None = None) -> dict:
    st = _need(db)
    ss = [s for s in st["sales"] if year is None or s.date.year == year]
    years = defaultdict(lambda: {"sales": 0, "gain_usd": 0.0, "wins": 0, "losses": 0, "not_computed": 0, "sheet_pl": 0.0})
    for s in st["sales"]:
        y = years[s.date.year]
        y["sales"] += 1
        y["sheet_pl"] += s.sheet_pl or 0.0
        if s.gain_usd is None:
            y["not_computed"] += 1
        else:
            y["gain_usd"] += s.gain_usd
            y["wins"] += s.gain_usd > 0
            y["losses"] += s.gain_usd < 0
    done = [s for s in ss if s.gain_usd is not None]
    return {"sales": [_sale_dict(s) for s in sorted(ss, key=lambda s: (s.date, s.row), reverse=True)],
            "by_year": [{"year": k, **v} for k, v in sorted(years.items())],
            "totals": {"sales": len(ss), "gain_usd": sum(s.gain_usd for s in done), "not_computed": len(ss) - len(done),
                       "proceeds_usd": sum(s.proceeds_usd for s in done), "cost_usd": sum(s.cost_usd for s in done)},
            "as_of": as_of(st).isoformat(), "method": "FIFO per stock and currency, across brokers; USD at the ECB rate of each trade date"}


def current_prices(db: Session, st) -> dict[str, dict]:
    """pool -> {price, date, source}: the newest of the sheet's Live Price (open rows, workbook save date) and
    prices entered in the app or read from an updated workbook."""
    ref = as_of(st)
    out: dict[str, dict] = {}
    for t in st["rb"].trades:
        if t.kind != "buy" or t.source != "sheet":
            continue
        p = st["rb"].position_by_row.get(t.row)
        if p is not None and p.live_price is not None and p.status == "open":
            cur = out.get(t.pool)
            if cur is None or p.row > cur["row"]:
                out[t.pool] = {"price": p.live_price, "date": ref, "source": f"sheet (row {p.row})", "row": p.row}
    for pr in db.scalars(select(m.Price).order_by(m.Price.date, m.Price.id)):
        cur = out.get(pr.pool)
        if cur is None or pr.date >= cur["date"]:
            out[pr.pool] = {"price": pr.price, "date": pr.date, "source": pr.source, "row": None, "id": pr.id}
    return out


def positions(db: Session) -> dict:
    st = _need(db)
    rt = st["rates"]
    ref = as_of(st)
    prices = current_prices(db, st)
    pools: dict[str, dict] = {}
    for lot in st["lots"]:
        pool = f"{lot.stock_key}|{lot.currency}"
        g = pools.setdefault(pool, {"stock": lot.stock, "stock_key": lot.stock_key, "currency": lot.currency, "lots": [],
                                    "shares": 0.0, "cost_local": 0.0, "cost_usd": 0.0, "cost_usd_missing": False})
        cl = lot.shares * lot.price * lot.scale + lot.shares * lot.fee_per_share
        g["lots"].append({"buy_id": lot.buy_id, "row": lot.row, "date": lot.date.isoformat(), "broker": lot.broker,
                          "shares": lot.shares, "price": lot.price, "cost_local": cl, "source": lot.source,
                          "cost_usd": cl * lot.cost_rate if lot.cost_rate is not None else None,
                          "days_held": (ref - lot.date).days})
        g["shares"] += lot.shares
        g["cost_local"] += cl
        if lot.cost_rate is None:
            g["cost_usd_missing"] = True
        else:
            g["cost_usd"] += cl * lot.cost_rate
        g["scale"] = lot.scale
    out = []
    for pool, g in pools.items():
        px = prices.get(pool)
        price = px["price"] if px else None
        pdate = px["date"] if px else ref
        rate = rt.usd(g["currency"], pdate)
        value_local = g["shares"] * price * g["scale"] if price is not None else None
        value_usd = value_local * rate.rate if value_local is not None and rate else None
        cost_usd = None if g["cost_usd_missing"] else g["cost_usd"]
        unreal = value_usd - cost_usd if value_usd is not None and cost_usd is not None else None
        out.append({**{k: v for k, v in g.items() if k not in ("cost_usd_missing", "scale")}, "pool": pool, "cost_usd": cost_usd,
                    "ticker": st["tickers"].get(g["stock_key"]) if g["currency"] == "USD" else None,
                    "avg_cost": g["cost_local"] / (g["shares"] * g["scale"]) if g["shares"] else None,
                    "price": price, "price_from_row": px["row"] if px else None, "price_date": pdate.isoformat() if px else None,
                    "price_source": px["source"] if px else None, "pence": g["scale"] == 0.01, "value_local": value_local,
                    "value_usd": value_usd, "rate": rate.rate if rate else None,
                    "rate_date": rate.rate_date.isoformat() if rate and rate.rate_date else None,
                    "unrealised_usd": unreal, "unrealised_pct": unreal / cost_usd * 100 if unreal is not None and cost_usd else None,
                    "days_held": sum(lot["shares"] * lot["days_held"] for lot in g["lots"]) / g["shares"] if g["shares"] else None})
    tot_v = sum(x["value_usd"] for x in out if x["value_usd"] is not None)
    for x in out:
        x["weight_pct"] = x["value_usd"] / tot_v * 100 if x["value_usd"] is not None and tot_v else None
    out.sort(key=lambda x: -(x["value_usd"] or 0))
    computed = [x for x in out if x["unrealised_usd"] is not None]
    dates = sorted({x["price_date"] for x in out if x["price_date"]})
    valued = date.fromisoformat(dates[-1]) if dates else ref
    return {"positions": out, "as_of": valued.isoformat(), "sheet_as_of": ref.isoformat(),
            "totals": {"value_usd": tot_v, "cost_usd": sum(x["cost_usd"] for x in computed),
                       "unrealised_usd": sum(x["unrealised_usd"] for x in computed), "not_computed": len(out) - len(computed)},
            "price_note": (f"Prices: the Live Price saved in your workbook on {ref.isoformat()}, unless a newer price was entered on "
                           "the Prices page (each position shows its price date and source).")}


def check(db: Session) -> dict:
    st = _need(db)
    return C.check(st["wb"], st["rb"])


# ---------------------------------------------------------------- phase 2: analysis

LIMITS = ("Your sheet only has today's prices, so what the portfolio was worth on past dates isn't known: per-year "
          "figures use realised gains (and dividends). Fees and dividends count once entered in the app (the sheet doesn't "
          "record them); interest isn't included. Rows still on the Review page are left out.")


def _buys(st) -> list[dict]:
    rt = st["rates"]
    out = []
    for t in st["rb"].trades:
        if t.kind != "buy":
            continue
        r = rt.usd(t.currency, t.date)
        out.append({"pool": t.pool, "stock": t.stock, "stock_key": t.stock_key, "currency": t.currency, "date": t.date,
                    "shares": t.shares, "price": t.price, "scale": t.scale, "row": t.row, "id": t.id, "broker": t.broker,
                    "cost_local": t.value, "cost_usd": t.value * r.rate if r else None,
                    "rate": r.rate if r else None, "rate_date": r.rate_date.isoformat() if r and r.rate_date else None})
    return out


def capital_flows(db: Session, st=None) -> tuple[list[dict], list[tuple[date, float]], list[str]]:
    """Entered deposits/withdrawals with USD values at the ECB rate of their date; problems for any without a rate."""
    rt = st["rates"] if st else rates(db)
    rows, usd, problems = [], [], []
    for f in db.scalars(select(m.CapitalFlow).order_by(m.CapitalFlow.date, m.CapitalFlow.id)):
        r = rt.usd(f.currency, f.date)
        v = f.amount * r.rate if r else None
        if v is None:
            problems.append(f"No ECB rate for {f.currency} on {f.date}: that entry is left out.")
        else:
            usd.append((f.date, v))
        rows.append({"id": f.id, "date": f.date.isoformat(), "amount": f.amount, "currency": f.currency, "account": f.account,
                     "note": f.note, "usd": v, "rate": r.rate if r else None})
    return rows, usd, problems


def add_capital(db: Session, d: dict) -> dict:
    try:
        when = date.fromisoformat(str(d["date"]))
        amount = float(d["amount"])
    except (KeyError, TypeError, ValueError) as e:
        raise BadRequest("needs a date (YYYY-MM-DD) and an amount (+ deposit, − withdrawal)") from e
    cur = str(d.get("currency") or "USD").strip().upper()
    if cur not in R.KNOWN_CURRENCIES:
        raise BadRequest(f"currency must be one of {sorted(R.KNOWN_CURRENCIES)}")
    if amount == 0:
        raise BadRequest("amount can't be 0")
    if when > datetime.now(timezone.utc).date():
        raise BadRequest("date can't be in the future")
    db.add(m.CapitalFlow(date=when, amount=amount, currency=cur, account=(d.get("account") or None),
                         note=(d.get("note") or None)))
    db.commit()
    if cur not in ("USD", "EUR") or not st_rates_cover(db, cur, when):
        ensure_fx_for(db, [cur], when)
    return capital(db)


def st_rates_cover(db: Session, cur: str, when: date) -> bool:
    rt = rates(db)
    return cur == "USD" or rt.usd(cur, when) is not None


def ensure_fx_for(db: Session, curs: list[str], start: date) -> None:
    try:
        rows = FX_FETCH([c for c in curs if c not in ("USD", "EUR")], start - timedelta(days=10))
    except FX.FxError:
        return
    existing = {(r.date, r.currency) for r in db.scalars(select(m.FxRate))}
    for d, c, v in rows:
        if (d, c) not in existing:
            db.add(m.FxRate(date=d, currency=c, per_eur=v))
    db.commit()
    _invalidate()


def delete_capital(db: Session, flow_id: int) -> dict:
    f = db.get(m.CapitalFlow, flow_id)
    if f is None:
        raise NotFound(f"entry {flow_id} not found")
    db.delete(f)
    db.commit()
    return capital(db)


def capital(db: Session) -> dict:
    st = state(db)
    rows, _, problems = capital_flows(db, st)
    cash = st["wb"].cash if st else []
    return {"flows": rows, "problems": problems, "sheet_cash": cash,
            "sheet_cash_note": "As recorded in your sheet's cash block (header 'Orginal | Dollar'). Shown for reference; "
                               "not used in any calculation."}


def analysis(db: Session) -> dict:
    st = _need(db)
    sales = st["sales"]
    buys = _buys(st)
    pos = positions(db)
    flows, cap_usd, problems = capital_flows(db, st)
    from .entries import dividend_list
    _, divs, div_problems = dividend_list(db, st)
    problems = problems + div_problems
    ref = date.fromisoformat(pos["as_of"])
    buy_flows = [(b["date"], b["cost_usd"]) for b in buys]
    tl = AN.timeline(buy_flows, sales, ref)
    t = pos["totals"]
    by_broker: dict[str, float] = defaultdict(float)
    by_cur: dict[str, float] = defaultdict(float)
    for p in pos["positions"]:
        if p["value_usd"] is None:
            continue
        lots_sh = sum(lot["shares"] for lot in p["lots"]) or 1.0
        for lot in p["lots"]:
            by_broker[lot["broker"] or "—"] += p["value_usd"] * lot["shares"] / lots_sh
        by_cur[p["currency"]] += p["value_usd"]
    tot = sum(by_cur.values())

    def alloc(d):
        return [{"label": k, "value_usd": v, "pct": v / tot * 100 if tot else None} for k, v in sorted(d.items(), key=lambda x: -x[1])]

    return {
        "as_of": ref.isoformat(),
        "statistics": AN.statistics(sales),
        "months": AN.months(sales),
        "years": AN.years(sales, tl, cap_usd or None, [(d, v) for d, v, _ in divs]),
        "timeline": [{"date": p.date.isoformat(), "invested_usd": p.invested_usd, "realised_cum_usd": p.realised_cum_usd} for p in tl],
        "returns": AN.returns(buy_flows, sales, t["value_usd"], t["cost_usd"] if not t["not_computed"] else None, ref, cap_usd or None,
                              [(d, v) for d, v, _ in divs]),
        "dividends": {"total_usd": sum(v for _, v, _ in divs), "count": len(divs)},
        "allocation": {"by_broker": alloc(by_broker), "by_currency": alloc(by_cur),
                       "by_stock": [{"label": p["stock"] + (f" ({p['currency']})" if p["currency"] != "USD" else ""),
                                     "value_usd": p["value_usd"], "pct": p["weight_pct"]} for p in pos["positions"] if p["value_usd"] is not None]},
        "open": {"value_usd": t["value_usd"], "cost_usd": t["cost_usd"], "unrealised_usd": t["unrealised_usd"],
                 "positions": len(pos["positions"])},
        "capital_entries": len(flows), "capital_problems": problems,
        "review_pending": st["rb"].accounting["review_pending"],
        "limits": LIMITS,
    }


def by_stock(db: Session) -> dict:
    st = _need(db)
    pos = positions(db)
    values = {f"{p['stock_key']}|{p['currency']}": p for p in pos["positions"]}
    from .entries import dividend_list
    _, divs, _ = dividend_list(db, st)
    rows = AN.per_stock(st["sales"], st["lots"], _buys(st), values, divs)
    return {"stocks": rows, "as_of": as_of(st).isoformat(), "limits": LIMITS}


def stock_detail(db: Session, pool: str) -> dict:
    st = _need(db)
    buys = [b for b in _buys(st) if b["pool"] == pool]
    sales = [s for s in st["sales"] if f"{s.stock_key}|{s.currency}" == pool]
    if not buys and not sales:
        raise NotFound("no trades for that stock")
    pos = next((p for p in positions(db)["positions"] if f"{p['stock_key']}|{p['currency']}" == pool), None)
    summary = next((r for r in by_stock(db)["stocks"] if r["pool"] == pool), None)
    trades = [{"kind": "buy", "date": b["date"].isoformat(), "shares": b["shares"], "price": b["price"], "row": b["row"],
               "broker": b["broker"], "value_usd": b["cost_usd"], "gain_usd": None, "id": b["id"]} for b in buys]
    trades += [{"kind": "sell", "date": s.date.isoformat(), "shares": s.shares, "price": s.price, "row": s.row,
                "broker": s.broker, "value_usd": s.proceeds_usd, "gain_usd": s.gain_usd, "gain_pct": s.gain_pct,
                "days_held": s.days_held, "id": s.id, "matches": [_jsonable(asdict(mm)) for mm in s.matches]} for s in sales]
    trades.sort(key=lambda x: (x["date"], 0 if x["kind"] == "buy" else 1))
    return {"pool": pool, "summary": summary, "position": pos, "trades": trades, "as_of": as_of(st).isoformat()}
