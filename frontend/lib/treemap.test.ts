import { describe, expect, it } from "vitest";

import { gainFill, squarify } from "./treemap";

describe("squarify", () => {
  it("areas are proportional, inside the box, and don't overlap", () => {
    const vals = [6, 6, 4, 3, 2, 2, 1];
    const box = { x: 0, y: 0, w: 600, h: 400 };
    const rs = squarify(vals, box);
    const total = vals.reduce((a, b) => a + b, 0);
    rs.forEach((r, i) => {
      expect(r.w * r.h).toBeCloseTo((vals[i] / total) * 600 * 400, 3);
      expect(r.x).toBeGreaterThanOrEqual(-1e-9);
      expect(r.x + r.w).toBeLessThanOrEqual(600 + 1e-6);
      expect(r.y + r.h).toBeLessThanOrEqual(400 + 1e-6);
    });
    for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
      const a = rs[i], b = rs[j];
      const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      expect(ox > 1e-6 && oy > 1e-6).toBe(false);
    }
  });
  it("keeps input order and handles one or no items", () => {
    expect(squarify([1, 9], { x: 0, y: 0, w: 100, h: 100 })[1].w * 100).toBeGreaterThan(0);
    expect(squarify([5], { x: 10, y: 20, w: 50, h: 30 })[0]).toEqual({ x: 10, y: 20, w: 50, h: 30 });
    expect(squarify([], { x: 0, y: 0, w: 10, h: 10 })).toEqual([]);
  });
});

describe("gainFill", () => {
  it("uses the diverging poles and a grey midpoint", () => {
    expect(gainFill(null).fill).toBe("var(--viz-mid)");
    expect(gainFill(25).fill).toContain("--viz-1");
    expect(gainFill(-80)).toEqual({ fill: "color-mix(in oklab, var(--viz-neg) 85%, var(--viz-mid))", strong: true });
  });
});
