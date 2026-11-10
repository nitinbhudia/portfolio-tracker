"""Turn the parsed sheet + your review decisions into trades (SPEC.md §2).

How your sheet records trades (verified on the workbook: 503 of 577 sales match exactly):
- an **open** row is a purchase you still hold;
- a **closed row with P/L 0** and no sales-log line is a purchase whose shares were sold later;
- a **closed row the sales log points to** is a *sale*: dated on the sale day, with the shares sold,
  the buy price (Price Entry) and the sell price (Live Price, typed when you sold).
- a closed row with a P/L but no sales-log line was sold "in place" (mostly 2020, before the log):
  its sale date is unknown, so it goes on the review list.

Sales are matched to the closed purchase rows of the same stock (a quantity check, oldest first) to
find purchases no sale accounts for, and sales with no purchase before them. Both go on the review
list. Nothing is guessed: anything on the review list stays out of the results until you decide.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.importer.live_portfolio import PositionRow, SaleRow, Workbook

PENCE = {"GBP"}  # London prices are quoted in pence: value = shares × price / 100
KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "CHF", "SEK", "NOK", "DKK", "JPY", "AUD", "HKD", "PLN", "HUF", "CZK"}
EPS = 1e-6

REVIEW_KINDS = {
    "unsold_buy": "Closed purchase with shares no sale accounts for",
    "sale_missing_buy": "Sale with no earlier purchase in the sheet for some of its shares",
    "closed_no_sale": "Sold in place (P/L recorded) but no date in the sales log",
    "sell_price_missing": "Sold, but the sell price is still the live-price formula",
    "sale_on_open_row": "The sales log points to a row marked Open",
    "linked_twice": "Several sales-log lines point to this row",
    "bad_data": "Missing or unreadable shares, price, date or currency",
    "price_unit": "Price looks like pence/cents: the sheet's cost is 1/100 of shares × price",
    "sale_unlinked": "Sale typed by hand in the log (no link to a position row)",
}
ACTIONS = {
    "unsold_buy": ("exclude", "sell"),
    "sale_missing_buy": ("add_buy", "exclude"),
    "closed_no_sale": ("sale_row", "sell", "exclude"),
    "sell_price_missing": ("sell", "exclude"),
    "sale_on_open_row": ("keep_open", "sell", "exclude"),
    "linked_twice": ("sell", "exclude"),
    "bad_data": ("fix", "exclude"),
    "price_unit": ("fix", "keep", "exclude"),
    "sale_unlinked": ("sheet_only", "link"),
}
POSITION_ACTIONS = ("sell", "exclude", "keep_open", "keep", "fix", "add_buy", "sale_row", "edit")
SALE_ACTIONS = ("sheet_only", "link")


def name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


@dataclass
class Trade:
    id: str
    kind: str  # "buy" | "sell"
    date: date
    stock: str  # display name of the stock group
    stock_key: str
    pool: str  # FIFO pool = stock + currency
    shares: float
    price: float
    currency: str
    scale: float  # 0.01 for prices in pence
    broker: str
    row: int  # position row
    sale_row: int | None = None  # sales-log row, for sells
    ref_price: float | None = None  # for sells: the buy price written on the sale row (the sheet's cost)
    note: str | None = None
    fee: float = 0.0  # in the trade's currency (not pence): added to a purchase's cost, taken off a sale's proceeds
    source: str = "sheet"  # "sheet" | "app" (entered in the app)

    @property
    def value(self) -> float:
        return self.shares * self.price * self.scale


@dataclass
class ReviewItem:
    key: str  # "P<row>" for position rows, "S<row>" for sales-log rows
    kind: str
    row: int
    title: str
    detail: str
    data: dict
    status: str = "pending"  # pending | resolved
    decision: dict | None = None
    actions: tuple[str, ...] = ()


@dataclass
class Rebuild:
    trades: list[Trade]
    review: list[ReviewItem]
    excluded_rows: list[int]
    accounting: dict
    sale_links: dict[int, list[int]]  # position row -> sales-log rows pointing to it
    position_by_row: dict[int, PositionRow] = field(default_factory=dict)
    roles: dict[int, str] = field(default_factory=dict)  # row -> open_buy | closed_buy | sale | sold_in_place | out


def _apply_fields(p: PositionRow, fields: dict | None) -> PositionRow:
    if not fields:
        return p
    kw = {k: fields[k] for k in ("date", "shares", "price", "currency", "name", "live_price") if k in fields}
    if "date" in kw and isinstance(kw["date"], str):
        kw["date"] = date.fromisoformat(kw["date"])
    if "pence" in fields:
        kw["formulas"] = {**p.formulas, "_pence": "1" if fields["pence"] else "0"}
    return PositionRow(**{**p.__dict__, **kw})


def _scale(p: PositionRow) -> float:
    flag = p.formulas.get("_pence")
    if flag is not None:
        return 0.01 if flag == "1" else 1.0
    return 0.01 if p.currency in PENCE else 1.0


def _unit_problem(p: PositionRow) -> str | None:
    if not (p.cost and p.shares and p.price):
        return None
    ratio = p.cost / (p.shares * p.price * _scale(p))
    if 0.0095 <= ratio <= 0.0105:
        return (f"Sheet cost {p.cost:,.2f} is 1/100 of shares × price ({p.shares * p.price * _scale(p):,.2f}) in {p.currency}: "
                "the price is probably in pence or cents (e.g. a London listing).")
    return None


def _bad(p: PositionRow) -> str | None:
    miss = [k for k, v in (("date", p.date), ("shares", p.shares), ("buy price", p.price)) if v is None]
    if p.shares is not None and p.shares <= 0:
        miss.append("shares > 0")
    if p.currency not in KNOWN_CURRENCIES:
        miss.append(f"currency (found '{p.currency}')")
    return ("Missing or unreadable: " + ", ".join(miss) + ".") if miss else None


def _pdata(p: PositionRow, lrows: list[int]) -> dict:
    return {"date": p.date.isoformat() if p.date else None, "name": p.name, "shares": p.shares, "price": p.price,
            "sell_price": None if p.live_price_is_formula else p.live_price, "live_price": p.live_price,
            "currency": p.currency, "broker": p.broker, "status": p.status, "sheet_cost": p.cost, "sheet_pl": p.pl,
            "sales_log_rows": lrows}


def _sdata(s: SaleRow) -> dict:
    return {"date": s.date.isoformat(), "stock": s.stock, "sheet_pl": s.pl, "sheet_pl_pct": s.pl_pct,
            "sheet_pl_usd": s.pl_usd, "formula": s.pl_formula}


def _parse_sale(dec: dict) -> tuple[date, float] | None:
    try:
        return date.fromisoformat(dec["date"]), float(dec["price"])
    except (KeyError, TypeError, ValueError):
        return None


def rebuild(wb: Workbook, decisions: dict[str, dict] | None = None, groups: dict[str, str] | None = None,
            group_names: dict[str, str] | None = None, manual: list[dict] | None = None,
            fees: dict[str, float] | None = None) -> Rebuild:
    """decisions: review key -> decision. groups: name_key -> stock group key; group_names: group -> display name.
    manual: trades entered in the app ({id, kind, date, name, shares, price, currency, pence, broker, fee}).
    fees: trade id (B12, S40, A40, L7) -> fee in the trade's currency, for trades from the sheet."""
    decisions = decisions or {}
    groups = groups or {}
    group_names = group_names or {}
    pos_by_row = {p.row: p for p in wb.positions}
    sale_by_row = {s.row: s for s in wb.sales}
    review: list[ReviewItem] = []

    # ---- sales-log lines -> the position rows they point to
    links: dict[int, list[int]] = {}
    for s in wb.sales:
        dec = decisions.get(f"S{s.row}")
        rows = s.linked_rows
        if s.link == "typed" or not rows:
            item = ReviewItem(f"S{s.row}", "sale_unlinked", s.row, REVIEW_KINDS["sale_unlinked"],
                              f"{s.date.isoformat()} · {s.stock} · P/L {s.pl}", _sdata(s), actions=ACTIONS["sale_unlinked"])
            rows = []
            if dec and dec.get("action") in SALE_ACTIONS:
                item.status, item.decision = "resolved", dec
                if dec["action"] == "link":
                    rows = [int(r) for r in dec.get("rows", []) if int(r) in pos_by_row]
            review.append(item)
        for r in rows:
            links.setdefault(r, []).append(s.row)

    def stock_of(p: PositionRow) -> tuple[str, str]:
        k = name_key(p.name) or f"row {p.row}"
        g = groups.get(k, k)
        return g, group_names.get(g, p.name or f"row {p.row}")

    def mk(kind: str, p: PositionRow, d: date, shares: float, price: float, id_: str, sale_row=None, ref=None, note=None) -> Trade:
        g, disp = stock_of(p)
        return Trade(id=id_, kind=kind, date=d, stock=disp, stock_key=g, pool=f"{g}|{p.currency}", shares=float(shares),
                     price=float(price), currency=p.currency, scale=_scale(p), broker=p.broker, row=p.row,
                     sale_row=sale_row, ref_price=ref, note=note)

    trades: list[Trade] = []
    roles: dict[int, str] = {}
    excluded: list[int] = []
    pending_rows: set[int] = set()

    def add_item(p: PositionRow, kind: str, detail: str, status: str = "pending", dec=None, lrows=()):
        review.append(ReviewItem(f"P{p.row}", kind, p.row, REVIEW_KINDS[kind], detail, _pdata(p, list(lrows)),
                                 status=status, decision=dec if status == "resolved" else None, actions=ACTIONS[kind]))
        if status == "pending":
            pending_rows.add(p.row)

    # ---- first pass: classify each row, apply row-level decisions
    for p0 in wb.positions:
        dec = decisions.get(f"P{p0.row}") or {}
        action = dec.get("action")
        p = _apply_fields(p0, dec.get("fields"))
        lrows = links.get(p.row, [])
        if action == "exclude" and dec.get("scope") != "leftover":
            excluded.append(p.row)
            roles[p.row] = "out"
            continue
        if (bad := _bad(p)):
            add_item(p, "bad_data", bad, lrows=lrows)
            roles[p.row] = "out"
            continue
        if (unit := _unit_problem(p)):
            if action == "keep":
                add_item(p, "price_unit", unit, "resolved", dec, lrows)
            else:
                add_item(p, "price_unit", unit, lrows=lrows)
                roles[p.row] = "out"
                continue
        if action == "fix":
            add_item(p, "bad_data" if _bad(p0) else "price_unit", "Fixed on the review page.", "resolved", dec, lrows)

        if p.status == "open":
            if lrows and action != "keep_open":
                if action == "sell" and (sd := _parse_sale(dec)):
                    trades.append(mk("sell", p, sd[0], p.shares, sd[1], f"S{p.row}", lrows[0], p.price, "sale entered on the review page"))
                    roles[p.row] = "sale"
                    add_item(p, "sale_on_open_row", "Treated as a sale.", "resolved", dec, lrows)
                    continue
                s = sale_by_row[lrows[0]]
                add_item(p, "sale_on_open_row", f"Sales-log row {s.row} ({s.date}) points here, but the row is marked Open.", lrows=lrows)
                roles[p.row] = "out"
                continue
            if lrows:
                add_item(p, "sale_on_open_row", "Kept open; the sales-log link is ignored.", "resolved", dec, lrows)
            trades.append(mk("buy", p, p.date, p.shares, p.price, f"B{p.row}"))
            roles[p.row] = "open_buy"
            continue

        # closed rows
        if len(lrows) > 1:
            sd = _parse_sale(dec) if action == "sell" else None
            if sd:
                trades.append(mk("sell", p, sd[0], p.shares, sd[1], f"S{p.row}", lrows[0], p.price, "sale entered on the review page"))
                roles[p.row] = "sale"
                add_item(p, "linked_twice", "Sale date and price entered.", "resolved", dec, lrows)
            else:
                add_item(p, "linked_twice", f"Sales-log rows {', '.join(map(str, lrows))} all point to this row.", lrows=lrows)
                roles[p.row] = "out"
            continue
        if len(lrows) == 1:
            s = sale_by_row[lrows[0]]
            if p.live_price_is_formula or p.live_price is None:
                sd = _parse_sale(dec) if action == "sell" else None
                if not sd:
                    add_item(p, "sell_price_missing", f"Sold on {s.date} (sales-log row {s.row}), but Live Price is still a formula, "
                             "so the sell price isn't known.", lrows=lrows)
                    roles[p.row] = "out"
                    continue
                add_item(p, "sell_price_missing", "Sell price entered.", "resolved", dec, lrows)
                trades.append(mk("sell", p, sd[0], p.shares, sd[1], f"S{p.row}", s.row, p.price))
            else:
                sale_day = date.fromisoformat(dec["fields"]["sale_date"]) if (dec.get("fields") or {}).get("sale_date") else s.date
                trades.append(mk("sell", p, sale_day, p.shares, p.live_price, f"S{p.row}", s.row, p.price))
            roles[p.row] = "sale"
            continue
        if p.pl:  # sold in place, no date
            if action == "sale_row" and not p.live_price_is_formula and p.live_price is not None:
                trades.append(mk("sell", p, p.date, p.shares, p.live_price, f"S{p.row}", None, p.price,
                                 "sale row without a sales-log line, dated on the row's date"))
                roles[p.row] = "sale"
                add_item(p, "closed_no_sale", "Treated as a sale on the row's date.", "resolved", dec)
                continue
            sd = _parse_sale(dec) if action == "sell" else None
            if sd and sd[0] >= p.date:
                trades.append(mk("buy", p, p.date, p.shares, p.price, f"B{p.row}"))
                trades.append(mk("sell", p, sd[0], p.shares, sd[1], f"S{p.row}", None, p.price, "sale entered on the review page"))
                roles[p.row] = "sold_in_place"
                add_item(p, "closed_no_sale", "Sale date and price entered.", "resolved", dec)
            else:
                msg = (f"No sales-log line for this row (sheet P/L {p.pl:,.2f}). If it is the sale of an earlier purchase (your usual "
                       f"layout: the row is dated on the sale day), choose 'Sale on {p.date}' at {p.live_price:g}; if the row is both the "
                       "purchase and the sale, enter the sale date and price.") if not p.live_price_is_formula and p.live_price is not None \
                    else f"No sale date for this row (sheet P/L {p.pl:,.2f})."
                if sd:
                    msg = f"The sale date you gave ({sd[0]}) is before the buy date ({p.date})."
                add_item(p, "closed_no_sale", msg)
                roles[p.row] = "out"
            continue
        trades.append(mk("buy", p, p.date, p.shares, p.price, f"B{p.row}"))
        roles[p.row] = "closed_buy"

    # ---- extra purchases entered for sales with no buy
    for key, dec in decisions.items():
        if dec.get("action") == "add_buy" and key.startswith("P") and int(key[1:]) in pos_by_row:
            r = int(key[1:])
            if roles.get(r) == "sale":
                p = _apply_fields(pos_by_row[r], decisions[key].get("fields"))
                try:
                    d, px, sh = date.fromisoformat(dec["date"]), float(dec["price"]), float(dec["shares"])
                except (KeyError, TypeError, ValueError):
                    continue
                trades.append(mk("buy", p, d, sh, px, f"A{r}", note="purchase entered on the review page"))

    # ---- second pass: match sales to closed purchases by quantity (oldest first, not after the sale)
    by_pool: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_pool[t.pool].append(t)
    remove: set[str] = set()
    trim: dict[str, float] = defaultdict(float)
    extra: list[Trade] = []
    for pool, ts in by_pool.items():
        ts.sort(key=lambda t: (t.date, 0 if t.kind == "buy" else 1, t.row))
        lots: list[list] = []  # [trade, remaining]
        consumed: dict[str, list[tuple[str, float]]] = {}
        missing: dict[str, float] = {}
        for t in ts:
            if t.kind == "buy":
                if roles.get(t.row) != "open_buy":
                    lots.append([t, t.shares])
                continue
            need, used = t.shares, []
            for lot in lots:
                if need <= EPS:
                    break
                take = min(lot[1], need)
                if take > EPS:
                    lot[1] -= take
                    need -= take
                    used.append((lot[0].id, take))
            consumed[t.id] = used
            if need > EPS:
                missing[t.id] = need
        for t in ts:
            if t.id in missing:
                p = pos_by_row[t.row]
                dec = decisions.get(f"P{t.row}") or {}
                have = sum(x.shares for x in trades if x.id == f"A{t.row}")
                if dec.get("action") == "add_buy" and have >= missing[t.id] - EPS:
                    continue  # covered (the entered purchase is in the trades already)
                if dec.get("action") == "exclude":
                    continue
                add_item(p, "sale_missing_buy",
                         f"Sold {t.shares:g} on {t.date}, but the sheet has no earlier closed purchase of this stock for "
                         f"{missing[t.id]:g} of those shares. Enter the purchase (date and price; the sale row's buy price is "
                         f"{p.price:g}) or exclude the sale.", lrows=links.get(t.row, []))
                review[-1].data["missing_shares"] = missing[t.id]
                remove.add(t.id)
                for bid, q in consumed[t.id]:
                    trim[bid] += q  # those shares stay out too, so they don't show up as still held
        for lot, left in ((lot[0], lot[1]) for lot in lots):
            if left <= EPS:
                continue
            p = pos_by_row[lot.row]
            if lot.id.startswith("A"):
                continue
            dec = decisions.get(f"P{lot.row}") or {}
            if dec.get("action") == "exclude" and dec.get("scope") == "leftover":
                trim[lot.id] += left
                add_item(p, "unsold_buy", f"{left:g} remaining shares left out.", "resolved", dec)
                continue
            if dec.get("action") == "sell" and (sd := _parse_sale(dec)) and sd[0] >= lot.date:
                extra.append(mk("sell", p, sd[0], left, sd[1], f"L{lot.row}", None, p.price, "sale entered on the review page"))
                add_item(p, "unsold_buy", f"Sale of the remaining {left:g} shares entered.", "resolved", dec)
                continue
            add_item(p, "unsold_buy", f"Bought {lot.shares:g} on {lot.date}, row marked Closed, but no sale in the log accounts for "
                     f"{left:g} of these shares (sold before the log started, or sold elsewhere?). Left out until you decide.")
            review[-1].data["leftover_shares"] = left
            trim[lot.id] += left

    final = []
    for t in trades + extra:
        if t.id in remove:
            continue
        if trim.get(t.id):
            left = t.shares - trim[t.id]
            if left <= EPS:
                continue
            t = Trade(**{**t.__dict__, "shares": left})
        final.append(t)
    fees = fees or {}
    for t in final:
        t.fee = float(fees.get(t.id, 0.0))
    for mt in manual or []:
        k = name_key(mt["name"]) or f"manual {mt['id']}"
        g = groups.get(k, k)
        final.append(Trade(id=f"M{mt['id']}", kind=mt["kind"], date=mt["date"], stock=group_names.get(g, mt["name"]), stock_key=g,
                           pool=f"{g}|{mt['currency']}", shares=float(mt["shares"]), price=float(mt["price"]), currency=mt["currency"],
                           scale=0.01 if mt.get("pence") else 1.0, broker=mt.get("broker") or "", row=0, fee=float(mt.get("fee") or 0.0),
                           source="app", note=mt.get("note")))
    final.sort(key=lambda t: (t.date, 0 if t.kind == "buy" else 1, t.row, t.id))

    role_counts = defaultdict(int)
    for r in pos_by_row:
        role_counts[roles.get(r, "out")] += 1
    acct = {"position_rows": len(wb.positions), "open_buys": role_counts["open_buy"], "closed_buys": role_counts["closed_buy"],
            "sales": role_counts["sale"] + role_counts["sold_in_place"], "excluded": len(excluded),
            "rows_pending": len({i.row for i in review if i.status == "pending" and i.key.startswith("P")}),
            "review_pending": sum(1 for i in review if i.status == "pending"),
            "sales_log_rows": len(wb.sales),
            "sales_log_linked": sum(1 for s in wb.sales if s.linked_rows and s.link != "typed")}
    acct["sales_log_unlinked"] = acct["sales_log_rows"] - acct["sales_log_linked"]
    acct["not_classified"] = role_counts["out"] - len(excluded)
    return Rebuild(final, review, excluded, acct, links, pos_by_row, roles)
