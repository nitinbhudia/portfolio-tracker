import { describe, expect, it } from "vitest";

import { rangeFrom } from "./range";

const days = (n: number, step: number) =>
  Array.from({ length: n }, (_, i) => new Date(Date.UTC(2024, 0, 1) + i * step * 86400000).toISOString().slice(0, 10));

describe("chart ranges use calendar time", () => {
  it("1Y covers about a year of daily bars and of weekly bars", () => {
    const d = days(730, 1);
    expect(d.length - rangeFrom(d, "1Y")).toBeGreaterThanOrEqual(364);
    expect(d.length - rangeFrom(d, "1Y")).toBeLessThanOrEqual(366);
    const w = days(150, 7);
    expect([52, 53]).toContain(w.length - rangeFrom(w, "1Y"));
  });
  it("All starts at zero and short histories keep a few bars", () => {
    const w = days(10, 30);
    expect(rangeFrom(w, "All")).toBe(0);
    expect(w.length - rangeFrom(w, "1M")).toBeGreaterThanOrEqual(3);
  });
});
