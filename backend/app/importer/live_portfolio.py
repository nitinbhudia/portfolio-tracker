"""Read the "Live Portfolio" tab of the workbook (SPEC.md §2).

Pure parsing: no database, no guessing. The workbook is read twice: once for the values Excel saved
(cached results of formulas) and once for the formulas themselves, which tell us which position row each
sales-log line points to (e.g. ``=G818``).
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import openpyxl

TAB_NAME = "live portfolio"

# header text in row 1 (normalised) -> field name. Your sheet spells "Staus"; both are accepted.
POSITION_HEADERS = {
    "ticker": "ticker", "date": "date", "price entry": "price", "pieces": "shares", "live price": "live_price",
    "% p/l": "pl_pct", "p/l": "pl", "market val": "market_value", "staus": "status", "status": "status",
    "broker": "broker", "stock name": "name", "org val": "cost", "currency": "currency",
}
REQUIRED = ("date", "price", "shares", "live_price", "status", "name", "currency")
SALES_HEADERS = ("date", "stock")  # followed by P/L, %, P/L USD
LINK = re.compile(r"^=\$?([A-Z]{1,3})\$?(\d+)$")
ROW_REFS = re.compile(r"\$?[A-Z]{1,3}\$?(\d+)")
MAX_COL = 30


class ImportError_(ValueError):
    """The file can't be read as a Live Portfolio workbook (message is shown to the user)."""


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower() if s is not None else ""


def _num(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def _date(x) -> date | None:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return None


def _formula(x) -> str | None:
    text = getattr(x, "text", x)  # ArrayFormula objects carry .text
    return text if isinstance(text, str) and text.startswith("=") else None


@dataclass
class PositionRow:
    row: int
    date: date | None
    name: str
    shares: float | None
    price: float | None
    live_price: float | None
    live_price_is_formula: bool  # still the live-price formula, i.e. not a typed sell price
    status: str  # "open" | "closed" | other text as found
    broker: str
    currency: str
    cost: float | None  # "Org val"
    pl: float | None
    pl_pct: float | None
    market_value: float | None
    formulas: dict[str, str] = field(default_factory=dict)  # field -> formula text, for display


@dataclass
class SaleRow:
    row: int
    date: date
    stock: str
    pl: float | None
    pl_pct: float | None
    pl_usd: float | None
    linked_rows: list[int]  # position rows the P/L cell refers to
    link: str  # "single" | "sum" | "formula" | "typed"
    pl_formula: str | None


@dataclass
class Skipped:
    row: int
    reason: str
    cells: dict[str, object]


@dataclass
class Workbook:
    sha256: str
    sheet_name: str
    saved_at: str | None
    positions: list[PositionRow]
    sales: list[SaleRow]
    skipped: list[Skipped]
    position_rows: tuple[int, int]
    sales_rows: tuple[int, int] | None
    cash: list[dict] = field(default_factory=list)  # the cash block(s) as recorded: header "Orginal | Dollar"

    def to_dict(self) -> dict:
        d = asdict(self)
        return _jsonable(d)


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    return x


def _grid(ws) -> list[list]:
    return [list(r) for r in ws.iter_rows(min_row=1, max_col=MAX_COL, values_only=True)]


def _find_tab(wb) -> str:
    names = [n for n in wb.sheetnames if _norm(n) == TAB_NAME]
    if not names:
        raise ImportError_(f"No tab called 'Live Portfolio' in this workbook (tabs: {', '.join(wb.sheetnames)}).")
    return names[0]


def read(data: bytes) -> Workbook:
    try:
        wb_v = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        wb_f = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    except Exception as e:  # zip errors, encrypted files, etc.
        if data[:4] == b"\xd0\xcf\x11\xe0":
            raise ImportError_("This file is password-protected or has a sensitivity label (encrypted). "
                               "Save an unprotected copy and upload that.") from e
        raise ImportError_(f"Can't read this file as an Excel workbook (.xlsx): {e}") from e
    tab = _find_tab(wb_v)
    vals, forms = _grid(wb_v[tab]), _grid(wb_f[tab])
    saved = wb_v.properties.modified
    saved_at = saved.isoformat() if saved else None
    wb_v.close()
    wb_f.close()
    width = max((len(r) for r in vals), default=0)
    vals = [r + [None] * (width - len(r)) for r in vals]
    forms = [r + [None] * (width - len(r)) for r in forms] + [[None] * width] * (len(vals) - len(forms))

    def v(r: int, c: int):  # 1-based row, 0-based column
        return vals[r - 1][c] if r - 1 < len(vals) and c is not None and c < width else None

    def f(r: int, c: int):
        return _formula(forms[r - 1][c]) if r - 1 < len(forms) and c is not None and c < width else None

    # ---- position columns from the header row
    col: dict[str, int] = {}
    for i, h in enumerate(vals[0] if vals else []):
        key = POSITION_HEADERS.get(_norm(h))
        if key and key not in col:
            col[key] = i
    missing = [k for k in REQUIRED if k not in col]
    if missing:
        raise ImportError_(f"Row 1 of the Live Portfolio tab is missing these columns: {', '.join(missing)}.")

    # ---- sales-log header: a row with "Date", "Stock" in adjacent columns
    sales_hdr = None
    for r in range(2, len(vals) + 1):
        row = [_norm(x) for x in vals[r - 1]]
        for c in range(width - 2):
            if row[c] == "date" and row[c + 1] == "stock" and row[c + 2].startswith("p/l"):
                sales_hdr = (r, c)
                break
        if sales_hdr:
            break

    # ---- positions: from row 2 to the last row with a date + status open/closed above the sales log
    end_scan = sales_hdr[0] - 1 if sales_hdr else len(vals)
    is_pos = [False] * (end_scan + 1)
    for r in range(2, end_scan + 1):
        st = _norm(v(r, col["status"]))
        is_pos[r] = _date(v(r, col["date"])) is not None and st in ("open", "closed")
    last = max((r for r in range(2, end_scan + 1) if is_pos[r]), default=1)
    positions, skipped = [], []
    for r in range(2, last + 1):
        cells = {k: v(r, c) for k, c in col.items()}
        if not is_pos[r]:
            if any(x not in (None, "", " ") for x in cells.values()):
                why = "no buy date" if _date(cells["date"]) is None else f"status is '{cells['status']}', not Open/Closed"
                skipped.append(Skipped(r, why, _jsonable({k: x for k, x in cells.items() if x not in (None, "")})))
            continue
        fx = {k: f(r, c) for k, c in col.items() if f(r, c)}
        positions.append(PositionRow(
            row=r, date=_date(cells["date"]), name=re.sub(r"\s+", " ", str(cells["name"] or "")).strip(),
            shares=_num(cells["shares"]), price=_num(cells["price"]), live_price=_num(cells["live_price"]),
            live_price_is_formula="live_price" in fx, status=_norm(cells["status"]),
            broker=re.sub(r"\s+", " ", str(cells.get("broker") or "")).strip(),
            currency=str(cells["currency"]).strip().upper() if isinstance(cells["currency"], str) else "",
            cost=_num(cells.get("cost")), pl=_num(cells.get("pl")), pl_pct=_num(cells.get("pl_pct")),
            market_value=_num(cells.get("market_value")), formulas=fx))

    # ---- sales log: rows below the header with a date in the Date column; stops after 10 rows without one
    sales, sales_range = [], None
    if sales_hdr:
        hr, dc = sales_hdr
        sc, pc, qc, uc = dc + 1, dc + 2, dc + 3, dc + 4
        gap, r, first, lastr = 0, hr + 1, None, None
        pos_rows = {p.row for p in positions}
        while r <= len(vals) and gap < 10:
            d = _date(v(r, dc))
            if d is None:
                gap += 1
                r += 1
                continue
            gap = 0
            first, lastr = first or r, r
            pf = f(r, pc)
            if pf is None:
                linked, kind = [], "typed"
            else:
                m = LINK.match(pf)
                refs = [int(x) for x in ROW_REFS.findall(pf)]
                if m:
                    linked, kind = [int(m.group(2))], "single"
                elif re.fullmatch(r"=\$?[A-Z]{1,3}\$?\d+(\+\$?[A-Z]{1,3}\$?\d+)+", pf):
                    linked, kind = refs, "sum"
                else:
                    linked, kind = refs, "formula"
                linked = [x for x in linked if x in pos_rows] if kind != "formula" else [x for x in refs if x in pos_rows]
            sales.append(SaleRow(row=r, date=d, stock=re.sub(r"\s+", " ", str(v(r, sc) or "")).strip(),
                                 pl=_num(v(r, pc)), pl_pct=_num(v(r, qc)), pl_usd=_num(v(r, uc)),
                                 linked_rows=linked, link=kind, pl_formula=pf))
            r += 1
        if first:
            sales_range = (first, lastr)
    # ---- cash block(s): a header row with "Orginal"/"Original" | "Dollar", rows until a "Tot …" line
    cash = []
    start = (sales_range[1] if sales_range else last) + 1
    for r in range(start, len(vals) + 1):
        for c in range(width - 1):
            if _norm(v(r, c)) in ("orginal", "original") and _norm(v(r, c + 1)) == "dollar":
                block = {"header_row": r, "title": str(v(r, c - 1)).strip() if c > 0 and v(r, c - 1) not in (None, "") else None,
                         "rows": [], "totals": []}
                for rr in range(r + 1, min(r + 60, len(vals) + 1)):
                    o, u = v(rr, c), v(rr, c + 1)
                    label = v(rr, c - 1) if c > 0 else None
                    if isinstance(o, str) and _norm(o).startswith("tot"):
                        if _num(u) is not None:
                            block["totals"].append({"row": rr, "label": o.strip(), "usd": _num(u)})
                        continue
                    if _num(o) is None and _num(u) is None:
                        if block["totals"]:
                            break
                        continue
                    block["rows"].append({"row": rr, "label": None if label in (None, "", " ") else str(label).strip(),
                                          "original": _num(o), "usd": _num(u)})
                cash.append(block)
    return Workbook(sha256=hashlib.sha256(data).hexdigest(), sheet_name=tab, saved_at=saved_at, positions=positions,
                    sales=sales, skipped=skipped, position_rows=(2, last), sales_rows=sales_range, cash=cash)


def _d(x):
    return date.fromisoformat(x) if isinstance(x, str) else x


def from_dict(d: dict) -> Workbook:
    pos = [PositionRow(**{**p, "date": _d(p["date"])}) for p in d["positions"]]
    sales = [SaleRow(**{**s, "date": _d(s["date"])}) for s in d["sales"]]
    return Workbook(sha256=d["sha256"], sheet_name=d["sheet_name"], saved_at=d["saved_at"], positions=pos, sales=sales,
                    skipped=[Skipped(**s) for s in d["skipped"]], position_rows=tuple(d["position_rows"]),
                    sales_rows=tuple(d["sales_rows"]) if d["sales_rows"] else None, cash=d.get("cash", []))
