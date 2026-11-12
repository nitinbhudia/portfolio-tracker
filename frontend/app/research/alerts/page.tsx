"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { AlertSettings } from "@/components/research/AlertSettings";
import { type Column, DataTable } from "@/components/research/DataTable";
import { Empty, ErrorBox, Loading, ProvenanceBadge, Section } from "@/components/research/ui";
import { type AlertEval, type AlertRow, type AlertsResp, apiFetch, ApiError, notifyAlerts, useApi } from "@/lib/research/api";
import { fmtTimestamp } from "@/lib/research/format";
import { fmtOperand } from "@/lib/research/setups";

const DIR: Record<AlertRow["direction"], string> = {
  bullish: "text-emerald-600 dark:text-emerald-400",
  bearish: "text-rose-600 dark:text-rose-400",
  neutral: "text-slate-500",
};
const DIR_ICON: Record<AlertRow["direction"], string> = { bullish: "▲", bearish: "▼", neutral: "◆" };

function fmtDetail(v: unknown): string {
  if (typeof v === "number") return fmtOperand(v);
  if (v === null || v === undefined) return "—";
  return String(v);
}

function makeColumns(markRead: (id: number) => void, select: (id: number) => void): Column<AlertRow>[] {
  return [
    { key: "read", label: "Read", type: "bool", labels: { true: "read", false: "unread" }, get: (r) => r.read,
      render: (r) => r.read ? <span className="text-xs text-slate-400">read</span>
        : <button className="text-xs text-blue-600 underline dark:text-blue-400" onClick={() => markRead(r.id)} aria-label={`Mark alert ${r.id} read`}>● mark read</button> },
    { key: "bar", label: "Bar date", type: "date", get: (r) => r.bar_date },
    { key: "ticker", label: "Symbol", type: "text", firstDir: "asc", get: (r) => r.listing.ticker,
      render: (r) => <Link href={r.type === "sector_rotation" ? `/research/sectors/${r.listing.ticker}` : `/research/analysis/${r.listing.id}`}
        className="font-medium hover:underline">{r.listing.ticker}</Link> },
    { key: "data", label: "Data", type: "enum", labels: { real: "Real", synthetic: "Synthetic" }, get: (r) => r.namespace,
      render: (r) => r.namespace === "real"
        ? <span className="rounded bg-emerald-700 px-1 text-[10px] font-bold uppercase text-white">Real</span>
        : <span className="rounded bg-violet-600 px-1 text-[10px] font-bold uppercase text-white">Synth</span> },
    { key: "type", label: "Type", type: "enum", get: (r) => r.type_label },
    { key: "dir", label: "Dir.", type: "enum", get: (r) => r.direction,
      render: (r) => <span className={DIR[r.direction]} title={r.direction}>{DIR_ICON[r.direction]} {r.direction}</span> },
    { key: "title", label: "Alert", type: "text", get: (r) => r.title, render: (r) => <span className={r.read ? "" : "font-medium"}>{r.title}</span> },
    { key: "created", label: "Created", type: "date", get: (r) => r.created_at.slice(0, 10), render: (r) => fmtTimestamp(r.created_at), defaultHidden: true },
    { key: "why", label: "Inputs", type: "text", sortable: false, filterable: false, get: () => null,
      render: (r) => <button className="text-xs text-blue-600 underline dark:text-blue-400" onClick={() => select(r.id)}>Why?</button> },
  ];
}

function EvalSummary({ ev }: { ev: AlertEval | null }) {
  if (!ev) return <p className="text-sm text-slate-500">No alert check has run yet. Press <b>Check now</b>, or refresh prices.</p>;
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600 dark:text-slate-300">
      <span>Last check: <b>{fmtTimestamp(ev.at)}</b></span>
      <span>Watching: <b>{ev.listings}</b> ({ev.scope === "all" ? "every stored instrument" : "holdings + watchlist"})</span>
      <span>New bars checked: <b>{ev.bars_evaluated}</b></span>
      <span>New alerts: <b>{ev.created}</b></span>
      <span>Held back by cooldown: <b>{ev.suppressed_cooldown}</b></span>
      {ev.skipped_unclosed_bars > 0 && <span>Unfinished sessions skipped: <b>{ev.skipped_unclosed_bars}</b></span>}
      {ev.skipped_backfill_bars > 0 && <span>Older bars not checked: <b>{ev.skipped_backfill_bars}</b></span>}
      {ev.insufficient_history.length > 0 && <span>Not enough history: {ev.insufficient_history.join(", ")}</span>}
      {ev.rotation?.enabled && <span>Sector rotation: <b>{ev.rotation.sectors}</b> sectors vs {ev.rotation.benchmark} ({ev.rotation.data === "synthetic" ? "synthetic demo" : "real data"}), <b>{ev.rotation.created}</b> new</span>}
    </div>
  );
}

export default function AlertsPage() {
  const { data, error, loading, reload } = useApi<AlertsResp>("/api/alerts");
  const [busy, setBusy] = useState(false);
  const [actErr, setActErr] = useState<ApiError | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const act = async (path: string) => {
    setBusy(true);
    setActErr(null);
    try {
      await apiFetch(path, { method: "POST" });
      notifyAlerts();
      reload();
    } catch (e) {
      setActErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(false);
    }
  };

  const columns = useMemo(() => makeColumns((id) => act(`/api/alerts/${id}/read`), setSelected), []); // eslint-disable-line react-hooks/exhaustive-deps
  const sel = data?.alerts.find((a) => a.id === selected);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Alerts {data && data.unread > 0 && <span className="text-sm font-normal text-slate-500">· {data.unread} unread</span>}</h1>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setShowSettings(!showSettings)} aria-expanded={showSettings}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700">{showSettings ? "Hide settings" : "Settings"}</button>
          <button onClick={() => act("/api/alerts/read-all")} disabled={busy || !data?.unread}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-slate-700">Mark all read</button>
          <button onClick={() => act("/api/alerts/evaluate")} disabled={busy}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">{busy ? "Checking…" : "Check now"}</button>
        </div>
      </div>
      <ErrorBox error={actErr} />
      {showSettings && (
        <Section title="Alert settings">
          <AlertSettings onSaved={reload} />
        </Section>
      )}
      <Section title="Alerts" right={data ? <ProvenanceBadge p={data.provenance} compact /> : null}>
        {loading && !data ? (
          <Loading label="Loading alerts…" />
        ) : error ? (
          <ErrorBox error={error} onRetry={reload} />
        ) : data ? (
          <div className="space-y-3">
            <EvalSummary ev={data.last_evaluation} />
            {data.alerts.length === 0 ? (
              <Empty>
                No alerts yet. Alerts appear when a condition <i>changes</i> on a closed daily bar for your holdings and
                {" "}<Link className="underline" href="/research/watchlist">watchlist</Link>, e.g. a price crossing SMA 50 or a Fibonacci level.
              </Empty>
            ) : (
              <DataTable id="alerts" rows={data.alerts} columns={columns} rowKey={(r) => r.id}
                initialSort={[{ key: "bar", dir: "desc" }]}
                rowClassName={(r) => (r.id === selected ? "bg-amber-50 dark:bg-amber-950/40" : r.read ? "opacity-70" : "")}
                presets={[
                  { label: "Unread", filters: { read: { kind: "bool", is: false } } },
                  { label: "Sector rotation", filters: { type: { kind: "enum", in: ["Sector rotation"] } } },
                  { label: "▲ Bullish", filters: { dir: { kind: "enum", in: ["bullish"] } } },
                  { label: "▼ Bearish", filters: { dir: { kind: "enum", in: ["bearish"] } } },
                  { label: "Real data only", filters: { data: { kind: "enum", in: ["real"] } } },
                ]}
                empty={<Empty>No alerts match these filters.</Empty>} />
            )}
            <p className="text-xs text-slate-500">
              Alerts are checked on closed daily bars only, after every price refresh or when you press Check now. They describe a condition that
              changed. They are not buy or sell signals. In-app only for now; email and Telegram are not set up.
            </p>
          </div>
        ) : null}
      </Section>
      {sel && (
        <Section title={`Why: ${sel.listing.ticker} · ${sel.bar_date}`} right={<button className="text-xs underline" onClick={() => setSelected(null)}>Close</button>}>
          <p className="mb-2 text-sm">{sel.title}</p>
          {sel.type === "sector_rotation" && (
            <p className="mb-2 text-xs"><Link className="underline" href={`/research/sectors/${sel.listing.ticker}`}>Open the {String(sel.details.sector)} sector page →</Link></p>
          )}
          <table className="tbl num text-xs">
            <tbody>
              {Object.entries(sel.details).map(([k, v]) => (
                <tr key={k}><td className="pr-4 text-slate-500">{k.replaceAll("_", " ")}</td><td className="text-right">{fmtDetail(v)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">
            Rule set alerts-v1 · config {sel.config_hash.slice(0, 10)} · input {sel.input_hash.slice(0, 10)} · source {sel.source}
          </p>
        </Section>
      )}
    </div>
  );
}
