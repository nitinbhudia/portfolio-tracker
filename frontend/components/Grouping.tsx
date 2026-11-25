"use client";

import { useEffect, useState } from "react";

import { input } from "@/components/ui";
import { apiFetch, jsonInit } from "@/lib/api";

/** ☆/★ for a stock: starred stocks are the ones most interesting to you (filter and group by it). */
export function Star({ starKey, on, label, onChange }: { starKey: string; on: boolean; label: string; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" disabled={busy} aria-pressed={on} aria-label={on ? `Unstar ${label}` : `Star ${label}`} title={on ? "Starred: one of your most interesting stocks" : "Star this stock"}
      className={`text-base leading-none ${on ? "text-amber-500" : "text-slate-300 hover:text-amber-500 dark:text-slate-600"}`}
      onClick={async () => { setBusy(true); try { await apiFetch("/api/journal/star", jsonInit("PUT", { key: starKey, starred: !on })); onChange(); } finally { setBusy(false); } }}>
      {on ? "★" : "☆"}</button>
  );
}

export type GroupOpt<T> = { key: string; label: string; of: (row: T) => string[]; order?: "count" | "name" | "desc" };

/** The chosen grouping, remembered in this browser. */
export function useGrouping(id: string, def = "none") {
  const [g, setG] = useState(def);
  const [starred, setStarred] = useState(false);
  useEffect(() => {
    try {
      const v = JSON.parse(localStorage.getItem(`pt-group:${id}`) || "null");
      if (v) { setG(v.g ?? def); setStarred(!!v.starred); }
    } catch { /* ignore */ }
  }, [id, def]);
  const save = (next: { g?: string; starred?: boolean }) => {
    const v = { g: next.g ?? g, starred: next.starred ?? starred };
    setG(v.g);
    setStarred(v.starred);
    try { localStorage.setItem(`pt-group:${id}`, JSON.stringify(v)); } catch { /* ignore */ }
  };
  return { group: g, starredOnly: starred, setGroup: (x: string) => save({ g: x }), setStarredOnly: (x: boolean) => save({ starred: x }) };
}

export function GroupControls<T>({ opts, group, setGroup, starredOnly, setStarredOnly, extra }: {
  opts: GroupOpt<T>[]; group: string; setGroup: (g: string) => void; starredOnly: boolean; setStarredOnly: (v: boolean) => void; extra?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
      <button type="button" aria-pressed={starredOnly} onClick={() => setStarredOnly(!starredOnly)}
        className={`rounded border px-2.5 py-1 ${starredOnly ? "border-amber-500 bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200" : "border-slate-300 dark:border-slate-700"}`}>
        <span className="text-amber-500">★</span> Starred only</button>
      <label className="flex items-center gap-1.5">Group by
        <select aria-label="Group by" className={input} value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="none">nothing</option>
          {opts.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select></label>
      {extra}
    </div>
  );
}

/** Rows split into groups (a row can sit in several, e.g. two buy reasons). */
export function groupRows<T>(rows: T[], opt: GroupOpt<T>): { name: string; rows: T[] }[] {
  const m = new Map<string, T[]>();
  for (const r of rows) for (const k of opt.of(r)) m.set(k, [...(m.get(k) ?? []), r]);
  const out = [...m.entries()].map(([name, rs]) => ({ name, rows: rs }));
  const last = (n: string) => (n.startsWith("(") || n.startsWith("No ") || n === "Not grouped" ? 1 : 0);
  return out.sort((a, b) => last(a.name) - last(b.name) || (opt.order === "name" ? a.name.localeCompare(b.name)
    : opt.order === "desc" ? b.name.localeCompare(a.name) : b.rows.length - a.rows.length || a.name.localeCompare(b.name)));
}
