"use client";

import { useEffect, useState } from "react";

import { Section, btn } from "@/components/ui";
import { apiFetch, jsonInit, useApi } from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";

type Step = { status: string; message?: string; updated?: number; up_to_date?: number; failed?: number | string[]; waiting?: number;
  fetched?: number; remaining?: number; configured?: boolean; skipped?: string; eu_updated?: number | null };
type AR = { enabled: boolean; running: boolean; last_run_at: string | null; last_complete_session: string | null; latest_session: string;
  backlog: boolean; next_retry_at: string | null; steps: Record<string, Step>; check_every_minutes: number };

const NAMES: Record<string, string> = { fx: "Exchange rates (ECB)", research: "Research prices and alerts", history: "Performance price history" };

function describe(name: string, s: Step): string {
  if (s.status === "failed") return `failed: ${s.message}`;
  if (s.configured === false) return "skipped (no Tiingo key)";
  if (s.skipped) return `skipped (${s.skipped})`;
  if (name === "research") return `${s.updated ?? 0} updated, ${s.up_to_date ?? 0} already current${s.waiting ? `, ${s.waiting} waiting for the hourly limit` : ""}`
    + (typeof s.failed === "number" && s.failed ? `, ${s.failed} failed` : "") + (s.eu_updated ? `, ${s.eu_updated} European` : "");
  if (name === "history") return `${s.fetched ?? 0} downloaded${s.remaining ? `, ${s.remaining} still to do` : ""}`;
  return "done";
}

/** The automatic daily refresh: on/off, what the last run did, and Run now. */
export function AutoRefreshCard() {
  const q = useApi<AR>("/api/auto-refresh");
  const [busy, setBusy] = useState(false);
  const d = q.data;
  useEffect(() => {  // while a run is going, follow it
    if (!d?.running) return;
    const t = setInterval(q.reload, 3000);
    return () => clearInterval(t);
  }, [d?.running, q.reload]);
  if (!d) return null;
  const toggle = async () => { setBusy(true); try { q.setData(await apiFetch<AR>("/api/auto-refresh", jsonInit("PUT", { enabled: !d.enabled }))); } finally { setBusy(false); } };
  const runNow = async () => { setBusy(true); try { q.setData(await apiFetch<AR>("/api/auto-refresh/run", { method: "POST" })); } finally { setBusy(false); } };
  const current = d.last_complete_session === d.latest_session;
  return (
    <Section title="Automatic daily refresh" right={
      <span className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={d.enabled} disabled={busy} onChange={toggle} /> On</label>
        <button className={btn} disabled={busy || d.running} onClick={runNow}>{d.running ? "Refreshing…" : "Run now"}</button>
      </span>}>
      <div className="space-y-1 text-sm">
        <p>{!d.enabled ? "Off: prices only update when you press a refresh button."
          : current ? <>Up to date with the US close of <b>{d.latest_session}</b>.</>
          : d.backlog && d.next_retry_at ? <>Part done for <b>{d.latest_session}</b>; the rest continues at {fmtTimestamp(d.next_retry_at)} (Tiingo&apos;s hourly limit).</>
          : <>The US close of <b>{d.latest_session}</b> will be fetched at the next check (every {d.check_every_minutes} minutes while the app runs).</>}</p>
        {d.last_run_at && (
          <div className="text-xs text-slate-600 dark:text-slate-300">
            <p>Last run {fmtTimestamp(d.last_run_at)}:</p>
            <ul className="ml-4 list-disc">{Object.entries(d.steps).map(([k, s]) => (
              <li key={k} className={s.status === "failed" ? "text-rose-700 dark:text-rose-400" : ""}>{NAMES[k] ?? k}: {describe(k, s)}</li>))}</ul>
          </div>
        )}
        <p className="text-xs text-slate-500">While the app is running it checks every {d.check_every_minutes} minutes. Once a US trading day has closed (about
          18:00 New York time) it updates exchange rates, Research (your holdings, watchlist, sector ETFs, then alerts) and Performance&apos;s price history.
          If the app was closed, it catches up when you open it. Positions and the other pages then use the latest close.</p>
      </div>
    </Section>
  );
}
