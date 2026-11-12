"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { type Column, DataTable } from "@/components/research/DataTable";
import { PriceChart } from "@/components/research/PriceChart";
import { RelativeChart } from "@/components/research/RelativeChart";
import { RrgChart } from "@/components/research/RrgChart";
import { ScorePanel } from "@/components/research/ScorePanel";
import { Empty, ErrorBox, Loading, ProvenanceBadge, Section, Warn } from "@/components/research/ui";
import { WatchStar } from "@/components/research/WatchStar";
import { type Analysis, apiFetch, ApiError, type Constituent, type Quadrant, type SectorDetail, useApi } from "@/lib/research/api";
import { fmtTimestamp, num, pct, ratioLabel, signClass } from "@/lib/research/format";
import { describe, QUADRANT_BADGE, QUADRANT_LABEL } from "@/lib/research/rrg";
import { sectorQuery, useSectorContext } from "@/lib/research/sectorContext";

function QBadge({ q }: { q?: Quadrant | null }) {
  if (!q) return <span className="text-xs text-slate-400">—</span>;
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${QUADRANT_BADGE[q]}`}>{QUADRANT_LABEL[q]}</span>;
}

const constCols = (reload: () => void): Column<Constituent & { weight?: number | null; rank?: number | null }>[] => [
  { key: "watch", label: "★", type: "bool", get: (c) => c.watchlisted, render: (c) => <WatchStar listingId={c.listing_id} on={c.watchlisted} onChange={reload} /> },
  { key: "rank", label: "#", type: "number", align: "right", get: (c) => c.rank ?? null, defaultHidden: false },
  { key: "ticker", label: "Stock", type: "text", get: (c) => c.ticker,
    render: (c) => <Link href={`/research/analysis/${c.listing_id}`} className="font-medium hover:underline" title="Open the full technical analysis">{c.ticker}</Link> },
  { key: "name", label: "Name", type: "text", get: (c) => c.name, render: (c) => <span className="inline-block max-w-48 truncate align-bottom text-xs">{c.name}</span> },
  { key: "weight", label: "Weight", type: "number", align: "right", get: (c) => c.weight ?? null, render: (c) => (c.weight != null ? `${num(c.weight, 2)}%` : "—") },
  { key: "d20", label: "20D", type: "number", align: "right", get: (c) => c.change_20d_pct ?? null, render: (c) => <span className={signClass(c.change_20d_pct)}>{pct(c.change_20d_pct, 1)}</span> },
  { key: "rel", label: "vs sector 20D", type: "number", align: "right", get: (c) => c.relative_to_sector_20d_pct ?? null,
    render: (c) => <span className={signClass(c.relative_to_sector_20d_pct)}>{pct(c.relative_to_sector_20d_pct, 1)}</span> },
  { key: "ratio", label: "RS-Ratio vs sector", type: "number", align: "right", get: (c) => c.rs_ratio_vs_sector ?? null, render: (c) => num(c.rs_ratio_vs_sector, 2) },
  { key: "mom", label: "RS-Mom. vs sector", type: "number", align: "right", get: (c) => c.rs_momentum_vs_sector ?? null, render: (c) => num(c.rs_momentum_vs_sector, 2) },
  { key: "q", label: "Quadrant vs sector", type: "enum", labels: QUADRANT_LABEL, get: (c) => c.quadrant_vs_sector ?? null, render: (c) => <QBadge q={c.quadrant_vs_sector} /> },
  { key: "beats", label: "Stronger than sector", type: "bool", labels: { true: "yes", false: "no" }, get: (c) => c.beats_sector ?? null,
    render: (c) => (c.beats_sector ? <span className="text-emerald-600">yes</span> : c.beats_sector === false ? "no" : "—") },
  { key: "held", label: "Held", type: "bool", labels: { true: "held", false: "not held" }, get: (c) => c.held, render: (c) => (c.held ? "●" : "") },
];

export default function SectorDetailPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [ctx, , ready] = useSectorContext();
  const q = sectorQuery(ctx);
  const { data: d, error, loading, reload } = useApi<SectorDetail>(ready ? `/api/sectors/${ticker}?${q}` : null);
  const { data: a } = useApi<Analysis>(d?.listing_id ? `/api/listings/${d.listing_id}/analysis` : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const cols = useMemo(() => constCols(reload), [reload]);

  const act = async (label: string, path: string) => {
    setBusy(label);
    setErr(null);
    setMsg(null);
    try {
      const r = await apiFetch<{ results: { ticker: string; status: string; message?: string }[] }>(path, { method: "POST" });
      const failed = r.results.filter((x) => x.status === "failed");
      setMsg(`${r.results.length - failed.length} done${failed.length ? `, ${failed.length} failed (${failed[0].ticker}: ${failed[0].message})` : ""}.`);
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!d) return <Loading label={loading ? "Analysing the sector…" : "Loading…"} />;
  const r = d.row;
  const m = r.metrics;
  const sc = r.score;
  const topRows = d.holdings.top10.filter((h) => h.analysis && h.analysis.status === "ok")
    .map((h) => ({ ...(h.analysis as Constituent), weight: h.weight_pct, rank: h.rank }));
  const inApp = d.constituents_in_app.filter((c) => c.status === "ok").map((c) => ({ ...c, weight: null, rank: null }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <Link href="/research/sectors" className="text-xs text-blue-600 underline dark:text-blue-400">← Sector Rotation{d.region ? ` (${d.region.name})` : ""}</Link>
          <h1 className="text-xl font-semibold">{d.sector} <span className="text-sm font-normal text-slate-500">{d.ticker} · {d.etf_name} · vs {d.benchmark} · {d.timeframes[d.timeframe]}</span></h1>
          <ProvenanceBadge p={d.provenance} />
        </div>
        <div className="flex items-center gap-2">
          <QBadge q={r.quadrant} />
          {sc?.total != null && <span className="text-sm">Rotation score <b>{num(sc.total, 1)}</b></span>}
          {d.listing_id && <Link href={`/research/analysis/${d.listing_id}`} className="rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700">Full analysis →</Link>}
        </div>
      </div>
      {d.data === "synthetic" && <Warn>Synthetic demo data: these prices are generated, not real.</Warn>}
      {r.status !== "ok" ? (
        <Warn>{r.status === "rrg_unavailable" ? r.reason : `Not enough price history for this sector (${r.bars_available} days).`}</Warn>
      ) : (
        <>
          <Section title="Three separate readings">
            <div className="grid gap-2 sm:grid-cols-3 text-sm">
              <div className="rounded border border-slate-200 p-2 dark:border-slate-800">
                <div className="text-xs font-semibold uppercase text-slate-500">Absolute performance</div>
                <div>20D <b className={signClass(m?.change_20d_pct)}>{pct(m?.change_20d_pct, 1)}</b> · 50D <span className={signClass(m?.change_50d_pct)}>{pct(m?.change_50d_pct, 1)}</span></div>
                <div className="text-xs">Trend: {m?.absolute_trend ?? "—"} (close vs SMA 50 vs SMA 200)</div>
              </div>
              <div className="rounded border border-slate-200 p-2 dark:border-slate-800">
                <div className="text-xs font-semibold uppercase text-slate-500">Relative performance vs {d.benchmark}</div>
                <div>20D <b className={signClass(m?.relative_20d_pct)}>{pct(m?.relative_20d_pct, 1)}</b> points · RS-Ratio <b>{num(r.ratio, 2)}</b></div>
                <div className="text-xs">{d.benchmark} 20D: {pct(m?.benchmark_change_20d_pct, 1)}</div>
              </div>
              <div className="rounded border border-slate-200 p-2 dark:border-slate-800">
                <div className="text-xs font-semibold uppercase text-slate-500">Relative momentum</div>
                <div>RS-Momentum <b>{num(r.momentum, 2)}</b> · <QBadge q={r.quadrant} /></div>
                <div className="text-xs">Volume trend {num(m?.volume_trend, 2)} ({m?.volume_trend_label ?? "—"})</div>
              </div>
            </div>
            <p className="mt-2 text-sm">In short: {d.sector} is {describe(m?.absolute_trend, m?.relative_20d_pct, r.quadrant)}.</p>
          </Section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Section title={`Rotation trail (last ${d.trail?.length ?? 0} sessions)`}>
              <RrgChart rows={[{ ...r, trail: d.trail }]} trail={60} colors={{ [r.ticker]: "#2563eb" }} height={420} benchmark={d.benchmark} />
            </Section>
            <Section title={`Relative performance vs ${d.benchmark} (rebased to 100)`}>
              {d.relative_chart && <RelativeChart {...d.relative_chart} sectorLabel={d.ticker} benchLabel={d.benchmark} />}
              <p className="mt-1 text-xs text-slate-500">The orange line rises when {d.ticker} beats {d.benchmark}, even if both fall.</p>
            </Section>
          </div>

          {sc && (
            <Section title="Rotation Signal Score: how it's built">
              <div className="overflow-x-auto">
                <table className="tbl num w-full text-xs">
                  <thead><tr><th>Component</th><th>Rule</th><th className="text-right">Input</th><th className="text-right">Points</th><th className="text-right">Weight</th><th className="text-right">Contribution</th></tr></thead>
                  <tbody>
                    {Object.entries(sc.components).map(([k, c]) => (
                      <tr key={k}><td>{d.score_labels[k] ?? k}</td><td className="min-w-48 text-slate-500" style={{ whiteSpace: "normal" }}>{c.rule}</td>
                        <td className="text-right">{typeof c.input === "number" ? num(c.input, 2) : c.input}</td><td className="text-right">{num(c.points, 0)}</td>
                        <td className="text-right">{c.effective_weight != null ? `${num(c.effective_weight * 100, 0)}%` : "—"}</td><td className="text-right">{num(c.contribution, 1)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {sc.excluded && sc.excluded.length > 0 && <p className="mt-1 text-xs text-amber-600">Left out (no data): {sc.excluded.join(", ")}.</p>}
            </Section>
          )}

          {(r.events?.length ?? 0) > 0 && (
            <Section title="Recent rotation signals (20 sessions)">
              <ul className="space-y-0.5 text-sm">
                {[...(r.events ?? [])].reverse().map((e, i) => (
                  <li key={i}><b>{d.event_categories[e.category]}</b>: {e.label} <span className="text-xs text-slate-500">· {e.date} · RS-Ratio {num(e.ratio, 2)}, RS-Momentum {num(e.momentum, 2)}</span></li>
                ))}
              </ul>
            </Section>
          )}
        </>
      )}

      {a && a.status === "ok" && (
        <>
          <Section title={`${d.ticker} price · SMAs · Fibonacci · RSI · MACD`} right={<Link href={`/research/analysis/${d.listing_id}`} className="text-xs underline">Open full analysis</Link>}>
            <PriceChart a={a} />
            {a.fibonacci?.status === "ok" && (
              <p className="mt-1 text-xs text-slate-500">Fibonacci from the last confirmed swings ({a.fibonacci.direction} swing): nearest level {ratioLabel(a.fibonacci.nearest.ratio)} at
                {" "}{num(a.fibonacci.nearest.price)} ({pct(a.fibonacci.nearest.distance_pct, 1)} away). Levels are reference points, not guaranteed support or resistance.</p>
            )}
          </Section>
          <Section title="Technical scores (existing engine)"><ScorePanel scores={a.scores!} /></Section>
        </>
      )}

      <Section title="Top 10 holdings by weight" right={<span className="text-xs text-slate-500">{d.holdings.source}{d.holdings.as_of && <> · as of {d.holdings.as_of}</>}</span>}>
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
          <button disabled={!!busy} onClick={() => act("Updating holdings from State Street…", `/api/sectors/holdings/refresh?ticker=${d.ticker}`)}
            className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-50 dark:border-slate-700">{d.holdings.count ? "Update holdings" : "Download holdings"}</button>
          {d.data === "real" && d.holdings.missing_prices.length > 0 && (
            <button disabled={!!busy} onClick={() => act("Downloading constituent prices from Tiingo…", `/api/sectors/${d.ticker}/constituents/download`)}
              className="rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">
              Download prices for {d.holdings.missing_prices.length} holdings</button>
          )}
          {busy && <span className="text-amber-600" role="status">{busy}</span>}
          {msg && <span className="text-xs text-slate-600 dark:text-slate-300">{msg}</span>}
          {d.holdings.fetched_at && <span className="text-xs text-slate-500">downloaded {fmtTimestamp(d.holdings.fetched_at)}</span>}
        </div>
        <ErrorBox error={err} />
        {d.holdings.count === 0 ? <Empty>No holdings downloaded yet. Holdings come from State Street&apos;s daily file for {d.ticker}.</Empty> : (
          <>
            <div className="overflow-x-auto">
              <table className="tbl num w-full text-xs">
                <thead><tr><th>#</th><th>Holding</th><th>Ticker</th>{d.region?.id === "eu" && <th>Exchange</th>}<th className="text-right">Weight</th><th className="text-right">20D</th><th className="text-right">RS-Ratio vs sector</th><th>Analysis</th></tr></thead>
                <tbody>
                  {d.holdings.top10.map((h) => (
                    <tr key={h.rank}><td>{h.rank}</td><td>{h.name}</td><td>{h.ticker ?? "—"}</td>{d.region?.id === "eu" && <td className="text-xs">{h.exchange ?? "—"}</td>}<td className="text-right">{num(h.weight_pct, 2)}%</td>
                      <td className="text-right"><span className={signClass(h.analysis?.change_20d_pct)}>{pct(h.analysis?.change_20d_pct, 1)}</span></td>
                      <td className="text-right">{num(h.analysis?.rs_ratio_vs_sector, 2)}</td>
                      <td>{h.analysis ? <Link href={`/research/analysis/${h.analysis.listing_id}`} className="underline">open</Link> :
                        <span className="text-slate-400">{h.price_supported === false ? "exchange not supported yet" : d.data === "real" ? "no prices yet" : "synthetic mode"}</span>}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.holdings.unsupported_exchanges && d.holdings.unsupported_exchanges.length > 0 && (
              <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">Prices aren&apos;t available yet for holdings on: {d.holdings.unsupported_exchanges.join(", ")}.
                Supported: Xetra, London, Euronext Amsterdam and Paris, SIX (via EODHD).</p>
            )}
            <p className="mt-1 text-xs text-slate-500">Top 10 = {num(d.holdings.top10_weight_pct, 1)}% of the fund ({d.holdings.count} holdings).
              {d.data === "synthetic" && " Weights are real (State Street); prices for them are only used in real-data mode, so real weights are never combined with synthetic prices."}</p>
          </>
        )}
      </Section>

      {(topRows.length > 0 || inApp.length > 0) && (
        <Section title={topRows.length ? "Constituents: strength against the sector" : `Instruments in this app classified as ${d.sector}`}>
          <DataTable id="sector-constituents" rows={topRows.length ? topRows : inApp} columns={cols} rowKey={(c) => c.listing_id}
            initialSort={[{ key: "ratio", dir: "desc" }]}
            presets={[{ label: "Stronger than sector", filters: { beats: { kind: "bool", is: true } } }, { label: "My holdings", filters: { held: { kind: "bool", is: true } } }]} />
          <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
            <div><b>Strongest (20D):</b> {d.strongest.map((c) => `${c.ticker} ${pct(c.change_20d_pct, 1)}`).join(", ") || "—"}</div>
            <div><b>Weakest (20D):</b> {d.weakest.map((c) => `${c.ticker} ${pct(c.change_20d_pct, 1)}`).join(", ") || "—"}</div>
            <div><b>Stronger than {d.ticker}:</b> {d.beating_sector.map((c) => c.ticker).join(", ") || "none"}</div>
          </div>
          <p className="mt-1 text-xs text-slate-500">&quot;Stronger than sector&quot; = the stock&apos;s RS-Ratio against {d.ticker} is above 100 (same approximation, same timeframe).
            Open a stock for Fibonacci levels, moving averages and scores to judge an entry.</p>
        </Section>
      )}

      <Section title="Notes"><ul className="list-disc space-y-1 pl-5 text-xs text-slate-600 dark:text-slate-300">{d.notes.map((x) => <li key={x}>{x}</li>)}</ul></Section>
    </div>
  );
}
