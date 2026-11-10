"use client";

import { createContext, useContext, useEffect, useState } from "react";

import { PRESETS, type Range } from "@/lib/range";

const Ctx = createContext<{ range: Range; setRange: (r: Range) => void }>({ range: { key: "ALL" }, setRange: () => {} });
export const useRange = () => useContext(Ctx);

/** One time range shared by every chart (remembered on this computer). */
export function RangeProvider({ children }: { children: React.ReactNode }) {
  const [range, set] = useState<Range>({ key: "ALL" });
  useEffect(() => {
    try {
      const saved = localStorage.getItem("pt-range");
      if (saved) set(JSON.parse(saved));
    } catch {
      /* ignore */
    }
  }, []);
  const setRange = (r: Range) => {
    set(r);
    try {
      localStorage.setItem("pt-range", JSON.stringify(r));
    } catch {
      /* ignore */
    }
  };
  return <Ctx.Provider value={{ range, setRange }}>{children}</Ctx.Provider>;
}

export function RangePicker() {
  const { range, setRange } = useRange();
  const [from, setFrom] = useState(range.from ?? "");
  const [to, setTo] = useState(range.to ?? "");
  const cls = (on: boolean) => `px-2.5 py-1 text-xs ${on ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`;
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Time range for the charts">
      <div role="group" className="inline-flex overflow-hidden rounded border border-slate-300 dark:border-slate-700">
        {PRESETS.map((k) => (
          <button key={k} aria-pressed={range.key === k} className={cls(range.key === k)} onClick={() => setRange({ key: k })}>{k === "ALL" ? "All" : k}</button>
        ))}
      </div>
      <span className="flex items-center gap-1 text-xs">
        <input aria-label="From date" type="date" className="rounded border border-slate-300 bg-transparent px-1 py-0.5 dark:border-slate-700" value={from} onChange={(e) => setFrom(e.target.value)} />
        <span>→</span>
        <input aria-label="To date" type="date" className="rounded border border-slate-300 bg-transparent px-1 py-0.5 dark:border-slate-700" value={to} onChange={(e) => setTo(e.target.value)} />
        <button className={`rounded border border-slate-300 dark:border-slate-700 ${cls(range.key === "CUSTOM")}`} disabled={!from && !to}
          onClick={() => setRange({ key: "CUSTOM", from: from || undefined, to: to || undefined })}>Apply</button>
      </span>
    </div>
  );
}
