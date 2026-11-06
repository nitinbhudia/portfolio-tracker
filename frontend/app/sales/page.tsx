"use client";

import { useState } from "react";

import { type Column, DataTable } from "@/components/DataTable";
import { ErrorBox, Loading, Note, Pct, Section, Stat, Usd } from "@/components/ui";
import { type Sale, type SalesResp, useApi } from "@/lib/api";
import { num, pct, qty, usd } from "@/lib/format";

function Lots({ s, onClose }: { s: Sale; onClose: () => void }) {
  return (
    <Section title={`${s.stock}: sale of ${qty(s.shares)} on ${s.date}`} right={<button className="text-sm underline" onClick={onClose}>close</button>}>
      <div className="space-y-2 text-sm">
        <p className="num">Sold {qty(s.shares)} at {num(s.price, 4)} {s.currency}{s.currency === "GBP" ? " (pence)" : ""} = {num(s.proceeds_local)} {s.currency}
          {s.sell_rate != null && s.currency !== "USD" && <> × {num(s.sell_rate, 4)} USD/{s.currency} (ECB {s.sell_rate_date})</>} = <b>{usd(s.proceeds_usd, 2)}</b>.
          Position row {s.row}{s.sale_row ? `, sales-log row ${s.sale_row}` : ""}.</p>
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-xs">
            <thead><tr><th>Matched buy (FIFO)</th><th>Broker</th><th className="text-right">Shares</th><th className="text-right">Buy price</th><th className="text-right">Cost ({s.currency})</th><th className="text-right">Rate</th><th className="text-right">Cost (USD)</th><th className="text-right">Days held</th></tr></thead>
            <tbody>{s.matches.map((m) => (
              <tr key={m.buy_id + m.shares}><td>{m.buy_date} · row {m.buy_row}</td><td>{m.broker}</td><td className="text-right">{qty(m.shares)}</td><td className="text-right">{num(m.buy_price, 4)}</td>
                <td className="text-right">{num(m.cost_local)}</td><td className="text-right">{s.currency === "USD" ? "—" : `${num(m.buy_rate, 4)} (${m.buy_rate_date})`}</td>
                <td className="text-right">{usd(m.cost_usd, 2)}</td><td className="text-right">{m.days_held}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <p>Gain: <b><Usd v={s.gain_usd} digits={2} /></b> ({pct(s.gain_pct)})
          {s.fx_effect_usd != null && s.currency !== "USD" && <> = price effect <Usd v={s.price_effect_usd} digits={2} /> + currency effect <Usd v={s.fx_effect_usd} digits={2} /></>}.
          {" "}Your sheet recorded {num(s.sheet_pl)} {s.currency} for this row (matched to its own buy).</p>
        {s.problems.map((p) => <Note key={p}>{p}</Note>)}
      </div>
    </Section>
  );
}

export default function SalesPage() {
  const q = useApi<SalesResp>("/api/sales");
  const [open, setOpen] = useState<Sale | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const cols: Column<Sale>[] = [
    { key: "date", label: "Sold", type: "date", get: (s) => s.date },
    { key: "stock", label: "Stock", type: "text", get: (s) => s.stock,
      render: (s) => <button className="text-left text-blue-700 underline dark:text-blue-300" onClick={() => { setOpen(s); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{s.stock}</button> },
    { key: "shares", label: "Shares", type: "number", align: "right", get: (s) => s.shares, render: (s) => qty(s.shares) },
    { key: "price", label: "Sell price", type: "number", align: "right", get: (s) => s.price, render: (s) => num(s.price, 2) },
    { key: "ccy", label: "Ccy", type: "enum", get: (s) => s.currency },
    { key: "proceeds", label: "Proceeds $", type: "number", align: "right", get: (s) => s.proceeds_usd, render: (s) => usd(s.proceeds_usd) },
    { key: "cost", label: "FIFO cost $", type: "number", align: "right", get: (s) => s.cost_usd, render: (s) => usd(s.cost_usd) },
    { key: "gain", label: "Gain $", type: "number", align: "right", firstDir: "desc", get: (s) => s.gain_usd, render: (s) => <Usd v={s.gain_usd} /> },
    { key: "gpct", label: "Gain %", type: "number", align: "right", firstDir: "desc", get: (s) => s.gain_pct, render: (s) => <Pct v={s.gain_pct} /> },
    { key: "fx", label: "of which FX $", type: "number", align: "right", get: (s) => s.fx_effect_usd, render: (s) => <Usd v={s.fx_effect_usd} />, defaultHidden: true },
    { key: "days", label: "Days held", type: "number", align: "right", get: (s) => s.days_held, render: (s) => num(s.days_held, 0) },
    { key: "lots", label: "Buys", type: "number", align: "right", get: (s) => s.matches.length },
    { key: "sheet", label: "Sheet P/L (own ccy)", type: "number", align: "right", get: (s) => s.sheet_pl, render: (s) => num(s.sheet_pl) },
    { key: "broker", label: "Broker", type: "enum", get: (s) => s.broker },
    { key: "year", label: "Year", type: "enum", get: (s) => s.date.slice(0, 4), defaultHidden: true },
  ];
  const t = d.totals;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Sales — realised gains (FIFO, USD)</h1>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Realised gain" value={<Usd v={t.gain_usd} />} sub={`${t.sales} sales${t.not_computed ? `, ${t.not_computed} not computed` : ""}`} />
        <Stat label="Return on cost of shares sold" value={<Pct v={t.cost_usd ? (t.gain_usd / t.cost_usd) * 100 : null} />} sub={`on ${usd(t.cost_usd)} cost`} />
        <Stat label="Proceeds" value={usd(t.proceeds_usd)} />
        <Stat label="Win rate" value={pct(d.by_year.reduce((a, y) => a + y.wins, 0) / Math.max(1, t.sales - t.not_computed) * 100, 0, false)} sub="sales with a gain" />
      </div>
      {open && <Lots s={open} onClose={() => setOpen(null)} />}
      <Section title="Per year">
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <thead><tr><th>Year</th><th className="text-right">Sales</th><th className="text-right">Realised gain (FIFO, USD)</th><th className="text-right">Wins / losses</th><th className="text-right">Sheet P/L (own ccy, as recorded)</th></tr></thead>
            <tbody>{d.by_year.map((y) => (
              <tr key={y.year}><td>{y.year}</td><td className="text-right">{y.sales}</td><td className="text-right font-medium"><Usd v={y.gain_usd} /></td>
                <td className="text-right">{y.wins} / {y.losses}</td><td className="text-right">{num(y.sheet_pl, 0)}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">{d.method}. Your sheet matched each sale to its own buy row and added currencies together without converting, so its
          figures differ from FIFO in USD; the <a className="underline" href="/check">Check vs sheet</a> page reproduces the sheet&apos;s own numbers.
          Rows still on the Review page are not included yet.</p>
      </Section>
      <Section title="All sales">
        <DataTable id="pt-sales" rows={d.sales} columns={cols} rowKey={(s) => s.id} initialSort={[{ key: "date", dir: "desc" }]} exportName="sales-fifo" />
        <p className="mt-1 text-xs text-slate-500">Click a stock to see which buys each sale was matched to, the exchange rates used, and the price/currency split of the gain.</p>
      </Section>
    </div>
  );
}
