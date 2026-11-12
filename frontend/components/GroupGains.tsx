"use client";

import { Fragment, useState } from "react";

import { Note, Section, Usd, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type GroupsResp, useApi } from "@/lib/api";
import { num, qty, usd } from "@/lib/format";
import { inRange, label, resolve, type Range } from "@/lib/range";

const NONE = "Not grouped";

/** Realised gains per group (your sheet's "Alpha picks / Trading / Mag 7 …" block), in the chosen time range. */
export function GroupGains({ asOf, range }: { asOf: string; range: Range }) {
  const q = useApi<GroupsResp>("/api/groups");
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const d = q.data;
  if (!d) return null;
  const win = resolve(range, asOf);
  const sales = d.sales.filter((s) => s.gain_usd !== null && inRange(s.date, win));
  const years = [...new Set(sales.map((s) => s.date.slice(0, 4)))].sort();
  const names = [...d.groups, ...(sales.some((s) => s.group === NONE) ? [NONE] : [])];
  const rows = names.map((g) => {
    const ss = sales.filter((s) => s.group === g);
    const gain = ss.reduce((a, s) => a + (s.gain_usd ?? 0), 0);
    return { g, ss, gain, won: ss.filter((s) => (s.gain_usd ?? 0) > 0).length,
      byYear: Object.fromEntries(years.map((y) => { const yy = ss.filter((s) => s.date.startsWith(y)); return [y, yy.length ? yy.reduce((a, s) => a + (s.gain_usd ?? 0), 0) : null]; })) as Record<string, number | null>,
      sheet: d.sheet.find((x) => x.name === g)?.sheet_total ?? null };
  });
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.gain)));
  const total = rows.reduce((a, r) => a + r.gain, 0);
  const move = async (ids: string[], group: string) => {
    setErr(null);
    try {
      q.setData(await apiFetch<GroupsResp>("/api/groups/assign", jsonInit("PUT", { ids, group: group || null })));
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  };
  const issues = d.in_two_groups.length + d.sheet.reduce((a, x) => a + x.unresolved.length, 0);
  return (
    <Section title={`Realised gain by group (FIFO, USD) · ${label(range)}`}>
      {!d.found_in_sheet && d.groups.length === 0 ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">No group block found in the workbook. Upload it again on Data ▾ Import: groups are read from
          the row of group names under the sales log (e.g. “Alpha picks | Trading | Mag 7”) and the formula under each name.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="tbl num w-full text-sm">
              <thead><tr><th>Group</th><th className="text-right">Sales</th><th className="text-right">Won</th><th className="w-1/4">Gain</th><th className="text-right"></th>
                {years.length > 1 && years.map((y) => <th key={y} className="text-right">{y}</th>)}
                <th className="text-right" title="The group's total as your sheet adds it up (all time; EU rows in EUR)">Sheet</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.g}>
                    <tr className={r.g === NONE ? "text-slate-500" : ""}>
                      <td><button className="text-left text-blue-700 underline dark:text-blue-300" aria-expanded={open === r.g} onClick={() => setOpen(open === r.g ? null : r.g)}>{r.g}</button></td>
                      <td className="text-right">{r.ss.length}</td>
                      <td className="text-right">{r.ss.length ? `${Math.round((r.won / r.ss.length) * 100)}%` : "—"}</td>
                      <td>
                        <span className="relative block h-3" aria-hidden>
                          <span className="absolute inset-y-0 left-1/2 w-px" style={{ background: "var(--viz-axis)" }} />
                          <span className="absolute inset-y-0" style={{ background: r.gain >= 0 ? "var(--viz-1)" : "var(--viz-neg)",
                            width: `${(Math.abs(r.gain) / max) * 50}%`, left: r.gain >= 0 ? "50%" : `${50 - (Math.abs(r.gain) / max) * 50}%`,
                            borderRadius: r.gain >= 0 ? "0 4px 4px 0" : "4px 0 0 4px" }} />
                        </span>
                      </td>
                      <td className="text-right font-medium"><Usd v={r.gain} /></td>
                      {years.length > 1 && years.map((y) => <td key={y} className="text-right">{r.byYear[y] === null ? <span className="text-slate-400">—</span> : <Usd v={r.byYear[y]} />}</td>)}
                      <td className="text-right text-slate-500">{r.sheet === null ? "—" : num(r.sheet, 0)}</td>
                    </tr>
                    {open === r.g && (
                      <tr><td colSpan={6 + (years.length > 1 ? years.length : 0)} className="bg-slate-50 dark:bg-slate-800/40">
                        <GroupSales g={r.g} ss={r.ss} names={d.groups} onMove={move} />
                      </td></tr>
                    )}
                  </Fragment>
                ))}
                <tr className="font-medium"><td>Total</td><td className="text-right">{sales.length}</td><td></td><td></td><td className="text-right"><Usd v={total} /></td>
                  {years.length > 1 && years.map((y) => <td key={y} className="text-right"><Usd v={rows.reduce((a, r) => a + (r.byYear[y] ?? 0), 0)} /></td>)}<td></td></tr>
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-500">Click a group to see its sales and move one to another group. {d.note}</p>
          {issues > 0 && (
            <Note>
              <b>In your sheet&apos;s group formulas:</b>
              <ul className="mt-1 list-disc pl-5">
                {d.in_two_groups.map((x) => <li key={x.row}>Sales-log row {x.row} is in two groups ({x.groups.join(" and ")}); counted in {x.groups[0]}.</li>)}
                {d.sheet.filter((x) => x.unresolved.length).map((x) => (
                  <li key={x.name}>{x.name} ({x.cell}) refers to {x.unresolved.join(", ")}, which {x.unresolved.length === 1 ? "isn't a row" : "aren't rows"} of the sales log (a typo for a row number like E1780?); left out.</li>
                ))}
              </ul>
            </Note>
          )}
          {err && <p className="mt-1 text-sm text-rose-700 dark:text-rose-400">{err}</p>}
        </>
      )}
    </Section>
  );
}

function GroupSales({ g, ss, names, onMove }: { g: string; ss: GroupsResp["sales"]; names: string[]; onMove: (ids: string[], group: string) => void }) {
  const [custom, setCustom] = useState("");
  const sorted = [...ss].sort((a, b) => b.date.localeCompare(a.date));
  return (
    <div className="max-h-80 overflow-auto py-1">
      <table className="w-full text-xs">
        <thead><tr className="text-left text-slate-500"><th className="py-1">Sold</th><th>Stock</th><th className="text-right">Shares</th><th className="text-right">Gain</th><th>Sheet row</th><th>Group</th></tr></thead>
        <tbody>{sorted.map((s) => (
          <tr key={s.id}>
            <td className="py-0.5 num">{s.date}</td><td>{s.stock}</td><td className="num text-right">{qty(s.shares)}</td>
            <td className="num text-right"><Usd v={s.gain_usd} /></td><td className="num">{s.sale_row ?? (s.source === "app" ? "app" : "—")}</td>
            <td>
              <select aria-label={`Group for ${s.stock} sold ${s.date}`} className={`${input} py-0 text-xs`} value={s.group === NONE ? "" : s.group}
                onChange={(e) => onMove([s.id], e.target.value)}>
                <option value="">{s.how === "app" ? "(as in the sheet)" : NONE}</option>
                {names.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              {s.how === "app" && <span className="ml-1 text-slate-500">set here</span>}
            </td>
          </tr>
        ))}</tbody>
      </table>
      {g === NONE && ss.length > 0 && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs">Or put all {ss.length} in a new group:
          <input aria-label="New group name" className={`${input} w-36 text-xs`} value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="name" />
          <button className="underline" disabled={!custom.trim()} onClick={() => onMove(ss.map((s) => s.id), custom.trim())}>apply</button>
          <span className="text-slate-500">({usd(ss.reduce((a, s) => a + (s.gain_usd ?? 0), 0))})</span></p>
      )}
    </div>
  );
}
