import { describe, expect, it } from "vitest";

import { applyFilters, type ColumnSpec, distinctValues, sortRows, toCsv, toggleSort } from "./table";

type R = { t: string; n: number | null; c: string | null; b: boolean | null; d: string };
const rows: R[] = [
  { t: "AAPL", n: 10, c: "bullish", b: true, d: "2026-01-02" },
  { t: "MSFT", n: null, c: "bearish", b: false, d: "2026-03-01" },
  { t: "nvda", n: -5, c: null, b: null, d: "2025-12-31" },
  { t: "ASML", n: 10, c: "neutral", b: true, d: "2026-02-01" },
];
const cols: ColumnSpec<R>[] = [
  { key: "t", label: "Ticker", type: "text", get: (r) => r.t },
  { key: "n", label: "Score", type: "number", get: (r) => r.n },
  { key: "c", label: "Class", type: "enum", get: (r) => r.c, labels: { bullish: "Bullish" } },
  { key: "b", label: "Held", type: "bool", get: (r) => r.b },
  { key: "d", label: "Date", type: "date", get: (r) => r.d },
];
const tickers = (rs: R[]) => rs.map((r) => r.t);

describe("filters", () => {
  it("text contains, case-insensitive", () => {
    expect(tickers(applyFilters(rows, cols, { t: { kind: "text", contains: "a" } }))).toEqual(["AAPL", "nvda", "ASML"]);
  });
  it("number range excludes missing", () => {
    expect(tickers(applyFilters(rows, cols, { n: { kind: "number", min: 0 } }))).toEqual(["AAPL", "ASML"]);
    expect(tickers(applyFilters(rows, cols, { n: { kind: "number", min: -5, max: -5 } }))).toEqual(["nvda"]);
  });
  it("enum including missing marker", () => {
    expect(tickers(applyFilters(rows, cols, { c: { kind: "enum", in: ["bullish", "—"] } }))).toEqual(["AAPL", "nvda"]);
  });
  it("bool and date", () => {
    expect(tickers(applyFilters(rows, cols, { b: { kind: "bool", is: false } }))).toEqual(["MSFT"]);
    expect(tickers(applyFilters(rows, cols, { d: { kind: "date", from: "2026-01-01", to: "2026-02-15" } }))).toEqual(["AAPL", "ASML"]);
  });
  it("combined filters are AND; global search uses labels", () => {
    expect(tickers(applyFilters(rows, cols, { n: { kind: "number", min: 0 }, b: { kind: "bool", is: true } }, "bull"))).toEqual(["AAPL"]);
  });
  it("inactive filters are ignored", () => {
    expect(applyFilters(rows, cols, { t: { kind: "text", contains: " " }, c: { kind: "enum", in: [] } })).toHaveLength(4);
  });
});

describe("sorting", () => {
  it("numbers with nulls last in both directions, stable ties", () => {
    expect(tickers(sortRows(rows, cols, [{ key: "n", dir: "asc" }]))).toEqual(["nvda", "AAPL", "ASML", "MSFT"]);
    expect(tickers(sortRows(rows, cols, [{ key: "n", dir: "desc" }]))).toEqual(["AAPL", "ASML", "nvda", "MSFT"]);
  });
  it("multi-sort tie-breaks", () => {
    expect(tickers(sortRows(rows, cols, [{ key: "n", dir: "desc" }, { key: "t", dir: "desc" }]))).toEqual(["ASML", "AAPL", "nvda", "MSFT"]);
  });
  it("text is case-insensitive", () => {
    expect(tickers(sortRows(rows, cols, [{ key: "t", dir: "asc" }]))).toEqual(["AAPL", "ASML", "MSFT", "nvda"]);
  });
  it("toggle cycles asc -> desc -> off; shift adds", () => {
    let s = toggleSort([], "n", false);
    expect(s).toEqual([{ key: "n", dir: "asc" }]);
    s = toggleSort(s, "n", false);
    expect(s).toEqual([{ key: "n", dir: "desc" }]);
    expect(toggleSort(s, "n", false)).toEqual([]);
    expect(toggleSort(s, "t", true)).toEqual([{ key: "n", dir: "desc" }, { key: "t", dir: "asc" }]);
    expect(toggleSort(s, "t", false)).toEqual([{ key: "t", dir: "asc" }]);
    expect(toggleSort([], "n", false, "desc")).toEqual([{ key: "n", dir: "desc" }]);
  });
});

describe("helpers", () => {
  it("distinct values put missing last", () => {
    expect(distinctValues(rows, cols[2])).toEqual(["bearish", "bullish", "neutral", "—"]);
  });
  it("csv escapes and guards formulas", () => {
    const csv = toCsv([{ t: '=HYPERLINK("x")', n: -1, c: "a,b", b: null, d: "2026" }], cols);
    expect(csv.split("\n")[1]).toBe(`"'=HYPERLINK(""x"")",-1,"a,b",,2026`);
  });
});

import { moveBefore, resolveOrder, shift } from "./table";

describe("column order", () => {
  it("resolves saved order and inserts new columns near their default neighbours", () => {
    expect(resolveOrder(["a", "b", "c"], undefined)).toEqual(["a", "b", "c"]);
    expect(resolveOrder(["a", "b", "c"], ["c", "a", "b"])).toEqual(["c", "a", "b"]);
    expect(resolveOrder(["a", "b", "x", "c"], ["c", "a", "b", "gone"])).toEqual(["c", "a", "b", "x"]);
    expect(resolveOrder(["new", "a", "b"], ["b", "a"])).toEqual(["new", "b", "a"]);
  });
  it("drag moves a column to the target position (both directions)", () => {
    expect(moveBefore(["a", "b", "c", "d"], "a", "c")).toEqual(["b", "c", "a", "d"]);
    expect(moveBefore(["a", "b", "c", "d"], "d", "b")).toEqual(["a", "d", "b", "c"]);
    expect(moveBefore(["a", "b"], "a", "a")).toEqual(["a", "b"]);
  });
  it("shift left/right with bounds", () => {
    expect(shift(["a", "b", "c"], "b", -1)).toEqual(["b", "a", "c"]);
    expect(shift(["a", "b", "c"], "c", 1)).toEqual(["a", "b", "c"]);
  });
});
