"""What-if service: builds holdings from the current state and runs the engine. Also stock sectors."""
from __future__ import annotations

import json
import os
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.engine import whatif as W

from . import portfolio as P
from .portfolio import BadRequest, NotFound

SECTORS = ["Information Technology", "Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy",
           "Financials", "Health Care", "Industrials", "Materials", "Real Estate", "Utilities", "Fund / ETF", "Crypto-related", "Other"]
MODEL = "claude-opus-5-5"


# ---------------------------------------------------------------- sectors

def _sector_rows(db: Session) -> dict[str, m.StockSector]:
    return {r.group_key: r for r in db.scalars(select(m.StockSector))}


def confirmed_sectors(db: Session) -> dict[str, str]:
    return {k: r.sector for k, r in _sector_rows(db).items() if r.confirmed}


def sectors(db: Session) -> dict:
    st = P._need(db)
    rows = _sector_rows(db)
    open_keys = {lot.stock_key for lot in st["lots"]}
    names: dict[str, str] = {}
    for t in st["rb"].trades:
        names.setdefault(t.stock_key, t.stock)
    out = [{"group_key": k, "stock": n, "open": k in open_keys, "sector": rows[k].sector if k in rows else None,
            "source": rows[k].source if k in rows else None, "confirmed": rows[k].confirmed if k in rows else False}
           for k, n in sorted(names.items(), key=lambda x: x[1].lower())]
    return {"stocks": out, "sectors": SECTORS, "ai_available": ai_available(),
            "counts": {"open": len(open_keys), "open_confirmed": sum(1 for x in out if x["open"] and x["confirmed"]),
                       "suggested_unconfirmed": sum(1 for x in out if x["sector"] and not x["confirmed"])}}


def set_sector(db: Session, group_key: str, sector: str | None) -> dict:
    if sector is not None and sector not in SECTORS:
        raise BadRequest(f"sector must be one of {SECTORS}")
    row = db.get(m.StockSector, group_key)
    if sector is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(m.StockSector(group_key=group_key, sector=sector, source="you", confirmed=True))
    else:
        row.sector, row.source, row.confirmed = sector, "you", True
    db.commit()
    return sectors(db)


def confirm_all(db: Session) -> dict:
    for r in db.scalars(select(m.StockSector).where(m.StockSector.confirmed.is_(False))):
        r.confirmed = True
    db.commit()
    return sectors(db)


def ai_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def make_client():  # replaced in tests
    import anthropic
    return anthropic.Anthropic()


def suggest_sectors(db: Session, only_open: bool = True) -> dict:
    """Ask Claude for a sector per stock name (structured output); stored unconfirmed for you to check."""
    import anthropic
    data = sectors(db)
    todo = [x for x in data["stocks"] if not x["confirmed"] and (x["open"] or not only_open)]
    if not todo:
        return {**data, "suggested": 0}
    schema = {"type": "object", "additionalProperties": False, "required": ["items"],
              "properties": {"items": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["id", "sector"],
                  "properties": {"id": {"type": "integer"}, "sector": {"type": "string", "enum": SECTORS}}}}}}
    listing = "\n".join(f"{i}: {x['stock']}" for i, x in enumerate(todo))
    prompt = ("Assign each stock or fund below to one GICS sector. The names are as written in a personal trading "
              "spreadsheet, so some are abbreviated or misspelled. Use 'Fund / ETF' for funds, ETFs and certificates, "
              "'Crypto-related' for crypto miners and bitcoin treasury companies, and 'Other' only if you can't tell what "
              f"the name refers to. Return one item per id.\n\n{listing}")
    try:
        resp = make_client().beta.messages.create(
            model=MODEL, max_tokens=16000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}])
    except anthropic.AuthenticationError as e:
        raise BadRequest("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in the app's .env file.") from e
    except anthropic.APIConnectionError as e:
        raise BadRequest("Couldn't reach Anthropic's API. Check your internet connection.") from e
    except anthropic.APIStatusError as e:
        raise BadRequest(f"Anthropic's API answered {e.status_code}: {e.message}") from e
    if resp.stop_reason == "refusal":
        raise BadRequest("The request was declined by the model's safety checks; set the sectors yourself.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        items = json.loads(text)["items"]
    except (ValueError, KeyError) as e:
        raise BadRequest("The suggestion came back incomplete; try again.") from e
    rows = _sector_rows(db)
    n = 0
    for it in items:
        i, sec = it.get("id"), it.get("sector")
        if not isinstance(i, int) or not 0 <= i < len(todo) or sec not in SECTORS:
            continue
        k = todo[i]["group_key"]
        if k in rows:
            if not rows[k].confirmed:
                rows[k].sector, rows[k].source = sec, "ai"
        else:
            db.add(m.StockSector(group_key=k, sector=sec, source="ai", confirmed=False))
        n += 1
    db.commit()
    return {**sectors(db), "suggested": n}


# ---------------------------------------------------------------- holdings

def holdings(db: Session) -> tuple[dict[str, W.Holding], date, float, dict]:
    st = P._need(db)
    pos = P.positions(db)
    secs = confirmed_sectors(db)
    by_pool: dict[str, list] = {}
    for lot in st["lots"]:  # already in FIFO order within each pool
        by_pool.setdefault(f"{lot.stock_key}|{lot.currency}", []).append(lot)
    hs = {}
    for p in pos["positions"]:
        lots = by_pool.get(p["pool"], [])
        if not lots:
            continue
        hs[p["pool"]] = W.Holding(p["pool"], p["stock"], p["currency"], secs.get(p["stock_key"]), lots, p["price"],
                                  0.01 if p["pence"] else 1.0, p["rate"], p["price_date"])
    today = date.fromisoformat(pos["as_of"])
    ytd = sum(s.gain_usd for s in st["sales"] if s.gain_usd is not None and s.date.year == today.year)
    return hs, today, ytd, pos


def overview(db: Session) -> dict:
    hs, today, ytd, pos = holdings(db)
    rows = [{"pool": h.pool, "stock": h.stock, "currency": h.currency, "sector": h.sector, "shares": h.shares,
             "price": h.price, "pence": h.scale == 0.01, "value_usd": h.value_usd, "cost_usd": h.cost_usd,
             "unrealised_usd": (h.value_usd - h.cost_usd) if h.value_usd is not None and h.cost_usd is not None else None,
             "price_date": h.price_date} for h in hs.values()]
    total = sum(r["value_usd"] or 0 for r in rows)
    for r in rows:
        r["weight_pct"] = r["value_usd"] / total * 100 if r["value_usd"] is not None and total else None
    by_sector: dict[str, float] = {}
    for r in rows:
        if r["value_usd"] is not None:
            k = r["sector"] or "(no sector)"
            by_sector[k] = by_sector.get(k, 0.0) + r["value_usd"]
    return {"as_of": today.isoformat(), "total_usd": total, "realised_this_year_usd": ytd,
            "holdings": sorted(rows, key=lambda r: -(r["value_usd"] or 0)),
            "sectors": [{"sector": k, "value_usd": v, "weight_pct": v / total * 100 if total else None}
                        for k, v in sorted(by_sector.items(), key=lambda x: -x[1])],
            "sector_list": SECTORS,
            "notes": "Before tax. Prices as of each position's price date; FIFO cost at purchase-date exchange rates."}


def simulate_sale(db: Session, items: list[dict] | None = None, sector: str | None = None, everything: bool = False,
                  percent: float | None = None, fee_per_sale: float = 0.0) -> dict:
    """items: [{pool, shares? , percent?}]; or a sector / everything with one percent (default 100)."""
    hs, today, ytd, _ = holdings(db)
    try:
        picks = []
        if items:
            for it in items:
                h = W.select(hs, [it.get("pool")])[0]
                sh = it.get("shares")
                pc = it.get("percent")
                if sh is None:
                    sh = h.shares * (100.0 if pc is None else float(pc)) / 100
                picks.append((h, float(sh)))
        else:
            pc = 100.0 if percent is None else float(percent)
            if not 0 < pc <= 100:
                raise W.WhatIfError("percent must be between 0 and 100")
            picks = [(h, h.shares * pc / 100) for h in W.select(hs, sector=sector, everything=everything)]
            picks = [(h, sh) for h, sh in picks if h.price is not None]
        out = W.sell_many(hs, picks, today, ytd, fee_per_sale)
    except W.WhatIfError as e:
        raise BadRequest(str(e)) from e
    out["as_of"] = today.isoformat()
    out["notes"] = ("Simulation only; nothing is sold or saved. FIFO: the oldest purchases are sold first. Before tax, "
                    "fees only if entered. Values at each position's latest price and today's ECB rate.")
    return out


def simulate_rebalance(db: Session, by: str, targets: dict[str, float], whole_shares: bool = True) -> dict:
    hs, today, ytd, _ = holdings(db)
    try:
        out = W.rebalance(hs, by, {k: float(v) for k, v in targets.items()}, today, ytd, whole_shares)
    except W.WhatIfError as e:
        raise BadRequest(str(e)) from e
    out["as_of"] = today.isoformat()
    return out


def simulate_average_down(db: Session, pool: str, buy_price: float | None = None, shares: float | None = None,
                          amount_usd: float | None = None, target_break_even: float | None = None, fee: float = 0.0) -> dict:
    hs, today, _, _ = holdings(db)
    try:
        h = W.select(hs, [pool])[0]
        out = W.average_down(h, today, buy_price, shares, amount_usd, target_break_even, fee)
    except W.WhatIfError as e:
        raise BadRequest(str(e)) from e
    out["as_of"] = today.isoformat()
    return out


def losers(db: Session) -> list[dict]:
    """Open positions below their FIFO cost, biggest loss first (for the average-down picker)."""
    rows = overview(db)["holdings"]
    return sorted([r for r in rows if r["unrealised_usd"] is not None and r["unrealised_usd"] < 0], key=lambda r: r["unrealised_usd"])


def find(db: Session, query: str) -> list[dict]:
    """Open positions whose name contains the words of `query` (for the assistant to resolve names)."""
    hs, _, _, _ = holdings(db)
    q = [w for w in query.lower().replace("-", " ").split() if w]
    hits = [h for h in hs.values() if all(w in h.stock.lower() for w in q)] or \
        [h for h in hs.values() if any(w in h.stock.lower() for w in q if len(w) > 2)]
    return [{"pool": h.pool, "stock": h.stock, "currency": h.currency, "sector": h.sector, "shares": h.shares,
             "value_usd": h.value_usd} for h in hits[:15]]


def not_found(msg: str):
    raise NotFound(msg)
