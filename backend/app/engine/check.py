"""Check figures: the app's rebuilt numbers next to what your sheet recorded (SPEC.md §7.2).

Compared in each trade's own currency (the sheet adds currencies together without converting; so does
this check) and with the sheet's own matching (each sale to its own buy row), so that any difference
comes from the rebuild, not from FIFO or FX.
"""
from __future__ import annotations

from collections import defaultdict

from app.importer.live_portfolio import Workbook

from .rebuild import Rebuild, Trade

TOL = 0.01


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(TOL, 1e-6 * abs(b))


def check(wb: Workbook, rb: Rebuild) -> dict:
    buys: dict[int, Trade] = {}
    sells: dict[int, Trade] = {}
    for t in rb.trades:
        (buys if t.kind == "buy" else sells)[t.row] = t
    pending = {i.row for i in rb.review if i.status == "pending" and i.key.startswith("P")}
    excluded = set(rb.excluded_rows)

    lines, by_year = [], defaultdict(lambda: {"sheet": 0.0, "app": 0.0, "sales": 0, "matched": 0})
    for s in wb.sales:
        y = by_year[s.date.year]
        y["sales"] += 1
        y["sheet"] += s.pl or 0.0
        rows = [r for r, ls in rb.sale_links.items() if s.row in ls]
        app, causes = 0.0, []
        for r in rows:
            p = rb.position_by_row[r]
            t = sells.get(r)
            if t is not None and t.ref_price is not None:
                cost = t.shares * t.ref_price * t.scale
                app += t.value - cost
                if p.cost is not None and not _close(cost, p.cost):
                    causes.append(f"row {r}: the sheet's cost (Org val {p.cost:,.2f}) differs from shares × price ({cost:,.2f})")
                elif p.pl is not None and "pl" not in p.formulas and not _close(t.value - cost, p.pl):
                    causes.append(f"row {r}: P/L typed by hand in the sheet ({p.pl:,.2f}); sell × shares − cost = {t.value - cost:,.2f}")
            elif r in excluded:
                causes.append(f"row {r} excluded on the review page")
            elif r in pending:
                causes.append(f"row {r} is waiting on the review page")
            else:
                causes.append(f"row {r} has no sale in the app")
        if not rows:
            causes.append("typed in the sales log without a link to a position row")
        ok = _close(app, s.pl or 0.0)
        if ok:
            y["matched"] += 1
            causes = []
        y["app"] += app
        lines.append({"row": s.row, "date": s.date.isoformat(), "stock": s.stock, "sheet": s.pl, "app": app,
                      "difference": app - (s.pl or 0.0), "match": ok, "position_rows": rows,
                      "causes": causes or ([] if ok else ["P/L formula in the log doesn't equal the linked rows' P/L"])})
    years = [{"year": k, **v, "difference": v["app"] - v["sheet"]} for k, v in sorted(by_year.items())]
    tot_sheet = sum(v["sheet"] for v in by_year.values())
    tot_app = sum(v["app"] for v in by_year.values())

    # open positions per stock and currency
    groups: dict[tuple[str, str], dict] = {}
    for p in wb.positions:
        if p.status != "open":
            continue
        t = buys.get(p.row)
        key = (t.stock if t else p.name, p.currency)
        g = groups.setdefault(key, {"stock": key[0], "currency": p.currency, "rows": [], "sheet_cost": 0.0, "app_cost": 0.0,
                                    "sheet_pl": 0.0, "app_pl": 0.0, "not_imported": []})
        g["rows"].append(p.row)
        g["sheet_cost"] += p.cost or 0.0
        g["sheet_pl"] += p.pl or 0.0
        if t and t.id == f"B{p.row}":
            g["app_cost"] += t.value
            g["app_pl"] += (p.live_price or 0.0) * t.shares * t.scale - t.value
        else:
            g["not_imported"].append(p.row)
    opens = []
    for g in sorted(groups.values(), key=lambda g: g["stock"].lower()):
        g["match"] = _close(g["app_cost"], g["sheet_cost"]) and _close(g["app_pl"], g["sheet_pl"])
        opens.append(g)
    return {
        "sales_log": {"total_sheet": tot_sheet, "total_app": tot_app, "difference": tot_app - tot_sheet,
                      "lines": len(lines), "lines_matching": sum(1 for x in lines if x["match"]), "by_year": years,
                      "differences": [x for x in lines if not x["match"]]},
        "open_positions": {"stocks": len(opens), "stocks_matching": sum(1 for g in opens if g["match"]),
                           "sheet_cost": sum(g["sheet_cost"] for g in opens), "app_cost": sum(g["app_cost"] for g in opens),
                           "sheet_pl": sum(g["sheet_pl"] for g in opens), "app_pl": sum(g["app_pl"] for g in opens),
                           "rows": opens},
        "accounting": rb.accounting,
        "note": "Compared in each row's own currency, with each sale matched to its own buy row, as the sheet does. "
                "Totals add different currencies together, exactly like the sheet.",
    }
