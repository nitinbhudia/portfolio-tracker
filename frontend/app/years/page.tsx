"use client";

import { useState } from "react";

import { Columns } from "@/components/charts";
import { RangePicker, useRange } from "@/components/RangePicker";
import { ErrorBox, Loading, Note, Pct, Section, Usd } from "@/components/ui";
import { type Analysis, useApi } from "@/lib/api";
import { pct, usd } from "@/lib/format";
import { gainBars } from "@/lib/periods";
import { label } from "@/lib/range";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function YearsPage() {
  const q = useApi<Analysis>("/api/analysis");
  const [year, setYear] = useState<number | null>(null);
  const { range } = useRange();
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const a = q.data;
  const ys = a.years.filter((y) => y.sales > 0);
  const sel = year ?? ys[ys.length - 1]?.year ?? null;
  const cap = a.capital_entries > 0;
  const monthly = MONTHS.map((m, i) => {
    const k = `${sel}-${String(i + 1).padStart(2, "0")}`;
    const r = a.months.find((x) => x.month === k);
    return { key: k, label: m, value: r?.gain_usd ?? 0, lines: [["Realised gain", usd(r?.gain_usd ?? 0)], ["Sales", String(r?.sales ?? 0)]] as [string, string][] };
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Per year</h1>
        <RangePicker />
      </div>
      <Note tone="slate">{a.limits}</Note>
      <Section title={`Realised gain per ${gainBars(a.months, range, a.as_of).monthly ? "month" : "year"} (FIFO, USD) · ${label(range)}`}>
        <Columns label="Realised gain in the chosen period" fmt={(v) => usd(v)}
          data={gainBars(a.months, range, a.as_of).bars.map((b) => ({ key: b.key, label: b.label, value: b.value,
            lines: [[b.key, ""], ["Realised gain", usd(b.value)], ["Sales", String(b.sales)]] as [string, string][] }))} />
        <div className="mt-3 overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <thead><tr><th>Year</th><th className="text-right">Sales</th><th className="text-right">Won</th><th className="text-right">Realised gain</th><th className="text-right">Dividends</th>
              <th className="text-right">Cost of shares sold</th><th className="text-right">Avg money in shares</th><th className="text-right" title="(Realised gain + dividends) ÷ average money invested in shares (month-ends)">Gain ÷ money in shares</th>
              {cap && <th className="text-right" title="Realised gain ÷ (capital at the start of the year + money added during it)">Return on capital</th>}</tr></thead>
            <tbody>{a.years.map((y) => (
              <tr key={y.year} className={y.year === sel ? "bg-slate-50 dark:bg-slate-800/50" : ""}>
                <td><button className="underline" onClick={() => setYear(y.year)}>{y.year}</button></td><td className="text-right">{y.sales}</td>
                <td className="text-right">{pct(y.win_rate_pct, 0, false)}</td><td className="text-right font-medium"><Usd v={y.gain_usd} /></td><td className="text-right">{y.dividends_usd ? usd(y.dividends_usd) : ""}</td>
                <td className="text-right">{usd(y.cost_usd)}</td><td className="text-right">{usd(y.avg_invested_usd)}</td>
                <td className="text-right"><Pct v={y.return_on_invested_pct} /></td>{cap && <td className="text-right"><Pct v={y.return_on_capital_pct} /></td>}</tr>
            ))}</tbody>
          </table>
        </div>
        {!cap && <p className="mt-2 text-xs text-slate-500">Enter your deposits on the <a className="underline" href="/returns">Returns</a> page to add return on capital per year.</p>}
      </Section>
      {sel && (
        <Section title={`${sel} month by month`} right={
          <select aria-label="Year" className="rounded border border-slate-300 bg-transparent px-1.5 py-1 text-sm dark:border-slate-700" value={sel} onChange={(e) => setYear(Number(e.target.value))}>
            {ys.map((y) => <option key={y.year} value={y.year}>{y.year}</option>)}
          </select>}>
          <Columns label={`Realised gain per month in ${sel}`} fmt={(v) => usd(v)} data={monthly} height={200} />
          <div className="mt-3 overflow-x-auto">
            <table className="tbl num w-full text-xs">
              <thead><tr><th>Month</th>{monthly.map((m) => <th key={m.key} className="text-right">{m.label}</th>)}</tr></thead>
              <tbody><tr><td>Gain</td>{monthly.map((m) => <td key={m.key} className="text-right"><Usd v={m.value} /></td>)}</tr></tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  );
}
