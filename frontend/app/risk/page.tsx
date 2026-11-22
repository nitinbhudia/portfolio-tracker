"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { Lines, RankedBars, Tooltip, type Tip, useWidth } from "@/components/charts";
import { type Column, DataTable } from "@/components/DataTable";
import { ErrorBox, Loading, Note, Section, Stat, Usd, input } from "@/components/ui";
import { useApi } from "@/lib/api";
import { num, pct, usd } from "@/lib/format";

type Share = { label: string; value_usd: number; pct: number | null };
type PosRisk = { key: string; label: string; weight_pct: number; value_usd: number; vol_pct: number; beta: number | null;
  max_drawdown_pct: number; from_high_pct: number; risk_share_pct: number | null };
type Corr = { labels: string[]; matrix: number[][]; average: number; most: { a: string; b: string; corr: number }[]; least: { a: string; b: string; corr: number }[] };
type Market = {
  status: "ok" | "no_data"; message?: string; window?: string; start?: string; end?: string; days?: number; covered_pct?: number;
  missing?: { key: string; label: string; pct: number; reason: string }[];
  volatility_pct?: number; market_volatility_pct?: number | null; max_drawdown_pct?: number; drawdown_peak?: string; drawdown_trough?: string;
  current_drawdown_pct?: number; market_max_drawdown_pct?: number | null; var95_pct?: number; var95_usd?: number; es95_pct?: number; es95_usd?: number;
  worst_day_pct?: number; worst_day?: string; worst_month_pct?: number | null; beta?: number | null; market_correlation?: number | null;
  positions?: PosRisk[]; drawdown?: { dates: string[]; portfolio: number[]; market: number[] | null }; correlation?: Corr | null;
  stress?: { market_pct: number; change_usd: number; change_pct: number | null }[] | null;
};
type RiskResp = {
  as_of: string; window: string; windows: string[]; benchmark: string | null; unpriced: string[]; sectors_set: number; positions: number;
  thresholds: { large_pct: number; very_large_pct: number };
  concentration: { total_usd: number; positions: number; effective_n: number | null; largest_pct: number | null; largest: string | null;
    top5_pct: number; top10_pct: number; large: { key: string; label: string; pct: number; very_large: boolean }[];
    weights: { key: string; label: string; value_usd: number; pct: number }[] };
  exposure: { sector: Share[]; currency: Share[]; broker: Share[] };
  market: Market;
};

const WINDOW_LABEL: Record<string, string> = { "6m": "6 months", "1y": "1 year", "3y": "3 years" };

/** Correlation colour: grey at 0, toward blue for moving together (+1), toward red for moving apart (−1). */
function corrColor(c: number): string {
  const p = Math.round(Math.min(1, Math.abs(c)) * 100);
  return `color-mix(in oklab, ${c >= 0 ? "var(--viz-1)" : "var(--viz-neg)"} ${p}%, var(--viz-mid))`;
}

function CorrGrid({ c }: { c: Corr }) {
  const wrap = useRef<HTMLDivElement>(null);
  const W = useWidth(wrap, 520);
  const [tip, setTip] = useState<Tip>(null);
  const n = c.labels.length;
  const labelW = Math.min(150, Math.max(90, W * 0.28));
  const cell = Math.max(14, Math.min(36, (W - labelW - 4) / n));
  const H = n * cell + 2;
  return (
    <div ref={wrap} className="relative">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="How closely your biggest positions moved together (correlation of daily returns)"
        onPointerLeave={() => setTip(null)}>
        {c.labels.map((l, i) => (
          <text key={l} x={labelW - 6} y={i * cell + cell / 2} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--viz-ink2)">
            {l.length > 20 ? l.slice(0, 19) + "…" : l}</text>
        ))}
        {c.matrix.map((row, i) => row.map((v, j) => (
          <rect key={`${i}-${j}`} x={labelW + j * cell + 1} y={i * cell + 1} width={cell - 2} height={cell - 2} rx={2}
            fill={i === j ? "var(--viz-grid)" : corrColor(v)}
            onPointerEnter={() => setTip(i === j ? null : { x: labelW + j * cell + cell / 2, y: i * cell, lines: [[`${c.labels[i]} × ${c.labels[j]}`, ""], ["Correlation", num(v, 2)]] })} />
        )))}
      </svg>
      <Tooltip tip={tip} />
      <div className="mt-2 flex items-center gap-2 text-xs text-slate-500" aria-hidden>
        <span>−1 opposite</span>
        <span className="h-2.5 w-40 rounded" style={{ background: "linear-gradient(90deg, var(--viz-neg), var(--viz-mid), var(--viz-1))" }} />
        <span>+1 together</span>
      </div>
    </div>
  );
}

const TOP = 12;

/** Every position by weight: the top 12 at first, "Show all" for the rest, and a search box that finds any of them
 * (bars keep the same scale, and each keeps its rank in the whole portfolio). */
function ConcentrationBars({ weights }: { weights: { key: string; label: string; value_usd: number; pct: number }[] }) {
  const [all, setAll] = useState(false);
  const [text, setText] = useState("");
  const t = text.trim().toLowerCase();
  const ranked = weights.map((w, i) => ({ label: `${i + 1}. ${w.label}`, name: w.label, value: w.value_usd, pct: w.pct }));
  const rows = t ? ranked.filter((r) => r.name.toLowerCase().includes(t)) : ranked;
  const limit = all || t ? rows.length : TOP;
  const hidden = rows.length - Math.min(limit, rows.length);
  const hiddenUsd = rows.slice(limit).reduce((a, r) => a + r.value, 0);
  const hiddenPct = rows.slice(limit).reduce((a, r) => a + r.pct, 0);
  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <input type="search" aria-label="Search positions" placeholder={`Search ${weights.length} positions…`} value={text}
          onChange={(e) => setText(e.target.value)} className={`${input} w-56 max-w-full`} />
        {t && <span className="text-xs text-slate-500" role="status">{rows.length} of {weights.length} match
          {rows.length > 0 && <> · {usd(rows.reduce((a, r) => a + r.value, 0))} · {pct(rows.reduce((a, r) => a + r.pct, 0), 1, false)}</>}</span>}
      </div>
      {rows.length === 0 ? <p className="text-sm text-slate-500">No position matches &ldquo;{text}&rdquo;.</p>
        : <RankedBars rows={rows} fmt={(v) => usd(v)} max={limit} scaleMax={weights[0]?.value_usd} hideRest />}
      {!t && weights.length > TOP && (
        <button className="mt-2 text-xs underline" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? `Show the top ${TOP} only` : `Show all ${weights.length} (${hidden} more: ${usd(hiddenUsd)} · ${pct(hiddenPct, 1, false)})`}</button>
      )}
    </>
  );
}

export default function RiskPage() {
  const [win, setWin] = useState("1y");
  const q = useApi<RiskResp>(`/api/risk?window=${win}`);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  const d = q.data;
  const m = d?.market;
  const c = d?.concentration;
  const cols: Column<PosRisk>[] = [
    { key: "stock", label: "Stock", type: "text", get: (r) => r.label },
    { key: "w", label: "Weight", type: "number", align: "right", firstDir: "desc", get: (r) => r.weight_pct, render: (r) => pct(r.weight_pct, 1, false) },
    { key: "risk", label: "Share of risk", type: "number", align: "right", firstDir: "desc", get: (r) => r.risk_share_pct,
      title: "How much of the portfolio's day-to-day swings come from this position (adds up to 100%)",
      render: (r) => <span className={r.risk_share_pct !== null && r.risk_share_pct > r.weight_pct * 1.5 ? "font-semibold" : ""}>{pct(r.risk_share_pct, 1, false)}</span> },
    { key: "vol", label: "Volatility", type: "number", align: "right", firstDir: "desc", get: (r) => r.vol_pct, title: "Annualised", render: (r) => pct(r.vol_pct, 0, false) },
    { key: "beta", label: "Beta", type: "number", align: "right", firstDir: "desc", get: (r) => r.beta, title: "Moves this many times the S&P 500", render: (r) => num(r.beta, 2) },
    { key: "mdd", label: "Max drawdown", type: "number", align: "right", get: (r) => r.max_drawdown_pct, render: (r) => pct(r.max_drawdown_pct, 0) },
    { key: "high", label: "From 1-year high", type: "number", align: "right", get: (r) => r.from_high_pct, render: (r) => pct(r.from_high_pct, 0) },
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Risk</h1>
        <div role="group" aria-label="Look-back window" className="flex overflow-hidden rounded border border-slate-300 text-sm dark:border-slate-700">
          {(d?.windows ?? ["6m", "1y", "3y"]).map((w) => (
            <button key={w} aria-pressed={win === w} onClick={() => setWin(w)}
              className={`px-2.5 py-1 ${win === w ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>{w.toUpperCase()}</button>
          ))}
        </div>
      </div>
      {!d || !m || !c ? <Loading /> : (
        <>
          <p className="text-sm text-slate-600 dark:text-slate-300">The risk of what you hold today ({c.positions} stocks, {usd(c.total_usd)} on {d.as_of}): today&apos;s
            positions replayed over the last {WINDOW_LABEL[d.window]} of daily prices in USD. It isn&apos;t your past performance (trades in that time are ignored),
            and the past doesn&apos;t promise the future.</p>
          {m.status === "ok" && m.missing && m.missing.length > 0 && (
            <Note>Market risk covers {pct(m.covered_pct, 0, false)} of your money: {m.missing.map((x) => `${x.label} (${pct(x.pct, 1, false)}, ${x.reason})`).join("; ")}.
              {" "}Add daily prices on <Link className="underline" href="/history">Data ▾ Price history</Link>.</Note>
          )}
          {m.status !== "ok" && <Note>{m.message} Concentration and exposure below don&apos;t need daily prices.</Note>}
          {m.status === "ok" && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Volatility (a year)" value={pct(m.volatility_pct, 1, false)}
                sub={m.market_volatility_pct != null ? <>S&amp;P 500: {pct(m.market_volatility_pct, 1, false)} · typical yearly swing</> : "typical yearly swing"} />
              <Stat label="Deepest fall" value={<span className="text-rose-700 dark:text-rose-400">{pct(m.max_drawdown_pct, 1)}</span>}
                sub={<>{m.drawdown_peak} → {m.drawdown_trough}{m.market_max_drawdown_pct != null && <> · S&amp;P 500 {pct(m.market_max_drawdown_pct, 1)}</>}</>} />
              <Stat label="Bad day (1 in 20)" value={<span className="text-rose-700 dark:text-rose-400">−{usd(m.var95_usd)}</span>}
                sub={<>{pct(m.var95_pct, 1, false)} or more on 1 day in 20; those days average −{usd(m.es95_usd)}</>} />
              <Stat label="Beta to the S&P 500" value={num(m.beta, 2)}
                sub={m.beta != null ? <>moves about {num(m.beta, 1)}× the market · correlation {num(m.market_correlation, 2)}</> : "no S&P 500 prices yet"} />
              <Stat label="Largest position" value={pct(c.largest_pct, 1, false)} sub={c.largest} />
              <Stat label="Effective positions" value={num(c.effective_n, 1)}
                sub={<>of {c.positions} held: you&apos;re as spread as {num(c.effective_n, 0)} equal positions · top 5 = {pct(c.top5_pct, 0, false)}</>} />
              <Stat label="Worst day" value={<span className="text-rose-700 dark:text-rose-400">{pct(m.worst_day_pct, 1)}</span>} sub={m.worst_day} />
              <Stat label="Worst month (21 days)" value={<span className="text-rose-700 dark:text-rose-400">{pct(m.worst_month_pct, 1)}</span>}
                sub={<>now {pct(m.current_drawdown_pct, 1)} from the high</>} />
            </div>
          )}
          {m.status !== "ok" && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Largest position" value={pct(c.largest_pct, 1, false)} sub={c.largest} />
              <Stat label="Effective positions" value={num(c.effective_n, 1)} sub={<>of {c.positions} held · top 5 = {pct(c.top5_pct, 0, false)}</>} />
              <Stat label="Top 10" value={pct(c.top10_pct, 0, false)} sub="of your money" />
            </div>
          )}

          {m.stress && (
            <Section title="If the S&P 500 fell">
              <table className="tbl num w-full max-w-xl text-sm">
                <thead><tr><th>S&amp;P 500</th><th className="text-right">Your portfolio (estimate)</th><th className="text-right">%</th></tr></thead>
                <tbody>{m.stress.map((s) => (
                  <tr key={s.market_pct}><td>{pct(s.market_pct, 0)}</td><td className="text-right"><Usd v={s.change_usd} /></td><td className="text-right">{pct(s.change_pct, 1)}</td></tr>
                ))}</tbody>
              </table>
              <p className="mt-2 text-xs text-slate-500">Each position moves by its own beta over the last {WINDOW_LABEL[d.window]}; positions without daily prices
                move with the market (beta 1). A rough guide: in real sell-offs correlations rise and single stocks can fall much further.</p>
            </Section>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="Concentration">
              {c.large.length > 0 && <p className="mb-2 text-sm">
                {c.large.map((x, i) => <span key={x.key}>{i > 0 && ", "}<b>{x.label}</b> {pct(x.pct, 1, false)}{x.very_large && " (over " + d.thresholds.very_large_pct + "%)"}</span>)}
                {" "}{c.large.length === 1 ? "is" : "are"} over {d.thresholds.large_pct}% of the portfolio each.</p>}
              <ConcentrationBars weights={c.weights} />
            </Section>
            <Section title="Sectors">
              <RankedBars rows={d.exposure.sector.map((s) => ({ label: s.label, value: s.value_usd, pct: s.pct }))} fmt={(v) => usd(v)} />
              {d.sectors_set < d.positions && <p className="mt-2 text-xs text-slate-500">{d.positions - d.sectors_set} stocks have no sector yet: set them on{" "}
                <Link className="underline" href="/stocks">Data ▾ Names</Link>.</p>}
            </Section>
            <Section title="Currencies">
              <RankedBars rows={d.exposure.currency.map((s) => ({ label: s.label, value: s.value_usd, pct: s.pct }))} fmt={(v) => usd(v)} />
              <p className="mt-2 text-xs text-slate-500">Money in other currencies also moves with the exchange rate against the dollar.</p>
            </Section>
            <Section title="Brokers">
              <RankedBars rows={d.exposure.broker.map((s) => ({ label: s.label, value: s.value_usd, pct: s.pct }))} fmt={(v) => usd(v)} />
            </Section>
          </div>

          {m.status === "ok" && m.drawdown && (
            <Section title={`Fall from the high (%) · last ${WINDOW_LABEL[d.window]}`}>
              <Lines dates={m.drawdown.dates} label="How far today's holdings and the S&P 500 were below their previous high, each day (%)"
                fmt={(v) => `${v.toFixed(1)}%`}
                series={[{ name: "Your holdings", color: "var(--viz-1)", values: m.drawdown.portfolio },
                  ...(m.drawdown.market ? [{ name: "S&P 500", color: "var(--viz-2)", values: m.drawdown.market }] : [])]} />
            </Section>
          )}

          {m.status === "ok" && m.positions && (
            <Section title="Where the risk comes from">
              <p className="mb-2 text-xs text-slate-500">Share of risk: how much of the portfolio&apos;s day-to-day swings each position causes, given its size, its own
                swings and how it moves with the others. Bold = well above its weight.</p>
              <DataTable id="pt-risk" rows={m.positions} columns={cols} rowKey={(r) => r.key} initialSort={[{ key: "risk", dir: "desc" }]} exportName="risk" compact />
            </Section>
          )}

          {m.status === "ok" && m.correlation && (
            <Section title={`Moving together · your ${m.correlation.labels.length} biggest positions`}>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                <CorrGrid c={m.correlation} />
                <div className="space-y-3 text-sm">
                  <p>Average correlation between your stocks: <b className="num">{num(m.correlation.average, 2)}</b>
                    <span className="text-slate-500"> (0 = unrelated, 1 = always together). The higher it is, the less spreading over many stocks helps.</span></p>
                  <div><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Most alike</h3>
                    <ul className="mt-1 space-y-0.5">{m.correlation.most.map((p) => <li key={p.a + p.b}>{p.a} &amp; {p.b} <b className="num">{num(p.corr, 2)}</b></li>)}</ul></div>
                  <div><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Most different</h3>
                    <ul className="mt-1 space-y-0.5">{m.correlation.least.map((p) => <li key={p.a + p.b}>{p.a} &amp; {p.b} <b className="num">{num(p.corr, 2)}</b></li>)}</ul></div>
                </div>
              </div>
            </Section>
          )}
          {d.unpriced.length > 0 && <p className="text-xs text-slate-500">Not included (no price): {d.unpriced.join(", ")}.</p>}
        </>
      )}
    </div>
  );
}
