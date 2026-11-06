"use client";

import type { ApiError } from "@/lib/api";
import { pct, signClass, usd } from "@/lib/format";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <span className="h-3 w-3 animate-pulse rounded-full bg-slate-400" /> {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: ApiError | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-200">
      <div>{error.message}</div>
      {onRetry && <button onClick={onRetry} className="mt-2 rounded border border-rose-400 px-2 py-0.5 text-xs">Retry</button>}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="p-4 text-sm text-slate-500">{children}</div>;
}

export function Note({ children, tone = "amber" }: { children: React.ReactNode; tone?: "amber" | "slate" | "emerald" }) {
  const cls = {
    amber: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200",
    slate: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
    emerald: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200",
  }[tone];
  return <div className={`rounded-md border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

export function Section({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card min-w-0">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold num">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function Usd({ v, digits = 0 }: { v: number | null | undefined; digits?: number }) {
  return <span className={signClass(v)}>{usd(v, digits)}</span>;
}

export function Pct({ v, digits = 1 }: { v: number | null | undefined; digits?: number }) {
  return <span className={signClass(v)}>{pct(v, digits)}</span>;
}

export const btn = "rounded border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800";
export const btnPrimary = "rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900";
export const input = "rounded border border-slate-300 bg-transparent px-1.5 py-1 text-sm dark:border-slate-700";
