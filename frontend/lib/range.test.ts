import { describe, expect, it } from "vitest";

import { inRange, label, resolve, spanMonths } from "./range";

describe("resolve", () => {
  it("counts back from the end date", () => {
    expect(resolve({ key: "1M" }, "2026-03-31")).toEqual({ start: "2026-02-28", end: "2026-03-31" });
    expect(resolve({ key: "1Y" }, "2026-11-06").start).toBe("2025-11-06");
    expect(resolve({ key: "YTD" }, "2026-11-06").start).toBe("2026-01-01");
    expect(resolve({ key: "ALL" }, "2026-11-06")).toEqual({ start: null, end: "2026-11-06" });
    expect(resolve({ key: "CUSTOM", from: "2024-01-01", to: "2024-06-30" }, "2026-11-06")).toEqual({ start: "2024-01-01", end: "2024-06-30" });
  });
  it("filters and labels", () => {
    const r = { start: "2024-01-01", end: "2024-12-31" };
    expect(inRange("2024-05-05", r)).toBe(true);
    expect(inRange("2025-01-01", r)).toBe(false);
    expect(spanMonths("2024-01-01", "2024-12-31")).toBe(12);
    expect(label({ key: "3M" })).toBe("last 3 months");
    expect(label({ key: "1Y" })).toBe("last 1 year");
  });
});
