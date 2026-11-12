"use client";

import { useState } from "react";

import type { Horizon, Score } from "@/lib/research/api";
import { num } from "@/lib/research/format";

import { ClassBadge } from "./ui";

const LABEL: Record<Horizon, string> = { short: "Short-term", medium: "Medium-term", long: "Long-term" };

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Math.abs(v) >= 1000 ? num(v, 1) : num(v, 4);
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

function ScoreCard({ s }: { s: Score }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">{LABEL[s.horizon]}</div>
        <ClassBadge c={s.classification} />
      </div>
      {s.status !== "ok" ? (
        <div className="mt-2 text-sm text-amber-600">Insufficient data: more than half the score weight has missing inputs.</div>
      ) : (
        <>
          <div className="num mt-1 text-3xl font-semibold">{num(s.total, 1)}<span className="text-sm text-slate-500"> / 100</span></div>
          <div className="mt-2 h-1.5 w-full rounded bg-slate-200 dark:bg-slate-700">
            <div className="h-1.5 rounded bg-slate-700 dark:bg-slate-300" style={{ width: `${s.total}%` }} />
          </div>
        </>
      )}
      {s.excluded_components.length > 0 && (
        <div className="mt-2 text-xs text-amber-600">Excluded (missing inputs): {s.excluded_components.join(", ")}. Remaining weights renormalised.</div>
      )}
      <button onClick={() => setOpen(!open)} className="mt-2 text-xs text-blue-600 underline dark:text-blue-400" aria-expanded={open}>
        {open ? "Hide" : "How was this calculated?"}
      </button>
      {open && (
        <div className="mt-2 space-y-2 text-xs">
          <table className="tbl num w-full">
            <thead>
              <tr><th>Component</th><th className="text-right">Points</th><th className="text-right">Weight</th><th className="text-right">Eff. weight</th><th className="text-right">Contribution</th></tr>
            </thead>
            <tbody>
              {Object.entries(s.weights).map(([k, w]) => {
                const c = s.components[k];
                return (
                  <tr key={k}>
                    <td className="capitalize">{k}</td>
                    <td className="text-right">{c ? num(c.points, 1) : "excluded"}</td>
                    <td className="text-right">{num(w * 100, 0)}%</td>
                    <td className="text-right">{c ? `${num(c.effective_weight * 100, 1)}%` : "—"}</td>
                    <td className="text-right">{c ? num(c.contribution, 2) : "—"}</td>
                  </tr>
                );
              })}
              <tr className="font-semibold"><td>Total</td><td colSpan={3} /><td className="text-right">{num(s.total, 1)}</td></tr>
            </tbody>
          </table>
          {Object.entries(s.components).map(([k, c]) => (
            <div key={k}>
              <div className="font-semibold capitalize">{k} rules</div>
              <ul className="ml-3 list-disc">
                {c.rules.map((r, i) => (
                  <li key={i}>
                    <span className="font-mono">{r.rule}</span>
                    {r.left !== undefined && r.left !== null && <> : {fmt(r.left)}{r.right !== undefined && r.right !== null && <> vs {fmt(r.right)}</>}</>}
                    {typeof r.result === "boolean" && <> → {r.result ? "true" : "false"}</>} → <b>{num(r.points, 0)} pts</b>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div className="text-slate-500">
            Classification: ≥60 bullish, ≤40 bearish, otherwise neutral. Score version {s.score_version}. params_hash {s.params_hash.slice(0, 12)}…, input_hash{" "}
            {s.input_hash.slice(0, 12)}…
          </div>
        </div>
      )}
    </div>
  );
}

export function ScorePanel({ scores }: { scores: Record<Horizon, Score> }) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {(["short", "medium", "long"] as const).map((h) => <ScoreCard key={h} s={scores[h]} />)}
    </div>
  );
}
