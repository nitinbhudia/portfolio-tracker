"use client";

import type { ApiError, Classification, Provenance } from "@/lib/research/api";
import { fmtTimestamp } from "@/lib/research/format";

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
      <div className="font-semibold">Error ({error.code})</div>
      <div>{error.message}</div>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 rounded border border-rose-400 px-2 py-0.5 text-xs hover:bg-rose-100 dark:hover:bg-rose-900">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="p-4 text-sm text-slate-500">{children}</div>;
}

export function Warn({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
      {children}
    </div>
  );
}

const CLS: Record<string, string> = {
  bullish: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200",
  neutral: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
  bearish: "bg-rose-100 text-rose-800 dark:bg-rose-900/60 dark:text-rose-200",
};

export function ClassBadge({ c, label }: { c: Classification; label?: string }) {
  if (!c) return <span className="rounded px-1.5 py-0.5 text-xs text-slate-500 ring-1 ring-slate-300 dark:ring-slate-700">n/a</span>;
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${CLS[c]}`} title={`${label ? label + ": " : ""}${c}`}>
      {label ? `${label[0].toUpperCase()} ` : ""}
      {c}
    </span>
  );
}

export function SyntheticTag() {
  return <span className="rounded bg-violet-600 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">Synthetic</span>;
}

export function ProvenanceBadge({ p, compact = false }: { p: Provenance | null | undefined; compact?: boolean }) {
  if (!p) return null;
  const delayed =
    p.data_type === "end_of_day_broker_marks" ? "end-of-day broker prices"
    : p.data_type === "end_of_day" ? "end-of-day data"
    : p.is_delayed ? `delayed ${p.delay_minutes ?? "?"} min` : "not delayed";
  return (
    <div className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500 dark:text-slate-400 ${compact ? "" : "mt-1"}`}>
      {p.is_synthetic && <SyntheticTag />}
      {p.is_synthetic === false && <span className="rounded bg-emerald-700 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">Real</span>}
      <span>
        Source: <b className="font-medium text-slate-700 dark:text-slate-300">{p.source ?? "none"}</b>
      </span>
      <span>As of: {fmtTimestamp(p.as_of)}</span>
      {p.oldest_as_of && p.oldest_as_of !== p.as_of && <span>(oldest: {fmtTimestamp(p.oldest_as_of)})</span>}
      <span>TZ: {p.exchange_timezone ?? "—"}</span>
      <span>{delayed}</span>
      {p.price_adjustment === "split_dividend" && <span>adjusted for splits &amp; dividends</span>}
      {p.stale && <span className="rounded bg-amber-200 px-1.5 py-0.5 font-semibold text-amber-900">STALE</span>}
    </div>
  );
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
