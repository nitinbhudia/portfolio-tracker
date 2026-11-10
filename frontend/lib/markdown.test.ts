import { describe, expect, it } from "vitest";

describe("assistant text is rendered as React elements", () => {
  it("is covered by the MiniMarkdown component (no innerHTML)", async () => {
    const src = await import("node:fs").then((fs) => fs.readFileSync("components/MiniMarkdown.tsx", "utf8"));
    expect(src.includes("dangerouslySetInnerHTML")).toBe(false);
  });
});
