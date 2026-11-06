"""Build made-up workbooks with the Live Portfolio layout, including formulas WITH their saved values.

openpyxl writes formulas without cached results, so after saving we add the <v> value to each formula cell
(what Excel does when it saves). No real data anywhere in the tests.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

import openpyxl

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
HEADER = ["Ticker", "Date", "Price Entry", "pieces", "Live Price", "% P/L", "P/L", "Market val", "Staus", "Broker",
          "Daily  %", "Stock Name", "Volume", "Days", "Org val", "Currency"]


class F:
    """A formula with the value Excel would have saved."""

    def __init__(self, formula: str, value):
        self.formula, self.value = formula, value


def position(r: int, d: date, name: str, shares: float, price: float, live: float, status: str, cur: str = "USD",
             broker: str = "IBKR 24", live_formula: bool = False, pence: bool = False, cost=None, pl=None) -> dict:
    s = 0.01 if pence else 1.0
    c = shares * price * s if cost is None else cost
    p = live * shares * s - c if pl is None else pl
    return {"A": "#VALUE!", "B": d, "C": price, "D": shares,
            "E": F(f'_FV(A{r},"Price")', live) if live_formula else live,
            "F": F(f"G{r}/O{r}", p / c if c else 0), "G": F(f"((E{r}*D{r})-O{r})", p) if pl is None else pl,
            "H": live * shares * s, "I": status, "J": broker, "L": name,
            "O": F(f"D{r}*C{r}" + ("/100" if pence else ""), c) if cost is None else cost, "P": cur}


def make(positions: dict[int, dict], sales_header_row: int, sales: dict[int, dict], tab: str = "Live Portfolio ",
         extra_tabs=("Goal",)) -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = extra_tabs[0] if extra_tabs else tab
    for t in extra_tabs[1:]:
        wb.create_sheet(t)
    ws = wb.create_sheet(tab) if extra_tabs else wb.active
    wb[wb.sheetnames[0]]["A1"] = "ignore me"
    for i, h in enumerate(HEADER, 1):
        ws.cell(1, i, h)
    cached: dict[str, object] = {}
    for r, cells in {**positions, **sales}.items():
        for col, v in cells.items():
            ref = f"{col}{r}"
            if isinstance(v, F):
                ws[ref] = "=" + v.formula
                cached[ref] = v.value
            else:
                ws[ref] = v
    for i, h in enumerate(["Date", "Stock", "P/L orginal", "p/l %", "PL USD"]):
        ws.cell(sales_header_row, 3 + i, h)
    buf = io.BytesIO()
    wb.save(buf)
    return _inject(buf.getvalue(), wb.sheetnames.index(tab) + 1, cached)


def sale(r: int, d: date, stock: str, link_row: int | None, pl: float, pct: float = 0.0, typed: bool = False,
         formula: str | None = None) -> dict:
    if typed or link_row is None and formula is None:
        return {"C": d, "D": stock, "E": pl, "F": pct, "G": pl}
    f = formula or f"G{link_row}"
    return {"C": d, "D": stock, "E": F(f, pl), "F": F(f"F{link_row}", pct) if link_row else pct, "G": F(f"E{r}", pl)}


def _inject(data: bytes, sheet_no: int, cached: dict[str, object]) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    name = f"xl/worksheets/sheet{sheet_no}.xml"
    ET.register_namespace("", NS)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            raw = zin.read(item.filename)
            if item.filename == name:
                root = ET.fromstring(raw)
                for c in root.iter(f"{{{NS}}}c"):
                    ref = c.get("r")
                    if ref in cached and c.find(f"{{{NS}}}f") is not None:
                        for v in c.findall(f"{{{NS}}}v"):
                            c.remove(v)
                        val = cached[ref]
                        v = ET.SubElement(c, f"{{{NS}}}v")
                        if isinstance(val, str):
                            c.set("t", "str" if not val.startswith("#") else "e")
                            v.text = val
                        else:
                            c.attrib.pop("t", None)
                            v.text = repr(float(val))
                raw = ET.tostring(root, xml_declaration=True, encoding="UTF-8")
                raw = re.sub(rb"ns0:", b"", raw)
            zout.writestr(item, raw)
    return out.getvalue()
