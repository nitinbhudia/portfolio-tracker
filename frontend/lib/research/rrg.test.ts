import { describe as d, expect, it } from "vitest";

import type { RrgPoint } from "./api";
import { axisDomain, describe, headingDeg, lastN } from "./rrg";

d("rrg helpers", () => {
  it("axis domain is symmetric around 100 and fits all points", () => {
    const dom = axisDomain([{ ratio: 103, momentum: 99 }, { ratio: 98, momentum: 101.5 }], 2, 0);
    expect(dom.x).toEqual([97, 103]);
    expect(dom.y).toEqual([98, 102]);
    expect(axisDomain([], 2, 0).x).toEqual([98, 102]);
  });
  it("trail slicing and heading", () => {
    const t = Array.from({ length: 20 }, (_, i) => ({ date: String(i), ratio: 100, momentum: 100, quadrant: "leading" })) as RrgPoint[];
    expect(lastN(t, 5).map((p) => p.date)).toEqual(["15", "16", "17", "18", "19"]);
    expect(headingDeg({ x: 0, y: 0 }, { x: 1, y: 0 })).toBe(0);
    expect(headingDeg({ x: 0, y: 0 }, { x: 0, y: -1 })).toBe(-90);
    expect(headingDeg({ x: 1, y: 1 }, { x: 1, y: 1 })).toBeNull();
  });
  it("keeps absolute, relative and momentum readings apart", () => {
    expect(describe("down", 1.2, "improving")).toBe("falling in absolute terms, outperforming the benchmark over 20 days, relative momentum improving");
    expect(describe("up", -0.5, "weakening")).toContain("rising in absolute terms, underperforming");
  });
});
