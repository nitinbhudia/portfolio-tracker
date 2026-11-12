"use client";

import type { SetupCatalogItem, Setups } from "@/lib/research/api";
import { fmtOperand, STATUS_LABEL } from "@/lib/research/setups";

const DIR = {
  bullish: "bg-emerald-100 text-emerald-800 ring-emerald-300 dark:bg-emerald-900/50 dark:text-emerald-200 dark:ring-emerald-800",
  bearish: "bg-rose-100 text-rose-800 ring-rose-300 dark:bg-rose-900/50 dark:text-rose-200 dark:ring-rose-800",
};

/** Compact chips for the triggered setups of one row. */
export function SetupChips({ triggered, catalog }: { triggered: string[]; catalog: SetupCatalogItem[] }) {
  const items = catalog.filter((c) => triggered.includes(c.id));
  if (!items.length) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {items.map((c) => (
        <span key={c.id} className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] ring-1 ${DIR[c.direction]}`} title={`${c.name} (${c.direction})`}>
          {c.direction === "bullish" ? "▲" : "▼"} {c.name}
        </span>
      ))}
    </span>
  );
}

const STATUS_CLS: Record<string, string> = {
  triggered: "font-semibold text-slate-900 dark:text-slate-100",
  not_triggered: "text-slate-500",
  insufficient_data: "text-amber-600",
  not_applicable: "text-slate-400",
};

/** Every detector with every rule, its inputs and outcome. */
export function SetupBreakdown({ setups }: { setups: Setups }) {
  const sorted = [...setups.setups].sort((a, b) => Number(b.status === "triggered") - Number(a.status === "triggered"));
  return (
    <div className="space-y-2">
      <div className="grid gap-2 md:grid-cols-2">
        {sorted.map((s) => (
          <details key={s.id} className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800" open={s.status === "triggered"}>
            <summary className="flex cursor-pointer flex-wrap items-center gap-2">
              <span className={s.direction === "bullish" ? "text-emerald-600" : "text-rose-600"}>{s.direction === "bullish" ? "▲" : "▼"}</span>
              <span className="font-medium">{s.name}</span>
              <span className={`ml-auto ${STATUS_CLS[s.status]}`}>{STATUS_LABEL[s.status]}</span>
            </summary>
            {s.rules.length === 0 ? (
              <p className="mt-1 text-slate-500">{s.reason}</p>
            ) : (
              <div className="mt-1 overflow-x-auto">
                <table className="tbl num w-full">
                  <thead>
                    <tr><th>Rule</th><th className="text-right">Value</th><th className="text-right">Threshold</th><th className="text-center">Met</th></tr>
                  </thead>
                  <tbody>
                    {s.rules.map((r, i) => (
                      <tr key={i}>
                        <td>{r.rule}{r.note ? <span className="text-slate-500"> ({r.note})</span> : null}</td>
                        <td className="text-right">{r.value ?? fmtOperand(r.left)}</td>
                        <td className="text-right">{fmtOperand(r.right)}</td>
                        <td className={`text-center ${r.result ? "text-emerald-600" : "text-rose-600"}`}>{r.result ? "✓" : "✗"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </details>
        ))}
      </div>
      <p className="text-xs text-slate-500">
        Rule set {setups.version} · params {setups.params_hash.slice(0, 10)} · input {setups.input_hash.slice(0, 10)}. A triggered setup is a
        condition to research, not a buy or sell signal. All rules must be met for a setup to trigger.
      </p>
    </div>
  );
}
