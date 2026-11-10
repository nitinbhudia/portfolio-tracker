"use client";

import { useState } from "react";

import { type Column, DataTable } from "@/components/DataTable";
import { ErrorBox, Loading, Note, Pct, Section, Usd } from "@/components/ui";
import { type StockDetail, type StockRow, useApi } from "@/lib/api";
import { num, qty, usd } from "@/lib/format";

function Detail({ pool, onClose }: { pool: string; onClose: () => void }) {
  const q = useApi<StockDetail>(`/api/by-stock/detail?pool=${encodeURIComponent(pool)}`);
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data) return <Loading />;
  const d = q.data, s = d.summary;
  return (
    <Section title={`${s?.stock ?? pool} (${s?.currency})`} right={<button className="text-sm underline" onClick={onClose}>close</button>}>
      {s && (
        <dl className="mb-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
          <div><dt className="text-xs text-slate-500">Total gain</dt><dd className="font-semibold"><Usd v={s.total_usd} /> (<Pct v={s.total_return_pct} />)</dd></div>
          <div><dt className="text-xs text-slate-500">Realised / unrealised</dt><dd><Usd v={s.realised_usd} /> / <Usd v={s.unrealised_usd} /></dd></div>
          <div><dt className="text-xs text-slate-500">Bought / sold</dt><dd className="num">{qty(s.shares_bought)} @ {num(s.avg_buy_price)} avg / {qty(s.shares_sold)} @ {num(s.avg_sell_price)} avg</dd></div>
        </dl>
      )}
      <div className="overflow-x-auto">
        <table className="tbl num w-full text-xs">
          <thead><tr><th>Date</th><th>Trade</th><th className="text-right">Shares</th><th className="text-right">Price ({s?.currency})</th><th className="text-right">USD</th>
            <th className="text-right">Gain (FIFO)</th><th className="text-right">Days held</th><th>Broker</th><th>Row</th><th>Matched buys</th></tr></thead>
          <tbody>{d.trades.map((t) => (
            <tr key={t.id}>
              <td>{t.date}</td><td>{t.kind === "buy" ? "Buy" : "Sell"}</td><td className="text-right">{qty(t.shares)}</td><td className="text-right">{num(t.price, 2)}</td>
              <td className="text-right">{usd(t.value_usd)}</td><td className="text-right">{t.kind === "sell" ? <><Usd v={t.gain_usd} /> (<Pct v={t.gain_pct} />)</> : ""}</td>
              <td className="text-right">{t.days_held != null ? num(t.days_held, 0) : ""}</td><td>{t.broker}</td><td>{t.row}</td>
              <td className="whitespace-normal">{t.matches?.map((m) => `${m.buy_date} ×${qty(m.shares)}`).join(", ")}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {d.position && <p className="mt-2 text-xs text-slate-500">Still held: {qty(d.position.shares)} at {num(d.position.price)} (sheet price, {d.as_of}).</p>}
    </Section>
  );
}

export default function ByStockPage() {
  const q = useApi<{ stocks: StockRow[]; as_of: string; limits: string }>("/api/by-stock");
  const [open, setOpen] = useState<string | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const cols: Column<StockRow>[] = [
    { key: "stock", label: "Stock", type: "text", get: (r) => r.stock,
      render: (r) => <button className="text-left text-blue-700 underline dark:text-blue-300" onClick={() => { setOpen(r.pool); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{r.stock}</button> },
    { key: "ccy", label: "Ccy", type: "enum", get: (r) => r.currency },
    { key: "status", label: "Status", type: "enum", get: (r) => r.status },
    { key: "total", label: "Total gain $", type: "number", align: "right", firstDir: "desc", get: (r) => r.total_usd, render: (r) => <Usd v={r.total_usd} /> },
    { key: "ret", label: "Total %", type: "number", align: "right", firstDir: "desc", get: (r) => r.total_return_pct, render: (r) => <Pct v={r.total_return_pct} /> },
    { key: "real", label: "Realised $", type: "number", align: "right", get: (r) => r.realised_usd, render: (r) => <Usd v={r.realised_usd} /> },
    { key: "unreal", label: "Unrealised $", type: "number", align: "right", get: (r) => r.unrealised_usd, render: (r) => <Usd v={r.unrealised_usd} /> },
    { key: "bought", label: "Bought $", type: "number", align: "right", get: (r) => r.bought_usd, render: (r) => usd(r.bought_usd) },
    { key: "buys", label: "Buys", type: "number", align: "right", get: (r) => r.buys },
    { key: "sells", label: "Sells", type: "number", align: "right", get: (r) => r.sells },
    { key: "avgb", label: "Avg buy", type: "number", align: "right", get: (r) => r.avg_buy_price, render: (r) => num(r.avg_buy_price), defaultHidden: true },
    { key: "avgs", label: "Avg sell", type: "number", align: "right", get: (r) => r.avg_sell_price, render: (r) => num(r.avg_sell_price), defaultHidden: true },
    { key: "first", label: "First trade", type: "date", get: (r) => r.first },
    { key: "last", label: "Last trade", type: "date", get: (r) => r.last },
  ];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Per stock</h1>
      <Note tone="slate">Total gain = realised (FIFO, USD) + unrealised at the sheet&apos;s prices of {q.data.as_of}. Total % = total gain ÷ everything you paid for
        the stock. A stock listed in two currencies appears once per currency.</Note>
      {open && <Detail pool={open} onClose={() => setOpen(null)} />}
      <Section title={`${q.data.stocks.length} stocks`}>
        <DataTable id="pt-by-stock" rows={q.data.stocks} columns={cols} rowKey={(r) => r.pool} initialSort={[{ key: "total", dir: "desc" }]} exportName="per-stock" />
      </Section>
    </div>
  );
}
