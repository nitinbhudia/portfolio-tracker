"use client";

import { type Column, DataTable } from "@/components/DataTable";
import { ErrorBox, Loading, Note, Pct, Section, Stat, Usd } from "@/components/ui";
import { type Position, type PositionsResp, useApi } from "@/lib/api";
import { num, pct, qty, usd } from "@/lib/format";

export default function PositionsPage() {
  const q = useApi<PositionsResp>("/api/positions");
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const cols: Column<Position>[] = [
    { key: "stock", label: "Stock", type: "text", get: (p) => p.stock },
    { key: "ccy", label: "Ccy", type: "enum", get: (p) => p.currency },
    { key: "shares", label: "Shares", type: "number", align: "right", get: (p) => p.shares, render: (p) => qty(p.shares) },
    { key: "avg", label: "Avg FIFO cost", type: "number", align: "right", get: (p) => p.avg_cost, render: (p) => num(p.avg_cost) },
    { key: "price", label: "Price (sheet)", type: "number", align: "right", get: (p) => p.price, render: (p) => num(p.price) },
    { key: "cost", label: "Cost $", type: "number", align: "right", get: (p) => p.cost_usd, render: (p) => usd(p.cost_usd) },
    { key: "value", label: "Value $", type: "number", align: "right", firstDir: "desc", get: (p) => p.value_usd, render: (p) => usd(p.value_usd) },
    { key: "pl", label: "Unrealised $", type: "number", align: "right", firstDir: "desc", get: (p) => p.unrealised_usd, render: (p) => <Usd v={p.unrealised_usd} /> },
    { key: "plpct", label: "Unrealised %", type: "number", align: "right", firstDir: "desc", get: (p) => p.unrealised_pct, render: (p) => <Pct v={p.unrealised_pct} /> },
    { key: "w", label: "Weight", type: "number", align: "right", firstDir: "desc", get: (p) => p.weight_pct, render: (p) => pct(p.weight_pct, 1, false) },
    { key: "days", label: "Days held", type: "number", align: "right", get: (p) => p.days_held, render: (p) => num(p.days_held, 0) },
    { key: "lots", label: "Lots", type: "number", align: "right", get: (p) => p.lots.length,
      render: (p) => <span title={p.lots.map((l) => `${l.date} ${qty(l.shares)} @ ${num(l.price)} (${l.broker}, row ${l.row})`).join("\n")}>{p.lots.length}</span> },
    { key: "brokers", label: "Brokers", type: "text", get: (p) => [...new Set(p.lots.map((l) => l.broker))].join(", ") },
  ];
  const t = d.totals;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Open positions</h1>
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Value" value={usd(t.value_usd)} sub={`as of ${d.as_of}`} />
        <Stat label="Cost (FIFO)" value={usd(t.cost_usd)} />
        <Stat label="Unrealised gain" value={<Usd v={t.unrealised_usd} />} sub={<Pct v={t.cost_usd ? (t.unrealised_usd / t.cost_usd) * 100 : null} />} />
      </div>
      <Note tone="slate">{d.price_note} Values in other currencies are converted at the ECB rate of that date. The remaining shares are what FIFO leaves
        after every sale, so the cost is that of the oldest buys still held.{t.not_computed > 0 && ` ${t.not_computed} positions have no price or rate and are left out of the totals.`}</Note>
      <Section title={`${d.positions.length} stocks`}>
        <DataTable id="pt-positions" rows={d.positions} columns={cols} rowKey={(p) => `${p.stock_key}|${p.currency}`} initialSort={[{ key: "value", dir: "desc" }]} exportName="open-positions" />
      </Section>
    </div>
  );
}
