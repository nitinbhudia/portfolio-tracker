import { describe, expect, it } from "vitest";

import { buyMore, cents, defaultSteps, holding, roundTargets, sharesForBudget, sharesForTarget } from "./breakeven";

describe("break-even", () => {
  const h = holding([{ shares: 6, price: 883 }]);
  it("matches the worked example: 6 shares at 883, buying at 633.55", () => {
    expect(h.cost).toBe(5298);
    expect(h.average).toBe(883);
    const rows = [1, 3, 6, 7, 17].map((n) => buyMore(h, 633.55, n));
    expect(rows.map((r) => cents(r.extra))).toEqual([633.55, 1900.65, 3801.3, 4434.85, 10770.35]);
    // (5,298 + 633.55 × n) ÷ (6 + n). The screenshot this came from had 747.58 and 698.75 for 7 and 17: those were wrong.
    expect(rows.map((r) => cents(r.average))).toEqual([847.36, 799.85, 758.28, 748.68, 698.62]);
    expect(sharesForTarget(h, 633.55, 700)).toBe(17);
    expect(sharesForTarget(h, 633.55, 800)).toBe(3);
    expect(sharesForTarget(h, 633.55, 600)).toBeNull(); // below the buy price: impossible
    expect(sharesForTarget(h, 633.55, 900)).toBeNull(); // already below
  });
  it("several buys and fees", () => {
    const g = holding([{ shares: 10, price: 100, fee: 5 }, { shares: 10, price: 80 }, { shares: null, price: 1 }]);
    expect(g.shares).toBe(20);
    expect(g.cost).toBe(1805);
    expect(g.average).toBeCloseTo(90.25);
    const r = buyMore(g, 70, 10, 5);
    expect(r.extra).toBe(705);
    expect(r.average).toBeCloseTo(2510 / 30);
    expect(r.riseNeededPct).toBeCloseTo((2510 / 30 / 70 - 1) * 100);
    expect(sharesForTarget(g, 70, 85, 5)).toBe(Math.ceil((1805 + 5 - 85 * 20) / 15));
  });
  it("budget, default rows and round targets", () => {
    expect(sharesForBudget(10000, 633.55)).toBe(15);
    expect(sharesForBudget(100, 633.55)).toBe(0);
    expect(defaultSteps(h)).toEqual([1, 3, 6, 12]);
    expect(roundTargets(h, 633.55)).toEqual([850, 800, 750]);
    expect(roundTargets(h, 900)).toEqual([]);
    expect(holding([]).average).toBeNull();
  });
});
