"""Your sale groups: read from the group block under the sales log on import, FIFO gains per group, app assignments.

Made-up book: Alpha bought 10 @ 100 (row 2) and sold @ 120 (row 3, sales log row 21: +200); Beta plc 200 @ 250p
(row 5) sold @ 300p (row 6, log row 22). Group block: row 27 names, row 28 formulas; EU points at another block cell.
"""
from datetime import date as D

from app.importer import live_portfolio as L

from .fixture_book import F, make, position, sale
from .test_api import client  # noqa: F401  (fixture re-used)


def grouped_book():
    pos = {
        2: position(2, D(2024, 1, 10), "Alpha Corp", 10, 100, 100, "Closed", cost=0, pl=0),
        3: position(3, D(2024, 6, 1), "Alpha Corp", 10, 100, 120, "Closed"),
        5: position(5, D(2024, 3, 1), "Beta plc", 200, 250, 250, "Closed", cur="GBP", pence=True, cost=0, pl=0),
        6: position(6, D(2024, 6, 3), "Beta plc", 200, 250, 300, "Closed", cur="GBP", pence=True),
    }
    rows = {
        21: sale(21, D(2024, 6, 1), "Alpha", 3, 200.0, 0.2),
        22: sale(22, D(2024, 6, 3), "Beta", 6, 100.0, 0.2),
        27: {"D": "Tot", "G": "Alpha picks ", "H": "Trading", "I": "EU"},
        28: {"G": F("G21+E22", 300), "H": F("E5+SUM(E21:E21)", 200), "I": F("E29", 100)},
        29: {"E": F("E22", 100)},
    }
    return make(pos, 20, rows)


def test_reads_the_group_block():
    w = L.read(grouped_book())
    g = {x["name"]: x for x in w.groups}
    assert list(g) == ["Alpha picks", "Trading", "EU"]
    assert g["Alpha picks"]["rows"] == [21, 22] and g["Alpha picks"]["sheet_total"] == 300 and g["Alpha picks"]["column"] == "G"
    assert g["Trading"]["rows"] == [21] and g["Trading"]["unresolved"] == ["E5"]  # a position-area cell, not the sales log
    assert g["EU"]["rows"] == [22]  # followed =E29 to the sales-log row
    assert L.from_dict(w.to_dict()).groups == w.groups


def test_no_group_block_is_fine():
    from .test_engine import book
    assert L.read(book()).groups == []


def test_gains_per_group_and_app_assignments(client):  # noqa: F811
    r = client.post("/api/import", files={"file": ("g.xlsx", grouped_book(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    v = client.get("/api/groups").json()
    assert v["groups"] == ["Alpha picks", "Trading", "EU"] and v["found_in_sheet"]
    s = {x["id"]: x for x in v["sales"]}
    assert s["S3"]["group"] == "Alpha picks" and s["S3"]["how"] == "sheet" and s["S3"]["gain_usd"] == 200
    assert s["S6"]["group"] == "Alpha picks"  # in two groups in the sheet: the first one counts, and it's reported
    assert {x["row"] for x in v["in_two_groups"]} == {21, 22}
    assert next(x for x in v["sheet"] if x["name"] == "Trading")["unresolved"] == ["E5"]
    v = client.put("/api/groups/assign", json={"ids": ["S6"], "group": "EU"}).json()
    s = {x["id"]: x for x in v["sales"]}
    assert s["S6"]["group"] == "EU" and s["S6"]["how"] == "app"
    v = client.put("/api/groups/assign", json={"ids": ["S6"], "group": None}).json()
    assert {x["id"]: x for x in v["sales"]}["S6"]["how"] == "sheet"
    assert client.put("/api/groups/assign", json={"ids": ["S99"], "group": "EU"}).status_code == 400
    # a new upload with the same block keeps working; app choices survive re-imports
    client.put("/api/groups/assign", json={"ids": ["S3"], "group": "Long term"})
    client.post("/api/import", files={"file": ("g.xlsx", grouped_book(), "application/octet-stream")})
    v = client.get("/api/groups").json()
    assert "Long term" in v["groups"] and {x["id"]: x for x in v["sales"]}["S3"]["group"] == "Long term"
