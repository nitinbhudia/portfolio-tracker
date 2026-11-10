"use client";

import { ErrorBox, Loading, Note, Pct, Section, Stat, Usd } from "@/components/ui";
import { type Analysis, type BriefSale, useApi } from "@/lib/api";
import { num, pct } from "@/lib/format";

function SaleList({ rows }: { rows: BriefSale[] }) {
  return (
    <div className="overflow-x-auto"><table className="tbl num w-full text-sm">
      <tbody>{rows.map((s) => (
        <tr key={s.id}><td>{s.date}</td><td className="whitespace-normal">{s.stock}</td><td className="text-right"><Usd v={s.gain_usd} /></td>
          <td className="text-right"><Pct v={s.gain_pct} /></td><td className="text-right text-xs text-slate-500">{num(s.days_held, 0)} d</td></tr>
      ))}</tbody>
    </table></div>
  );
}

export default function StatsPage() {
  const q = useApi<Analysis>("/api/analysis");
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const s = q.data.statistics;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Trading statistics</h1>
      <p className="text-xs text-slate-500">All {s.sales} sales with a FIFO gain in USD{s.not_computed ? ` (${s.not_computed} without a USD value are left out)` : ""}. Before fees.</p>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Win rate" value={pct(s.win_rate_pct, 1, false)} sub={`${s.wins} won · ${s.losses} lost${s.breakeven ? ` · ${s.breakeven} even` : ""}`} />
        <Stat label="Profit factor" value={num(s.profit_factor, 2)} sub={<>gains <Usd v={s.gross_wins_usd} /> ÷ losses <Usd v={-s.gross_losses_usd} /></>} />
        <Stat label="Average win / loss" value={<><Usd v={s.avg_win_usd} /> / <Usd v={s.avg_loss_usd} /></>} sub={<><Pct v={s.avg_win_pct} /> / <Pct v={s.avg_loss_pct} /> on cost</>} />
        <Stat label="Average per sale" value={<Usd v={s.expectancy_usd} />} sub="net gain ÷ number of sales" />
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Days held, winners" value={num(s.avg_days_winners, 0)} sub="average, share-weighted" />
        <Stat label="Days held, losers" value={num(s.avg_days_losers, 0)} sub="average, share-weighted" />
        <Stat label="Currency effect" value={<Usd v={s.fx_effect_usd} />} sub="part of realised gains due to exchange rates" />
        <Stat label="Net realised" value={<Usd v={s.net_usd} />} />
      </div>
      <Section title="By holding period">
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <thead><tr><th>Held</th><th className="text-right">Sales</th><th className="text-right">Won</th><th className="text-right">Gain</th><th className="text-right">Return on cost</th></tr></thead>
            <tbody>{s.by_holding_period.map((b) => (
              <tr key={b.label}><td>{b.label}</td><td className="text-right">{b.sales}</td><td className="text-right">{pct(b.win_rate_pct, 0, false)}</td>
                <td className="text-right"><Usd v={b.gain_usd} /></td><td className="text-right"><Pct v={b.return_pct} /></td></tr>
            ))}</tbody>
          </table>
        </div>
        <p className="mt-1 text-xs text-slate-500">Holding period of a sale = share-weighted days since the FIFO purchases it was matched to.</p>
      </Section>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Best sales"><SaleList rows={s.best_sales} /></Section>
        <Section title="Worst sales"><SaleList rows={s.worst_sales} /></Section>
      </div>
      <Note tone="slate">Best and worst stocks overall (realised + unrealised) are on the <a className="underline" href="/by-stock">Per stock</a> page, sorted by total gain.</Note>
    </div>
  );
}
