"use client";

import { useState } from "react";

import { ApiError, apiFetch, notifyAlerts } from "@/lib/research/api";

type PricesSummary = {
  status: string; updated?: number; up_to_date?: number; failed?: number; skipped_budget?: number; message?: string; error_code?: string;
  results?: { ticker: string; status: string; message?: string }[];
};
type IbkrSummary = { status: string; message?: string | null; error_code?: string | null; positions_count?: number } | null;
type FxSummary = { status: string; new_days?: number; last_date?: string | null; message?: string } | null;
type AllResp = { ibkr: IbkrSummary; prices: PricesSummary; eu_prices?: PricesSummary; fx?: FxSummary };
type OneResp = { ticker: string; status: string; bars_added: number; last_date?: string | null; message?: string; mode?: string };

function summarise(r: AllResp): { text: string; ok: boolean } {
  const parts: string[] = [];
  let ok = true;
  if (r.ibkr) {
    if (r.ibkr.status === "success") parts.push(`IBKR: ${r.ibkr.positions_count ?? 0} positions synced`);
    else if (r.ibkr.status === "failed") { parts.push(`IBKR: ${r.ibkr.message}`); ok = false; }
    else parts.push(`IBKR: ${r.ibkr.message}`);
  }
  const prices = (label: string, p: PricesSummary | undefined, skipNotConfigured = false) => {
    if (!p) return;
    if (p.status === "ok") {
      parts.push(`${label}: ${p.updated} updated, ${p.up_to_date} already up to date` +
        (p.failed ? `, ${p.failed} failed` : "") + (p.skipped_budget ? `, ${p.skipped_budget} deferred (request budget)` : ""));
      if (p.failed) {
        ok = false;
        const first = p.results?.find((x) => x.status === "failed");
        if (first?.message) parts.push(`${first.ticker}: ${first.message}`);
      }
    } else if (p.status === "failed") { parts.push(`${label}: ${p.message}`); ok = false; }
    else if (!(skipNotConfigured && p.error_code === "not_configured")) parts.push(`${label}: ${p.message}`);
  };
  prices("US prices", r.prices);
  prices("EU prices", r.eu_prices, true);
  if (r.fx) {
    if (r.fx.status === "failed") { parts.push(`FX: ${r.fx.message}`); ok = false; }
    else parts.push(`FX (ECB): up to ${r.fx.last_date ?? "—"}`);
  }
  return { text: parts.join(" · "), ok };
}

const base = "inline-flex items-center gap-1 rounded border px-2.5 py-1 text-sm disabled:opacity-60";

/** Refreshes everything on demand: IBKR holdings (if used) and real prices, then reloads the page data. */
export function RefreshAllButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const run = async () => {
    setBusy(true);
    setMsg(null);
    try {
      setMsg(summarise(await apiFetch<AllResp>("/api/refresh", { method: "POST" })));
      notifyAlerts();
      onDone();
    } catch (e) {
      setMsg({ text: (e as ApiError).message, ok: false });
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button onClick={run} disabled={busy} className={`${base} border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800`}
        title="Sync IBKR holdings (if used) and download the latest prices">
        <span className={busy ? "animate-spin" : ""} aria-hidden>↻</span> {busy ? "Refreshing…" : "Refresh data"}
      </button>
      {msg && <span role="status" className={`text-xs ${msg.ok ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}`}>{msg.text}</span>}
    </span>
  );
}

/** Refreshes one real (Tiingo) instrument. Optional full re-download. Disabled for synthetic data. */
export function RefreshOneButton({ listingId, real, onDone, compact = false }: { listingId: number; real: boolean; onDone: () => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const run = async (force: boolean) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await apiFetch<OneResp>(`/api/listings/${listingId}/refresh`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force }),
      });
      const ok = r.status !== "failed";
      const text = r.status === "up_to_date" ? `Up to date (${r.last_date})`
        : r.status === "skipped_budget" ? (r.message ?? "Free-plan limit reached; try later")
        : r.status === "failed" ? (r.message ?? "Failed")
        : `${r.mode === "full" ? "Re-downloaded" : "Updated"}: latest ${r.last_date}${r.bars_added ? ` (+${r.bars_added})` : ""}`;
      setMsg({ text, ok });
      notifyAlerts();
      if (ok) onDone();
    } catch (e) {
      setMsg({ text: (e as ApiError).message, ok: false });
    } finally {
      setBusy(false);
    }
  };
  if (!real) {
    return compact ? null : (
      <span className="text-xs text-slate-500" title="Synthetic demo data is generated locally; there is nothing to download.">Synthetic data: no refresh needed</span>
    );
  }
  if (compact) {
    return (
      <span className="inline-flex items-center gap-1">
        <button onClick={() => run(false)} disabled={busy} aria-label="Refresh this symbol" title={msg?.text ?? "Refresh this symbol"}
          className={`rounded px-1 text-sm hover:bg-slate-200 disabled:opacity-50 dark:hover:bg-slate-700 ${msg && !msg.ok ? "text-amber-600" : ""}`}>
          <span className={busy ? "inline-block animate-spin" : ""}>↻</span>
        </button>
        {msg && <span className={`text-[10px] ${msg.ok ? "text-emerald-600" : "text-amber-600"}`}>{msg.ok ? "✓" : "!"}</span>}
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button onClick={() => run(false)} disabled={busy} className={`${base} border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800`}>
        <span className={busy ? "animate-spin" : ""} aria-hidden>↻</span> {busy ? "Refreshing…" : "Refresh"}
      </button>
      <button onClick={() => run(true)} disabled={busy} className="text-xs text-slate-500 underline" title="Download the full 5-year history again (uses 1 request)">
        re-download history
      </button>
      {msg && <span role="status" className={`text-xs ${msg.ok ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}`}>{msg.text}</span>}
    </span>
  );
}
