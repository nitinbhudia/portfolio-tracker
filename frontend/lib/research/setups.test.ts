import { describe, expect, it } from "vitest";

import type { SetupCatalogItem, SetupItem } from "./api";
import { countBySetup, failedRules, fmtOperand, triggeredNames } from "./setups";

const catalog: SetupCatalogItem[] = [
  { id: "breakout", name: "Potential breakout", direction: "bullish", needs_volume: true },
  { id: "breakdown", name: "Potential breakdown", direction: "bearish", needs_volume: true },
  { id: "bullish_ma", name: "Bullish MA alignment", direction: "bullish", needs_volume: false },
];

describe("setups helpers", () => {
  it("joins triggered names in catalog order", () => {
    expect(triggeredNames(["bullish_ma", "breakout"], catalog)).toBe("Potential breakout · Bullish MA alignment");
    expect(triggeredNames([], catalog)).toBe("");
  });

  it("no setup name contains another (text filters stay unambiguous)", () => {
    for (const a of catalog) for (const b of catalog) if (a !== b) expect(a.name.includes(b.name)).toBe(false);
  });

  it("counts rows per setup", () => {
    expect(countBySetup([{ triggered: ["breakout"] }, { triggered: ["breakout", "bullish_ma"] }, { triggered: [] }])).toEqual({
      breakout: 2,
      bullish_ma: 1,
    });
  });

  it("lists failed rules", () => {
    const s: SetupItem = {
      id: "breakout", name: "Potential breakout", direction: "bullish", status: "not_triggered",
      rules: [{ rule: "a", left: 1, right: 0, result: true }, { rule: "b", left: 1.1, right: 1.5, result: false }],
    };
    expect(failedRules(s).map((r) => r.rule)).toEqual(["b"]);
  });

  it("formats operands", () => {
    expect(fmtOperand(null)).toBe("—");
    expect(fmtOperand(1234567.8)).toBe("1,234,568");
    expect(fmtOperand(0.123456)).toBe("0.1235");
    expect(fmtOperand(104.7215)).toBe("104.7");
  });
});
