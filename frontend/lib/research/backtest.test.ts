import { describe, expect, it } from "vitest";

import type { BtSegment } from "./api";
import { chainSegments } from "./backtest";

const seg = (dates: string[], s: number[], b: number[]) => ({ curve: { dates, strategy: s, buy_hold: b } }) as unknown as BtSegment;

describe("chainSegments", () => {
  it("continues the holdout from the end of the main period, for display", () => {
    const c = chainSegments(seg(["a", "b"], [1, 1.2], [1, 0.9]), seg(["c", "d"], [1.1, 1.0], [1.0, 1.5]));
    expect(c.dates).toEqual(["a", "b", "c", "d"]);
    expect(c.strategy).toEqual([1, 1.2, 1.2 * 1.1, 1.2]);
    expect(c.buyHold[3]).toBeCloseTo(0.9 * 1.5);
    expect(c.holdoutStart).toBe("c");
    expect(c.equalWeight).toBeNull();
  });
  it("chains the equal-weight line when present (rotation backtests)", () => {
    const m = { curve: { dates: ["a"], strategy: [1], buy_hold: [1], equal_weight: [1.5] } } as unknown as BtSegment;
    const h = { curve: { dates: ["b"], strategy: [1], buy_hold: [1], equal_weight: [0.8] } } as unknown as BtSegment;
    const ew = chainSegments(m, h).equalWeight!;
    expect(ew[0]).toBe(1.5);
    expect(ew[1]).toBeCloseTo(1.2);
  });
});
