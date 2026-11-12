"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { type Column, DataTable, type Preset } from "@/components/research/DataTable";
import { SetupBreakdown, SetupChips } from "@/components/research/Setups";
import { ClassBadge, Empty, ErrorBox, Loading, ProvenanceBadge, Section, Warn } from "@/components/research/ui";
import { WatchStar } from "@/components/research/WatchStar";
import { apiFetch, ApiError, type Horizon, type ScanResp, type ScanRow, type SetupCatalogItem, useApi } from "@/lib/research/api";
import { fmtTimestamp, num, pct, signClass } from "@/lib/research/format";
import { countBySetup, triggeredNames } from "@/lib/research/setups";

const HZ: Record<Horizon, string> = { short: "Short", medium: "Medium", long: "Long" };
const CLS = { bullish: "bullish", neutral: "neutral", bearish: "bearish", "—": "n/a" };
const n = (v: number | null | undefined) => (v === undefined ? null : v);

function makeColumns(h: Horizon, catalog: SetupCatalogItem[], select: (id: number) => void, reload: () => void): Column<ScanRow>[] {
  return [
    { key: "watch", label: "★", type: "bool", labels: { true: "on watchlist", false: "not on watchlist" }, title: "Watchlist",
      get: (r) => r.watchlisted, render: (r) => <WatchStar listingId={r.listing.id} on={r.watchlisted} onChange={reload} /> },
    { key: "rank", label: "Rank", type: "number", align: "right", firstDir: "asc", title: `Rank by ${HZ[h].toLowerCase()}-term score (1 = highest)`,
      get: (r) => n(r[`rank_${h}`]), render: (r) => r[`rank_${h}`] ?? "—" },
    { key: "ticker", label: "Symbol", type: "text", firstDir: "asc", get: (r) => r.listing.ticker,
      render: (r) => <Link href={`/research/analysis/${r.listing.id}`} className="font-medium hover:underline">{r.listing.ticker}</Link> },
    { key: "name", label: "Name", type: "text", get: (r) => r.listing.tracks ? `${r.listing.name} (${r.listing.tracks})` : r.listing.name, defaultHidden: true,
      render: (r) => <span className="inline-block max-w-48 truncate align-bottom text-xs" title={r.listing.name}>{r.listing.tracks ?? r.listing.name}</span> },
    { key: "data", label: "Data", type: "enum", labels: { real: "Real", synthetic: "Synthetic" }, get: (r) => r.namespace,
      render: (r) => r.namespace === "real"
        ? <span className="rounded bg-emerald-700 px-1 text-[10px] font-bold uppercase text-white">Real</span>
        : <span className="rounded bg-violet-600 px-1 text-[10px] font-bold uppercase text-white">Synth</span> },
    { key: "type", label: "Type", type: "enum", get: (r) => r.listing.asset_class },
    { key: "exchange", label: "Exch.", type: "enum", get: (r) => r.listing.exchange },
    { key: "sector", label: "Sector", type: "enum", get: (r) => r.listing.sector ?? null, render: (r) => r.listing.sector ?? "—", defaultHidden: true },
    { key: "ccy", label: "Ccy", type: "enum", get: (r) => r.listing.currency, defaultHidden: true },
    { key: "held", label: "Held", type: "bool", labels: { true: "held", false: "not held" }, get: (r) => r.held, render: (r) => (r.held ? "●" : "") },
    { key: "score", label: `Score ${HZ[h][0]}`, type: "number", align: "right", title: `${HZ[h]}-term score v1 (0–100)`,
      get: (r) => n(r[`score_${h}`]), render: (r) => num(r[`score_${h}`], 1) },
    { key: "cls", label: `Trend ${HZ[h][0]}`, type: "enum", labels: CLS, get: (r) => r[`class_${h}`] ?? null,
      render: (r) => <ClassBadge c={r[`class_${h}`] ?? null} /> },
    { key: "setups", label: "Setups", type: "text", title: "Triggered setups (filter by name)", get: (r) => triggeredNames(r.triggered, catalog) || null,
      render: (r) => <SetupChips triggered={r.triggered} catalog={catalog} /> },
    { key: "nsetups", label: "# setups", type: "number", align: "right", get: (r) => r.triggered.length, defaultHidden: true },
    { key: "close", label: "Close", type: "number", align: "right", get: (r) => n(r.close), render: (r) => num(r.close) },
    { key: "d1", label: "1D", type: "number", align: "right", get: (r) => n(r.change_1d_pct),
      render: (r) => <span className={signClass(r.change_1d_pct)}>{pct(r.change_1d_pct, 1)}</span> },
    { key: "m1", label: "1M", type: "number", align: "right", get: (r) => n(r.change_1m_pct),
      render: (r) => <span className={signClass(r.change_1m_pct)}>{pct(r.change_1m_pct, 1)}</span>, defaultHidden: true },
    { key: "vol", label: "Avg vol 20d", type: "number", align: "right", title: "Average daily volume over the last 20 bars (indices: none)",
      get: (r) => n(r.avg_volume20), render: (r) => num(r.avg_volume20, 0) },
    { key: "rsi", label: "RSI 14", type: "number", align: "right", get: (r) => n(r.rsi14), render: (r) => num(r.rsi14, 1), defaultHidden: true },
    { key: "asof", label: "Bar date", type: "date", get: (r) => r.as_of ?? null, render: (r) => r.as_of ?? "—", defaultHidden: true },
    { key: "status", label: "Status", type: "enum", get: (r) => r.status, defaultHidden: true },
    { key: "why", label: "Rules", type: "text", sortable: false, filterable: false, title: "Show every rule for this row", get: () => null,
      render: (r) => r.setups ? <button className="text-xs text-blue-600 underline dark:text-blue-400" onClick={() => select(r.listing.id)}>Why?</button> : null },
  ];
}

function Coverage({ data }: { data: Extract<ScanResp, { status: "ok" }> }) {
  const { run, freshness } = data;
  const c = run.coverage;
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>Universe: <b>{run.universe_size}</b> instruments</span>
        <span>Scanned: <b>{run.scanned}</b></span>
        <span>Not scanned: <b>{c.not_scanned.length}</b></span>
        <span>Timeframe: <b>{c.timeframe}</b></span>
        <span>Last scan: <b>{fmtTimestamp(run.finished_at)}</b></span>
        <span>Sensitivity: <b>{run.sensitivity}</b> (k = {run.atr_multiple})</span>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-600 dark:text-slate-300">
        <span>By source: {Object.entries(c.by_source).map(([k, v]) => `${k} ${v}`).join(", ")}</span>
        <span>By exchange: {Object.entries(c.by_exchange).map(([k, v]) => `${k} ${v.scanned}/${v.total}`).join(", ")}</span>
      </div>
      {c.not_scanned.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-slate-600 dark:text-slate-300">Why some instruments weren&apos;t scanned</summary>
          <ul className="mt-1 list-disc pl-5">
            {c.not_scanned.map((x) => (
              <li key={`${x.exchange}:${x.ticker}:${x.namespace}`}>{x.ticker} ({x.exchange}, {x.namespace}): {x.reason.replaceAll("_", " ")}, {x.bars_available} bars</li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-slate-500">{c.note}</p>
      {freshness.out_of_date && (
        <Warn>
          This scan is out of date:{" "}
          {[freshness.newer_bars.length ? `new prices for ${freshness.newer_bars.join(", ")}` : null,
            freshness.new_listings ? `${freshness.new_listings} new instrument(s)` : null,
            freshness.removed_listings ? `${freshness.removed_listings} removed instrument(s)` : null].filter(Boolean).join("; ")}
          . Run the scan again to include them.
        </Warn>
      )}
    </div>
  );
}

export default function ScannerPage() {
  const { data, error, loading, reload } = useApi<ScanResp>("/api/scanner");
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<ApiError | null>(null);
  const [horizon, setHorizon] = useState<Horizon>("medium");
  const [selected, setSelected] = useState<number | null>(null);

  const run = async () => {
    setRunning(true);
    setRunErr(null);
    try {
      await apiFetch("/api/scanner/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      reload();
    } catch (e) {
      setRunErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setRunning(false);
    }
  };

  const catalog = useMemo(() => data?.setup_catalog ?? [], [data]);
  const columns = useMemo(() => makeColumns(horizon, catalog, setSelected, reload), [horizon, catalog, reload]);
  const counts = useMemo(() => countBySetup(data?.rows ?? []), [data]);
  const presets = useMemo(() => {
    const byRank = [{ key: "rank", dir: "asc" as const }];
    const out: Preset[] = [{ label: "Any setup", filters: { nsetups: { kind: "number", min: 1 } }, sort: byRank }];
    for (const c of catalog)
      if (counts[c.id])
        out.push({ label: `${c.direction === "bullish" ? "▲" : "▼"} ${c.name} (${counts[c.id]})`, filters: { setups: { kind: "text", contains: c.name } }, sort: byRank });
    out.push(
      { label: "My holdings", filters: { held: { kind: "bool", is: true } } },
      { label: "Watchlist", filters: { watch: { kind: "bool", is: true } } },
      { label: "Real data only", filters: { data: { kind: "enum", in: ["real"] } } },
    );
    return out;
  }, [catalog, counts]);
  const sel = data?.rows.find((r) => r.listing.id === selected);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Opportunity Scanner</h1>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-slate-600 dark:text-slate-300">
            Rank by{" "}
            <select aria-label="Rank by horizon" value={horizon} onChange={(e) => setHorizon(e.target.value as Horizon)}
              className="rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700">
              {(Object.keys(HZ) as Horizon[]).map((k) => <option key={k} value={k}>{HZ[k]}-term score</option>)}
            </select>
          </label>
          <button onClick={run} disabled={running}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">
            {running ? "Scanning…" : data?.status === "ok" ? "Run scan again" : "Run scan"}
          </button>
        </div>
      </div>
      <ErrorBox error={runErr} />
      {loading && !data ? (
        <Loading label="Loading the latest scan…" />
      ) : error ? (
        <ErrorBox error={error} onRetry={reload} />
      ) : !data ? null : data.status === "no_scan" ? (
        <Section title="No scan yet">
          <Empty>No scan has been run. Press <b>Run scan</b> to check every instrument stored in the app against the {catalog.length} setup rules.</Empty>
        </Section>
      ) : (
        <>
          <Section title="Coverage" right={<ProvenanceBadge p={data.provenance} compact />}>
            <Coverage data={data} />
          </Section>
          <Section title={`Results · ranked by ${HZ[horizon].toLowerCase()}-term score`}>
            <DataTable id="scanner" rows={data.rows} columns={columns} rowKey={(r) => r.listing.id}
              initialSort={[{ key: "rank", dir: "asc" }]} presets={presets}
              rowClassName={(r) => (r.status !== "ok" ? "opacity-60" : r.listing.id === selected ? "bg-amber-50 dark:bg-amber-950/40" : "")}
              empty={<Empty>No instruments match these filters.</Empty>} />
            <p className="mt-2 text-xs text-slate-500">
              Setups are conditions to research, not recommendations, and none is a buy or sell signal on its own. Rank uses the transparent score
              (open a symbol for its breakdown). Rows marked Synth use synthetic demo data. No market-cap filter: no data source here provides market cap yet.
            </p>
          </Section>
          {sel?.setups && (
            <Section title={`Setup rules · ${sel.listing.ticker} · bar ${sel.as_of}`}
              right={<button className="text-xs underline" onClick={() => setSelected(null)}>Close</button>}>
              <SetupBreakdown setups={sel.setups} />
            </Section>
          )}
        </>
      )}
    </div>
  );
}
