"use client";

import Link from "next/link";
import { useMemo } from "react";

import { type Column, DataTable } from "@/components/research/DataTable";
import { EuMarketDataPanel, FxPanel } from "@/components/research/EuMarketDataPanel";
import { MarketDataPanel } from "@/components/research/MarketDataPanel";
import { RefreshAllButton, RefreshOneButton } from "@/components/research/RefreshButtons";
import { type Spark, Sparkline } from "@/components/research/Sparkline";
import { ClassBadge, ErrorBox, Loading, ProvenanceBadge, Section } from "@/components/research/ui";
import { type Classification, type ListingInfo, type Provenance, useApi } from "@/lib/research/api";
import { num, pct, ratioLabel, signClass } from "@/lib/research/format";

type Row = {
  listing: ListingInfo;
  namespace: "real" | "synthetic";
  held: boolean;
  provenance: Provenance;
  status: string;
  as_of?: string;
  close?: number;
  change_1d_pct?: number | null;
  change_1m_pct?: number | null;
  change_ytd_pct?: number | null;
  score_short?: number | null;
  score_medium?: number | null;
  score_long?: number | null;
  class_short?: Classification;
  class_medium?: Classification;
  class_long?: Classification;
  rsi14?: number | null;
  macd_hist?: number | null;
  atr_pct?: number | null;
  relvol20?: number | null;
  above_sma50?: boolean | null;
  above_sma200?: boolean | null;
  fib_direction?: "up" | "down" | null;
  fib_nearest_ratio?: number | null;
  fib_nearest_price?: number | null;
  fib_distance_pct?: number | null;
  fib_distance_atr?: number | null;
  data_gaps?: number;
  spark?: Spark;
};
type Resp = { rows: Row[]; provenance: Provenance; sensitivity: string };

const CLS = { bullish: "bullish", neutral: "neutral", bearish: "bearish", "—": "n/a" };
const n = (v: number | null | undefined) => (v === undefined ? null : v);

const makeColumns = (reload: () => void): Column<Row>[] => [
  { key: "ticker", label: "Symbol", type: "text", get: (r) => r.listing.ticker, firstDir: "asc",
    render: (r) => <Link href={`/research/analysis/${r.listing.id}`} className="font-medium hover:underline">{r.listing.ticker}</Link> },
  { key: "name", label: "Name", type: "text", get: (r) => r.listing.tracks ? `${r.listing.name} (${r.listing.tracks})` : r.listing.name,
    render: (r) => <span className="inline-block max-w-48 truncate align-bottom text-xs text-slate-600 dark:text-slate-300" title={r.listing.name}>{r.listing.tracks ?? r.listing.name}</span> },
  { key: "data", label: "Data", type: "enum", labels: { real: "Real", synthetic: "Synthetic" }, get: (r) => r.namespace,
    render: (r) => r.namespace === "real"
      ? <span className="rounded bg-emerald-700 px-1 text-[10px] font-bold uppercase text-white">Real</span>
      : <span className="rounded bg-violet-600 px-1 text-[10px] font-bold uppercase text-white">Synth</span> },
  { key: "type", label: "Type", type: "enum", get: (r) => r.listing.asset_class },
  { key: "exchange", label: "Exch.", type: "enum", get: (r) => r.listing.exchange },
  { key: "ccy", label: "Ccy", type: "enum", get: (r) => r.listing.currency, defaultHidden: true },
  { key: "held", label: "Held", type: "bool", labels: { true: "held", false: "not held" }, get: (r) => r.held, render: (r) => (r.held ? "●" : "") },
  { key: "close", label: "Close", type: "number", align: "right", get: (r) => n(r.close), render: (r) => num(r.close) },
  { key: "d1", label: "1D", type: "number", align: "right", get: (r) => n(r.change_1d_pct),
    render: (r) => <span className={signClass(r.change_1d_pct)}>{pct(r.change_1d_pct, 1)}</span> },
  { key: "m1", label: "1M", type: "number", align: "right", get: (r) => n(r.change_1m_pct),
    render: (r) => <span className={signClass(r.change_1m_pct)}>{pct(r.change_1m_pct, 1)}</span> },
  { key: "ytd", label: "YTD %", type: "number", align: "right", get: (r) => n(r.change_ytd_pct),
    render: (r) => <span className={signClass(r.change_ytd_pct)}>{pct(r.change_ytd_pct, 1)}</span>, defaultHidden: true },
  { key: "spark3m", label: "3M", type: "number", align: "right", title: "Last 3 months (sort = 3-month % change)", get: (r) => r.spark?.m3_change_pct ?? null,
    render: (r) => <Sparkline values={r.spark?.m3} change={r.spark?.m3_change_pct} start={r.spark?.m3_start} label={`${r.listing.ticker} 3 months`} /> },
  { key: "sparkytd", label: "YTD", type: "number", align: "right", title: "Year-to-date (sort = YTD % change)", get: (r) => r.spark?.ytd_change_pct ?? null,
    render: (r) => <Sparkline values={r.spark?.ytd} change={r.spark?.ytd_change_pct} start={r.spark?.ytd_start} label={`${r.listing.ticker} year-to-date`} /> },
  { key: "s_short", label: "Score S", type: "number", align: "right", get: (r) => n(r.score_short), render: (r) => num(r.score_short, 1) },
  { key: "s_medium", label: "Score M", type: "number", align: "right", get: (r) => n(r.score_medium), render: (r) => num(r.score_medium, 1) },
  { key: "s_long", label: "Score L", type: "number", align: "right", get: (r) => n(r.score_long), render: (r) => num(r.score_long, 1) },
  { key: "c_short", label: "Trend S", type: "enum", labels: CLS, get: (r) => r.class_short ?? null, render: (r) => <ClassBadge c={r.class_short ?? null} /> },
  { key: "c_medium", label: "Trend M", type: "enum", labels: CLS, get: (r) => r.class_medium ?? null, render: (r) => <ClassBadge c={r.class_medium ?? null} />, defaultHidden: true },
  { key: "c_long", label: "Trend L", type: "enum", labels: CLS, get: (r) => r.class_long ?? null, render: (r) => <ClassBadge c={r.class_long ?? null} />, defaultHidden: true },
  { key: "rsi", label: "RSI 14", type: "number", align: "right", get: (r) => n(r.rsi14), render: (r) => num(r.rsi14, 1) },
  { key: "macd", label: "MACD hist", type: "number", align: "right", get: (r) => n(r.macd_hist), render: (r) => num(r.macd_hist, 3), defaultHidden: true },
  { key: "atr", label: "ATR %", type: "number", align: "right", get: (r) => n(r.atr_pct), render: (r) => pct(r.atr_pct, 2, false), defaultHidden: true },
  { key: "relvol", label: "Rel. vol", type: "number", align: "right", get: (r) => n(r.relvol20), render: (r) => num(r.relvol20), defaultHidden: true },
  { key: "sma50", label: ">SMA50", type: "bool", labels: { true: "above", false: "below" }, get: (r) => r.above_sma50 ?? null,
    render: (r) => (r.above_sma50 == null ? "—" : r.above_sma50 ? "above" : "below"), defaultHidden: true },
  { key: "sma200", label: ">SMA200", type: "bool", labels: { true: "above", false: "below" }, get: (r) => r.above_sma200 ?? null,
    render: (r) => (r.above_sma200 == null ? "—" : r.above_sma200 ? "above" : "below") },
  { key: "fibdir", label: "Swing", type: "enum", get: (r) => r.fib_direction ?? null, render: (r) => r.fib_direction ?? "—", defaultHidden: true },
  { key: "fib", label: "Nearest Fib", type: "number", get: (r) => n(r.fib_nearest_ratio),
    render: (r) => (r.fib_nearest_ratio != null ? `${ratioLabel(r.fib_nearest_ratio)} @ ${num(r.fib_nearest_price)}` : "—") },
  { key: "fibdist", label: "Fib dist.", type: "number", align: "right", get: (r) => n(r.fib_distance_pct), render: (r) => pct(r.fib_distance_pct, 1) },
  { key: "fibatr", label: "Fib dist. (ATR)", type: "number", align: "right", get: (r) => n(r.fib_distance_atr), render: (r) => num(r.fib_distance_atr) },
  { key: "asof", label: "Last day", type: "date", get: (r) => r.as_of ?? r.provenance.latest_bar_date ?? null, render: (r) => r.as_of ?? "—", defaultHidden: true },
  { key: "stale", label: "Stale", type: "bool", labels: { true: "stale", false: "fresh" }, get: (r) => r.provenance.stale,
    render: (r) => (r.provenance.stale ? <span className="text-amber-600">stale</span> : ""), defaultHidden: true },
  { key: "status", label: "Status", type: "enum", get: (r) => r.status, defaultHidden: true },
  { key: "refresh", label: "↻", type: "text", sortable: false, filterable: false, title: "Refresh this symbol (real data only)", get: () => null,
    render: (r) => <RefreshOneButton listingId={r.listing.id} real={r.namespace === "real"} onDone={reload} compact /> },
];

export default function MarketAnalysisIndex() {
  const { data, error, loading, reload } = useApi<Resp>("/api/screener");
  const columns = useMemo(() => makeColumns(reload), [reload]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Market Analysis</h1>
        <RefreshAllButton onDone={reload} />
      </div>
      <MarketDataPanel onChanged={reload} />
      <EuMarketDataPanel onChanged={reload} />
      <FxPanel />
      <Section title="Screener" right={data ? <ProvenanceBadge p={data.provenance} compact /> : null}>
        {loading && !data ? (
          <Loading label="Calculating all instruments…" />
        ) : error ? (
          <ErrorBox error={error} onRetry={reload} />
        ) : data ? (
          <>
            <DataTable
              id="screener"
              rows={data.rows}
              columns={columns}
              rowKey={(r) => r.listing.id}
              initialSort={[{ key: "data", dir: "asc" }, { key: "s_short", dir: "desc" }]}
              rowClassName={(r) => (r.status !== "ok" ? "opacity-60" : "")}
              presets={[
                { label: "Real data only", filters: { data: { kind: "enum", in: ["real"] } } },
                { label: "My holdings", filters: { held: { kind: "bool", is: true } } },
                { label: "Short-term bullish", filters: { c_short: { kind: "enum", in: ["bullish"] } }, sort: [{ key: "s_short", dir: "desc" }] },
                { label: "Short-term bearish", filters: { c_short: { kind: "enum", in: ["bearish"] } }, sort: [{ key: "s_short", dir: "asc" }] },
                { label: "RSI below 30", filters: { rsi: { kind: "number", max: 30 } }, sort: [{ key: "rsi", dir: "asc" }] },
                { label: "RSI above 70", filters: { rsi: { kind: "number", min: 70 } }, sort: [{ key: "rsi", dir: "desc" }] },
                { label: "Within 1 ATR of a Fib level", filters: { fibatr: { kind: "number", max: 1 } }, sort: [{ key: "fibatr", dir: "asc" }] },
                { label: "Above SMA 200", filters: { sma200: { kind: "bool", is: true } } },
              ]}
            />
            <p className="mt-2 text-xs text-slate-500">
              Fibonacci sensitivity: {data.sensitivity}. Presets are filters, not recommendations: an RSI below 30 or a nearby Fibonacci level is not a buy
              signal on its own. Rows marked Synth use synthetic demo data. Click a symbol for its full chart and score breakdown.
            </p>
          </>
        ) : null}
      </Section>
    </div>
  );
}
