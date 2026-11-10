import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MiniMarkdown } from "../components/MiniMarkdown";

const ANSWER = "Selling all **36 Microsoft** shares now would realise a **gain of $2,118** (+12.1%) before tax.\n\n| | USD |\n|---|---|\n| Proceeds | $19,620 |\n| FIFO cost | $17,502 |\n| Gain | $2,118 |\n\n- Realised this year would go from $87,356 to $89,474.\n- Simulation only: nothing was sold.";

describe("MiniMarkdown", () => {
  it("renders paragraphs, tables and lists without hanging", () => {
    const html = renderToStaticMarkup(<MiniMarkdown text={ANSWER} />);
    expect(html).toContain("<b>36 Microsoft</b>");
    expect(html).toContain("<table");
    expect(html).toContain("<li>Simulation only: nothing was sold.</li>");
  }, 2000);
  it("never renders raw HTML from the text", () => {
    expect(renderToStaticMarkup(<MiniMarkdown text={"<img src=x onerror=alert(1)>"} />)).not.toContain("<img");
  });
  it("handles odd lines", () => {
    for (const t of ["  # indented heading", "* star", "1. one", "|", "   ", "**", "`x`"]) renderToStaticMarkup(<MiniMarkdown text={t} />);
  });
});
