import { describe, expect, it } from "vitest";

import { gainBars } from "./periods";

const months = [{ month: "2024-01", sales: 2, gain_usd: 100, wins: 2 }, { month: "2025-03", sales: 1, gain_usd: -50, wins: 0 }, { month: "2026-10", sales: 3, gain_usd: 70, wins: 2 }];

describe("gainBars", () => {
  it("uses years for long ranges", () => {
    const r = gainBars(months, { key: "ALL" }, "2026-11-06");
    expect(r.monthly).toBe(false);
    expect(r.bars.map((b) => [b.key, b.value])).toEqual([["2024", 100], ["2025", -50], ["2026", 70]]);
  });
  it("uses every month for short ranges, empty months included", () => {
    const r = gainBars(months, { key: "3M" }, "2026-11-06");
    expect(r.monthly).toBe(true);
    expect(r.bars.map((b) => [b.key, b.value])).toEqual([["2026-08", 0], ["2026-09", 0], ["2026-10", 70], ["2026-11", 0]]);
  });
});
