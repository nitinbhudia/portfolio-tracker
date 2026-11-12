"""Your own groups of sales (e.g. "Alpha picks", "Trading", "Mag 7"), read from the workbook's group block on every
import (see importer._groups), with the app's FIFO gains in USD per group. Sales that no group formula includes, and
sales entered in the app, are "Not grouped" until you put them in a group here (kept across imports)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models as m

from . import portfolio as P
from .portfolio import BadRequest

SETTING = "sale_groups"  # {sale id: group name}: groups you chose in the app (they win over the sheet)
NONE = "Not grouped"


def _chosen(db: Session) -> dict[str, str]:
    row = db.get(m.Setting, SETTING)
    return dict(row.value) if row else {}


def view(db: Session) -> dict:
    st = P._need(db)
    wb = st["wb"]
    sheet_groups = wb.groups or []
    by_row: dict[int, list[str]] = {}
    for g in sheet_groups:
        for r in g["rows"]:
            by_row.setdefault(r, []).append(g["name"])
    chosen = _chosen(db)
    names = [g["name"] for g in sheet_groups] + sorted({v for v in chosen.values() if v not in {g["name"] for g in sheet_groups}})
    sales = []
    for s in st["sales"]:
        sheet = by_row.get(s.sale_row or -1, [])
        if s.id in chosen:
            grp, how = chosen[s.id], "app"
        elif sheet:
            grp, how = sheet[0], "sheet"
        else:
            grp, how = NONE, None
        sales.append({"id": s.id, "date": s.date.isoformat(), "stock": s.stock, "shares": s.shares, "sale_row": s.sale_row,
                      "gain_usd": s.gain_usd, "proceeds_usd": s.proceeds_usd, "cost_usd": s.cost_usd, "group": grp, "how": how,
                      "source": s.source})
    log_rows = {x.row for x in wb.sales}
    used_rows = {s.sale_row for s in st["sales"] if s.sale_row}
    return {
        "groups": names, "found_in_sheet": bool(sheet_groups),
        "sheet": [{"name": g["name"], "cell": f"{g['column']}{g['header_row'] + 1}", "rows": len(g["rows"]),
                   "sheet_total": g.get("sheet_total"), "unresolved": g.get("unresolved", []), "subtracted": g.get("subtracted", [])}
                  for g in sheet_groups],
        "in_two_groups": [{"row": r, "groups": gs} for r, gs in sorted(by_row.items()) if len(gs) > 1],
        "log_rows_not_grouped": sorted(r for r in log_rows & used_rows if r not in by_row),
        "sales": sales,
        "note": ("Groups and their sales are read from your workbook's group block (the row of group names under the sales log, "
                 "and the formula under each name) on every import. Gains are the app's FIFO gains in USD at each trade date's "
                 "ECB rate; the sheet's own totals are in each row's currency as the sheet adds them up (EU rows in EUR)."),
    }


def assign(db: Session, ids: list[str], group: str | None) -> dict:
    st = P._need(db)
    known = {s.id for s in st["sales"]}
    bad = [i for i in ids if i not in known]
    if not ids or bad:
        raise BadRequest(f"unknown sale(s): {', '.join(bad)}" if bad else "Choose at least one sale.")
    g = (group or "").strip()
    if len(g) > 60:
        raise BadRequest("A group name has at most 60 characters.")
    row = db.get(m.Setting, SETTING)
    cur = dict(row.value) if row else {}
    for i in ids:
        if g:
            cur[i] = g
        else:
            cur.pop(i, None)
    if row is None:
        db.add(m.Setting(key=SETTING, value=cur))
    else:
        row.value = cur
    db.commit()
    return view(db)
