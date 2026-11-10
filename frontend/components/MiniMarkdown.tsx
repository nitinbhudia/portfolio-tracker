"use client";

import { Fragment, type ReactNode } from "react";

/** Small, safe Markdown subset for assistant answers: paragraphs, bullet/numbered lists, tables, **bold**, `code`.
 * Builds React elements (never raw HTML), so model output can't inject markup. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    out.push(t.startsWith("**") ? <b key={m.index}>{t.slice(2, -2)}</b> : <code key={m.index} className="rounded bg-slate-100 px-1 text-xs dark:bg-slate-800">{t.slice(1, -1)}</code>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function MiniMarkdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (/^\s*\|/.test(l)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={`t${i}`} className="my-2 overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <thead><tr>{head?.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} className={/^[-+$£€(]?[\d,.]+/.test(c) ? "text-right" : ""}>{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      const ordered = /^\s*\d+\./.test(l);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        i++;
      }
      const L = ordered ? "ol" : "ul";
      blocks.push(<L key={`l${i}`} className={`my-1 ${ordered ? "list-decimal" : "list-disc"} space-y-0.5 pl-5`}>{items.map((t, k) => <li key={k}>{inline(t)}</li>)}</L>);
      continue;
    }
    if (/^\s*#{1,4}\s+/.test(l)) {
      blocks.push(<p key={`h${i}`} className="mt-2 font-semibold">{inline(l.replace(/^\s*#{1,4}\s+/, ""))}</p>);
      i++;
      continue;
    }
    if (l.trim() === "") { i++; continue; }
    // a paragraph always takes at least this line, so every pass of the outer loop moves forward
    const para: string[] = [l];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !/^\s*(\||[-*]\s|\d+\.\s|#{1,4}\s)/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(<p key={`p${i}`} className="my-1">{para.map((p, k) => <Fragment key={k}>{k > 0 && <br />}{inline(p)}</Fragment>)}</p>);
  }
  return <div className="text-sm leading-relaxed">{blocks}</div>;
}
