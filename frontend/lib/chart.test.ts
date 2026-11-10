import { describe, expect, it } from "vitest";

import { axisLabel, niceTicks } from "./chart";

describe("niceTicks", () => {
  it("covers the range with round steps and includes 0", () => {
    expect(niceTicks(0, 182630)).toEqual([0, 50000, 100000, 150000, 200000]);
    const t = niceTicks(-1500, 4200);
    expect(t[0]).toBeLessThanOrEqual(-1500);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(4200);
    expect(t).toContain(0);
  });
  it("handles an empty range", () => expect(niceTicks(0, 0)).toEqual([0]));
});

describe("axisLabel", () => {
  it("is in full under 10k and compact above", () => {
    expect(axisLabel(2000, false)).toBe("2,000");
    expect(axisLabel(150000, true)).toBe("150K");
  });
});
