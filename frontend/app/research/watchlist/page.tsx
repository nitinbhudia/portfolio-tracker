"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { type Column, DataTable } from "@/components/research/DataTable";
import { SetupBreakdown, SetupChips } from "@/components/research/Setups";
import { ClassBadge, Empty, ErrorBox, Loading, ProvenanceBadge, Section } from "@/components/research/ui";
import { WatchStar } from "@/components/research/WatchStar";
import { apiFetch, type ScanResp, type ScanRow, type SetupCatalogItem, useApi, type WatchlistResp } from "@/lib/research/api";
import { num, pct, signClass } from "@/lib/research/format";
import { triggeredNames } from "@/lib/research/setups";

function NoteCell({ row, onSaved }: { row: ScanRow; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(row.note ?? "");
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setErr(null);
    try {
      await apiFetch(`/api/watchlist/${row.listing.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: text }),
      });
      setEditing(false);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  if (!editing)
    return (
      <button className="max-w-64 truncate text-left text-xs hover:underline" title={row.note ?? "Add a note"} onClick={() => setEditing(true)}>
        {row.note || <span className="text-slate-400">+ note</span>}
      </button>
    );
  return (
    <span className="flex items-center gap-1">
      <input aria-label={`Note for ${row.listing.ticker}`} value={text} maxLength={500} autoFocus onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
        className="w-48 rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700" />
      <button className="text-xs underline" onClick={save}>Save</button>
      {err && <span className="text-xs text-rose-600">{err}</span>}
    </span>
  );
}

const n = (v: number | null | undefined) => (v === undefined ? null : v);

function makeColumns(catalog: SetupCatalogItem[], reload: () => void, select: (id: number) => void): Column<ScanRow>[] {
  return [
    { key: "watch", label: "★", type: "text", sortable: false, filterable: false, get: () => null,
      render: (r) => <WatchStar listingId={r.listing.id} on onChange={reload} /> },
    { key: "ticker", label: "Symbol", type: "text", firstDir: "asc", get: (r) => r.listing.ticker,
      render: (r) => <Link href={`/research/analysis/${r.listing.id}`} className="font-medium hover:underline">{r.listing.ticker}</Link> },
    { key: "data", label: "Data", type: "enum", labels: { real: "Real", synthetic: "Synthetic" }, get: (r) => r.namespace,
      render: (r) => r.namespace === "real"
        ? <span className="rounded bg-emerald-700 px-1 text-[10px] font-bold uppercase text-white">Real</span>
        : <span className="rounded bg-violet-600 px-1 text-[10px] font-bold uppercase text-white">Synth</span> },
    { key: "exchange", label: "Exch.", type: "enum", get: (r) => r.listing.exchange },
    { key: "close", label: "Close", type: "number", align: "right", get: (r) => n(r.close), render: (r) => num(r.close) },
    { key: "d1", label: "1D", type: "number", align: "right", get: (r) => n(r.change_1d_pct),
      render: (r) => <span className={signClass(r.change_1d_pct)}>{pct(r.change_1d_pct, 1)}</span> },
    { key: "s_short", label: "Score S", type: "number", align: "right", get: (r) => n(r.score_short), render: (r) => num(r.score_short, 1) },
    { key: "s_medium", label: "Score M", type: "number", align: "right", get: (r) => n(r.score_medium), render: (r) => num(r.score_medium, 1) },
    { key: "s_long", label: "Score L", type: "number", align: "right", get: (r) => n(r.score_long), render: (r) => num(r.score_long, 1) },
    { key: "c_medium", label: "Trend M", type: "enum", get: (r) => r.class_medium ?? null, render: (r) => <ClassBadge c={r.class_medium ?? null} /> },
    { key: "setups", label: "Setups now", type: "text", get: (r) => triggeredNames(r.triggered, catalog) || null,
      render: (r) => <SetupChips triggered={r.triggered} catalog={catalog} /> },
    { key: "note", label: "Note", type: "text", get: (r) => r.note ?? null, render: (r) => <NoteCell row={r} onSaved={reload} /> },
    { key: "added", label: "Added", type: "date", get: (r) => r.added_at?.slice(0, 10) ?? null, render: (r) => r.added_at?.slice(0, 10) ?? "—", defaultHidden: true },
    { key: "why", label: "Rules", type: "text", sortable: false, filterable: false, get: () => null,
      render: (r) => r.setups ? <button className="text-xs text-blue-600 underline dark:text-blue-400" onClick={() => select(r.listing.id)}>Why?</button> : null },
  ];
}

export default function WatchlistPage() {
  const { data, error, loading, reload } = useApi<WatchlistResp>("/api/watchlist");
  // The catalog (setup names) comes with the scanner response, which is cheap to read.
  const { data: scan } = useApi<ScanResp>("/api/scanner");
  const catalog = useMemo(() => scan?.setup_catalog ?? [], [scan]);
  const [selected, setSelected] = useState<number | null>(null);
  const columns = useMemo(() => makeColumns(catalog, reload, setSelected), [catalog, reload]);
  const sel = data?.rows.find((r) => r.listing.id === selected);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Watchlist</h1>
      <Section title="Watched instruments" right={data ? <ProvenanceBadge p={data.provenance} compact /> : null}>
        {loading && !data ? (
          <Loading label="Calculating your watchlist…" />
        ) : error ? (
          <ErrorBox error={error} onRetry={reload} />
        ) : data && data.rows.length === 0 ? (
          <Empty>
            Your watchlist is empty. Add instruments with the ☆ star in the <Link className="underline" href="/research/scanner">Opportunity Scanner</Link> or
            on any analysis page.
          </Empty>
        ) : data ? (
          <>
            <DataTable id="watchlist" rows={data.rows} columns={columns} rowKey={(r) => r.listing.id}
              initialSort={[{ key: "ticker", dir: "asc" }]} rowClassName={(r) => (r.status !== "ok" ? "opacity-60" : "")} />
            <p className="mt-2 text-xs text-slate-500">
              Values are calculated now from the latest stored prices (sensitivity: {data.sensitivity}). Setups are conditions to research, not buy
              or sell signals.
            </p>
          </>
        ) : null}
      </Section>
      {sel?.setups && (
        <Section title={`Setup rules · ${sel.listing.ticker} · bar ${sel.as_of}`}
          right={<button className="text-xs underline" onClick={() => setSelected(null)}>Close</button>}>
          <SetupBreakdown setups={sel.setups} />
        </Section>
      )}
    </div>
  );
}
