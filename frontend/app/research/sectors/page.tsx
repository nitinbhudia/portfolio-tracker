"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { type Column, DataTable, type Preset } from "@/components/research/DataTable";
import { RefreshAllButton } from "@/components/research/RefreshButtons";
import { RrgChart, sectorColor } from "@/components/research/RrgChart";
import { ClassBadge, Empty, ErrorBox, Loading, ProvenanceBadge, Section, Warn } from "@/components/research/ui";
import { apiFetch, ApiError, type Quadrant, type RotationEvent, type SectorRow, type SectorsResp, useApi } from "@/lib/research/api";
import { fmtTimestamp, num, pct, signClass } from "@/lib/research/format";
import { QUADRANT_BADGE, QUADRANT_LABEL } from "@/lib/research/rrg";
import { REGION_DEFAULT_BENCHMARK, sectorQuery, useSectorContext } from "@/lib/research/sectorContext";

const sel = "rounded border border-slate-300 bg-transparent px-1.5 py-1 text-sm dark:border-slate-700";
const n = (v: number | null | undefined) => (v === undefined ? null : v);

function QBadge({ q }: { q?: Quadrant | null }) {
  if (!q) return <span className="text-xs text-slate-400">—</span>;
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${QUADRANT_BADGE[q]}`}>{QUADRANT_LABEL[q]}</span>;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <div className="mt-1 text-sm">{children}</div>
    </div>
  );
}

const CAT_STYLE: Record<string, string> = {
  early_opportunity: "border-blue-300 dark:border-blue-800", established: "border-emerald-300 dark:border-emerald-800",
  exit_warning: "border-amber-300 dark:border-amber-800", deterioration: "border-rose-300 dark:border-rose-800", neutral: "border-slate-300 dark:border-slate-700",
};

function lastTransition(r: SectorRow): RotationEvent | undefined {
  return [...(r.events ?? [])].reverse().find((e) => e.kind === "quadrant");
}

function makeColumns(q: string, colors: Record<string, string>): Column<SectorRow>[] {
  const m = (r: SectorRow) => r.metrics;
  return [
    { key: "rank", label: "#", type: "number", align: "right", firstDir: "asc", get: (r) => n(r.rank) },
    { key: "sector", label: "Sector", type: "text", firstDir: "asc", get: (r) => r.sector,
      render: (r) => <Link href={`/research/sectors/${r.ticker}?${q}`} className="font-medium hover:underline">
        <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: colors[r.ticker] }} />{r.sector}</Link> },
    { key: "etf", label: "ETF", type: "text", get: (r) => r.ticker },
    { key: "quadrant", label: "Quadrant", type: "enum", labels: QUADRANT_LABEL, get: (r) => r.quadrant ?? null, render: (r) => <QBadge q={r.quadrant} /> },
    { key: "score", label: "Rotation score", type: "number", align: "right", title: "Rotation Signal Score 0–100 (transparent; not a buy/sell signal)",
      get: (r) => n(r.score?.total), render: (r) => <b>{num(r.score?.total, 1)}</b> },
    { key: "ratio", label: "RS-Ratio", type: "number", align: "right", get: (r) => n(r.ratio), render: (r) => num(r.ratio, 2) },
    { key: "mom", label: "RS-Mom.", type: "number", align: "right", get: (r) => n(r.momentum), render: (r) => num(r.momentum, 2) },
    { key: "transition", label: "Latest transition", type: "text", get: (r) => lastTransition(r)?.label ?? null,
      render: (r) => { const e = lastTransition(r); return e ? <span className="text-xs">{e.label} <span className="text-slate-500">({e.sessions_ago}d ago)</span></span> : <span className="text-slate-400">—</span>; } },
    { key: "d10", label: "10D", type: "number", align: "right", get: (r) => n(m(r)?.change_10d_pct), render: (r) => <span className={signClass(m(r)?.change_10d_pct)}>{pct(m(r)?.change_10d_pct, 1)}</span> },
    { key: "d20", label: "20D", type: "number", align: "right", get: (r) => n(m(r)?.change_20d_pct), render: (r) => <span className={signClass(m(r)?.change_20d_pct)}>{pct(m(r)?.change_20d_pct, 1)}</span> },
    { key: "d50", label: "50D", type: "number", align: "right", get: (r) => n(m(r)?.change_50d_pct), render: (r) => <span className={signClass(m(r)?.change_50d_pct)}>{pct(m(r)?.change_50d_pct, 1)}</span> },
    { key: "rel", label: "vs bench. 20D", type: "number", align: "right", title: "20-day change minus the benchmark's 20-day change (percentage points)",
      get: (r) => n(m(r)?.relative_20d_pct), render: (r) => <span className={signClass(m(r)?.relative_20d_pct)}>{pct(m(r)?.relative_20d_pct, 1)}</span> },
    { key: "abs", label: "Abs. trend", type: "enum", title: "Close vs SMA 50 vs SMA 200", get: (r) => m(r)?.absolute_trend ?? null },
    { key: "rsi", label: "RSI 14", type: "number", align: "right", get: (r) => n(m(r)?.rsi14), render: (r) => num(m(r)?.rsi14, 1) },
    ...([10, 20, 50, 200] as const).map((p) => ({
      key: `sma${p}`, label: `SMA ${p}`, type: "number" as const, align: "right" as const, defaultHidden: p === 10 || p === 20,
      title: `${p}-day moving average; ▲ close above it, ▼ close below it`,
      get: (r: SectorRow) => n(m(r)?.[`sma${p}`]),
      render: (r: SectorRow) => { const a = m(r)?.[`above_sma${p}`]; return <span>{num(m(r)?.[`sma${p}`])} <span className={a ? "text-emerald-600" : a === false ? "text-rose-600" : ""}>{a ? "▲" : a === false ? "▼" : ""}</span></span>; },
    })),
    { key: "vol", label: "Volume trend", type: "number", align: "right", title: "20-day ÷ 50-day average volume",
      get: (r) => n(m(r)?.volume_trend), render: (r) => <span>{num(m(r)?.volume_trend, 2)} <span className="text-xs text-slate-500">{m(r)?.volume_trend_label}</span></span> },
    { key: "held", label: "Held", type: "bool", labels: { true: "held", false: "not held" }, get: (r) => !!r.held, render: (r) => (r.held ? "●" : ""), defaultHidden: true },
    { key: "status", label: "Data", type: "enum", get: (r) => r.status, defaultHidden: true },
  ];
}

function WeightsPanel({ data, onSaved }: { data: SectorsResp; onSaved: () => void }) {
  const [w, setW] = useState<Record<string, number>>(data.score.weights);
  const [err, setErr] = useState<ApiError | null>(null);
  const save = async (next: Record<string, number>) => {
    setErr(null);
    try {
      await apiFetch("/api/sectors/score-weights", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
      setW(next);
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    }
  };
  const total = Object.values(w).reduce((a, b) => a + b, 0);
  return (
    <div className="space-y-2 text-sm">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(data.score.labels).map(([k, label]) => (
          <label key={k} className="flex items-center justify-between gap-2 rounded border border-slate-200 px-2 py-1 dark:border-slate-800">
            <span>{label}</span>
            <span className="flex items-center gap-1">
              <input type="number" min={0} max={100} step={5} value={w[k]} aria-label={`Weight ${label}`}
                onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })}
                className="w-16 rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700" />
              <span className="w-10 text-right text-xs text-slate-500">{total ? Math.round((w[k] / total) * 100) : 0}%</span>
            </span>
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <button onClick={() => save(w)} className="rounded bg-slate-900 px-3 py-1 text-xs text-white dark:bg-slate-100 dark:text-slate-900">Save weights</button>
        <button onClick={() => save(data.score.defaults)} className="rounded border border-slate-300 px-3 py-1 text-xs dark:border-slate-700">Restore defaults</button>
      </div>
      <ErrorBox error={err} />
      <p className="text-xs text-slate-500">Weights are renormalised to 100%. Components without data are left out and the rest renormalised. Each sector&apos;s breakdown is on its page.</p>
    </div>
  );
}

export default function SectorRotationPage() {
  const router = useRouter();
  const [ctx, setCtx, ready] = useSectorContext();
  const q = sectorQuery(ctx);
  const { data, error, loading, reload } = useApi<SectorsResp>(ready ? `/api/sectors?${q}` : null);
  const [showWeights, setShowWeights] = useState(false);
  const hidden = useMemo(() => new Set(ctx.hidden), [ctx.hidden]);
  const colors = useMemo(() => Object.fromEntries((data?.rows ?? []).map((r) => r.ticker).sort().map((t, i) => [t, sectorColor(i)])), [data]);
  const columns = useMemo(() => makeColumns(q, colors), [q, colors]);
  const okRows = (data?.rows ?? []).filter((r) => r.status === "ok");
  const presets: Preset[] = [
    { label: "Leading", filters: { quadrant: { kind: "enum", in: ["leading"] } } },
    { label: "Improving", filters: { quadrant: { kind: "enum", in: ["improving"] } }, sort: [{ key: "mom", dir: "desc" }] },
    { label: "Weakening", filters: { quadrant: { kind: "enum", in: ["weakening"] } } },
    { label: "Lagging", filters: { quadrant: { kind: "enum", in: ["lagging"] } } },
    { label: "Recent transition", filters: { transition: { kind: "text", contains: "→" } } },
    { label: "Outperforming benchmark (20D)", filters: { rel: { kind: "number", min: 0 } }, sort: [{ key: "rel", dir: "desc" }] },
  ];
  const H = data?.highlights;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Sector Rotation</h1>
          <p className="text-xs text-slate-500">Where relative strength is rotating between {ctx.region === "eu" ? "European" : "US"} sectors:
            Lagging → Improving → Leading → Weakening.</p>
        </div>
        <RefreshAllButton onDone={reload} />
      </div>

      <Section title="Controls">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <span className="flex flex-col gap-1">Region
            <span className="inline-flex overflow-hidden rounded border border-slate-300 dark:border-slate-700" role="group" aria-label="Region">
              {([["us", "United States"], ["eu", "Europe"]] as const).map(([id, label]) => (
                <button key={id} aria-pressed={ctx.region === id}
                  onClick={() => setCtx({ region: id, benchmark: REGION_DEFAULT_BENCHMARK[id], hidden: [] })}
                  className={`px-2 py-1 text-xs ${ctx.region === id ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>{label}</button>
              ))}
            </span>
          </span>
          <label className="flex flex-col gap-1">Timeframe
            <select aria-label="Timeframe" className={sel} value={ctx.timeframe} onChange={(e) => setCtx({ timeframe: e.target.value })}>
              {Object.entries(data?.timeframes ?? { "10d": "10 trading days", "1m": "1 month", "3m": "3 months", "6m": "6 months", "12m": "12 months" })
                .map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">Benchmark
            <select aria-label="Benchmark" className={sel} value={ctx.benchmark} onChange={(e) => setCtx({ benchmark: e.target.value })}>
              {(data?.benchmarks ?? [ctx.benchmark]).map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">Data
            <select aria-label="Data source" className={sel} value={ctx.data} onChange={(e) => setCtx({ data: e.target.value as "auto" | "real" | "synthetic" })}>
              <option value="auto">Automatic (real if available)</option>
              <option value="real">Real ({ctx.region === "eu" ? "EODHD" : "Tiingo"})</option><option value="synthetic">Synthetic demo</option>
            </select>
          </label>
          <span className="flex flex-col gap-1">Trail
            <span className="inline-flex overflow-hidden rounded border border-slate-300 dark:border-slate-700" role="group" aria-label="Trail length">
              {[5, 10, 20].map((t) => (
                <button key={t} aria-pressed={ctx.trail === t} onClick={() => setCtx({ trail: t })}
                  className={`px-2 py-1 text-xs ${ctx.trail === t ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>{t} sessions</button>
              ))}
            </span>
          </span>
        </div>
      </Section>

      {!data && loading ? <Loading label="Calculating sector rotation…" /> : error ? <ErrorBox error={error} onRetry={reload} /> : !data ? null : (
        <>
          {data.data === "synthetic" && (
            <Warn>
              Showing the <b>synthetic demo</b>: generated prices for {data.benchmark} and the {data.rows.length} sector ETFs, not real market data.
              {data.data_requested === "auto" && (data.region.price_provider === "eodhd"
                ? <> Real data appears automatically once EODHD has enough history for EXSA and the sector ETFs (add <code>EODHD_API_KEY</code>, then Refresh data).</>
                : <> Real data appears automatically once Tiingo has enough history for SPY and the sector ETFs (add <code>TIINGO_API_KEY</code>, then Refresh data).</>)}
            </Warn>
          )}
          {data.status !== "ok" ? (
            <Section title="Not enough data">
              <Empty>
                {data.status === "no_benchmark" ? `No ${data.data} price history for ${data.benchmark} yet.` :
                  `Only ${data.aligned_bars} aligned trading days are available; this timeframe needs ${data.bars_needed}. Try a shorter timeframe.`}
                {" "}Nothing is estimated or filled in.
              </Empty>
            </Section>
          ) : (
            <>
              <Section title={`Market overview · ${data.benchmark}`} right={<ProvenanceBadge p={data.provenance} compact />}>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  <Card title={`Benchmark ${data.benchmark}`}>
                    {data.benchmark_info ? (
                      <>
                        <div><b className="num">{num(data.benchmark_info.close)}</b> · 20D <span className={signClass(data.benchmark_info.change_20d_pct)}>{pct(data.benchmark_info.change_20d_pct, 1)}</span></div>
                        <div className="mt-1 flex flex-wrap gap-1 text-xs">Trend {data.benchmark_info.absolute_trend ?? "—"} ·
                          <ClassBadge c={data.benchmark_info.classification.medium} label="medium" /><ClassBadge c={data.benchmark_info.classification.long} label="long" /></div>
                      </>
                    ) : "—"}
                  </Card>
                  <Card title="Sectors by quadrant">
                    <div className="grid grid-cols-2 gap-x-3">
                      {(["leading", "improving", "weakening", "lagging"] as Quadrant[]).map((x) => (
                        <span key={x}><QBadge q={x} /> <b>{data.quadrant_counts[x]}</b></span>
                      ))}
                    </div>
                  </Card>
                  <Card title="Highlights">
                    <div>Highest score: <b>{H?.most_attractive ? `${H.most_attractive.sector} (${H.most_attractive.ticker})` : "—"}</b></div>
                    <div>Strongest improving: <b>{H?.strongest_improving ? `${H.strongest_improving.sector} (${H.strongest_improving.ticker})` : "none"}</b></div>
                    <div>Lowest score: <b>{H?.weakest ? `${H.weakest.sector} (${H.weakest.ticker})` : "—"}</b></div>
                  </Card>
                  <Card title="Data">
                    <div>Latest bar: <b>{data.as_of}</b> ({data.aligned_bars} aligned days)</div>
                    <div>Last refresh: <b>{data.last_refresh ? fmtTimestamp(data.last_refresh.at) : data.data === "synthetic" ? "synthetic demo" : "—"}</b></div>
                    <div className="text-xs text-slate-500">Windows: {data.method.windows.window}d z-score, {data.method.windows.momentum_lag}d momentum</div>
                  </Card>
                </div>
              </Section>

              {data.region.id === "eu" && (
                <p className="text-xs text-slate-600 dark:text-slate-300">Sectors: {data.region.classification}. Prices in {data.region.currency}.</p>
              )}
              <Section title={`Relative Rotation Graph · ${data.region.name} · ${data.timeframes[data.timeframe]} · vs ${data.benchmark}`}
                right={<span className="text-xs text-amber-700 dark:text-amber-400">RRG-inspired approximation, not JdK&apos;s proprietary calculation</span>}>
                <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label="Show or hide sectors">
                  {okRows.map((r) => {
                    const off = hidden.has(r.ticker);
                    return (
                      <button key={r.ticker} aria-pressed={!off} onClick={() => setCtx({ hidden: off ? ctx.hidden.filter((t) => t !== r.ticker) : [...ctx.hidden, r.ticker] })}
                        className={`rounded-full border px-2 py-0.5 text-xs ${off ? "border-slate-300 text-slate-400 line-through dark:border-slate-700" : "border-transparent text-white"}`}
                        style={off ? undefined : { background: colors[r.ticker] }} title={r.sector}>{r.ticker}</button>
                    );
                  })}
                  <button className="text-xs underline" onClick={() => setCtx({ hidden: [] })}>all</button>
                  <button className="text-xs underline" onClick={() => setCtx({ hidden: okRows.map((r) => r.ticker) })}>none</button>
                </div>
                <RrgChart rows={data.rows} trail={ctx.trail} hidden={hidden} colors={colors} benchmark={data.benchmark}
                  onSelect={(t) => router.push(`/research/sectors/${t}?${q}`)} />
                <p className="mt-1 text-xs text-slate-500">
                  Right of centre = stronger than {data.benchmark}; above centre = relative strength improving. Sectors usually rotate clockwise.
                  Trails show the last {ctx.trail} sessions; the arrow shows the latest direction. Hover for readings, click for details.
                </p>
              </Section>

              <Section title="Sector ranking">
                <DataTable id="sector-ranking" rows={data.rows} columns={columns} rowKey={(r) => r.ticker} initialSort={[{ key: "rank", dir: "asc" }]}
                  presets={presets} rowClassName={(r) => (r.status !== "ok" ? "opacity-60" : "")} />
                <p className="mt-1 text-xs text-slate-500">
                  Absolute trend (is it rising?), relative performance (is it beating {data.benchmark}?) and relative momentum (is that improving?) are separate
                  columns: a falling sector can still be improving relative to the market. The Rotation Signal Score is a transparent summary, not a buy or sell signal.
                  <button className="ml-1 underline" onClick={() => setShowWeights(!showWeights)}>{showWeights ? "Hide" : "Adjust"} score weights</button>
                </p>
                {showWeights && <div className="mt-2"><WeightsPanel data={data} onSaved={reload} /></div>}
              </Section>

              <Section title="Rotation signals (last 20 sessions)">
                {data.events.length === 0 ? <Empty>No quadrant transitions or crossings in the last 20 sessions.</Empty> : (
                  <div className="grid gap-3 lg:grid-cols-2">
                    {["early_opportunity", "established", "exit_warning", "deterioration"].map((cat) => {
                      const evs = data.events.filter((e) => e.category === cat);
                      return (
                        <div key={cat} className={`rounded-md border-l-4 border-y border-r p-2 ${CAT_STYLE[cat]}`}>
                          <div className="text-sm font-semibold">{data.event_categories[cat]} <span className="text-xs font-normal text-slate-500">({evs.length})</span></div>
                          {evs.length === 0 ? <div className="text-xs text-slate-500">None</div> : (
                            <ul className="mt-1 space-y-0.5 text-xs">
                              {evs.slice(0, 8).map((e, i) => (
                                <li key={i}><Link href={`/research/sectors/${e.ticker}?${q}`} className="font-medium hover:underline">{e.sector} ({e.ticker})</Link>: {e.label}
                                  <span className="text-slate-500"> · {e.date} ({e.sessions_ago === 0 ? "today" : `${e.sessions_ago}d ago`})</span></li>
                              ))}
                            </ul>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                <p className="mt-2 text-xs text-slate-500">Early opportunity: Lagging → Improving, or RS-Momentum crossing above 100. Established: → Leading.
                  Exit warning: Leading → Weakening, or RS-Momentum falling below 100. Deterioration: → Lagging, or close crossing below SMA 50.
                  These are conditions to research. Check the absolute trend and the market (benchmark) trend before acting.
                  New signals also appear on the <Link href="/research/alerts" className="underline">Alerts</Link> page (choose which in Alerts → Settings → Sector rotation).</p>
              </Section>

              <Section title="Method and data notes">
                <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600 dark:text-slate-300">
                  {data.notes.map((x) => <li key={x}>{x}</li>)}
                  <li>RS = 100 × sector ÷ benchmark on common trading days. RS-Ratio = 100 + z-score of smoothed RS over {data.method.windows.window} days;
                    RS-Momentum = 100 + z-score of the {data.method.windows.momentum_lag}-day change in RS-Ratio. Version {data.method.version}.</li>
                </ul>
              </Section>
            </>
          )}
        </>
      )}
    </div>
  );
}
