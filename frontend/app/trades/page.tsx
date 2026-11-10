"use client";

import { useState } from "react";

import { type Column, DataTable } from "@/components/DataTable";
import { ErrorBox, Loading, Note, Section, Usd, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, notifyStatus, type TradeRow, type TradesResp, useApi } from "@/lib/api";
import { num, qty } from "@/lib/format";

type Form = { kind: "buy" | "sell"; date: string; name: string; shares: string; price: string; currency: string; pence: boolean; broker: string; fee: string; note: string };
const EMPTY: Form = { kind: "buy", date: "", name: "", shares: "", price: "", currency: "USD", pence: false, broker: "", fee: "", note: "" };

function TradeForm({ stocks, currencies, editing, onSaved, onCancel }: {
  stocks: string[]; currencies: string[]; editing: TradeRow | null; onSaved: (r: TradesResp) => void; onCancel: () => void;
}) {
  const [f, setF] = useState<Form>(editing ? {
    kind: editing.kind, date: editing.date, name: editing.stock, shares: String(editing.shares), price: String(editing.price), currency: editing.currency,
    pence: editing.pence, broker: editing.broker, fee: editing.fee ? String(editing.fee) : "", note: editing.note ?? "",
  } : EMPTY);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = { ...f, shares: Number(f.shares), price: Number(f.price), fee: Number(f.fee || 0) };
      onSaved(await apiFetch<TradesResp>(editing ? `/api/trades/${editing.id}` : "/api/trades", jsonInit(editing ? "PUT" : "POST", body)));
      if (!editing) setF({ ...EMPTY, kind: f.kind, currency: f.currency, broker: f.broker, date: f.date });
      notifyStatus();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const L = "flex flex-col text-xs";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className={L}>Trade<select aria-label="Trade type" className={input} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as Form["kind"] })}>
          <option value="buy">Buy</option><option value="sell">Sell</option></select></label>
        <label className={L}>Date<input aria-label="Trade date" type="date" className={input} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
        <label className={L}>Stock<input aria-label="Stock name" list="pt-stocks" className={`${input} w-44`} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <datalist id="pt-stocks">{stocks.map((s) => <option key={s} value={s} />)}</datalist></label>
        <label className={L}>Shares<input aria-label="Shares" inputMode="decimal" className={`${input} w-20`} value={f.shares} onChange={(e) => setF({ ...f, shares: e.target.value })} /></label>
        <label className={L}>Price<input aria-label="Price" inputMode="decimal" className={`${input} w-24`} value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
        <label className={L}>Currency<select aria-label="Trade currency" className={input} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value, pence: e.target.value === "GBP" })}>
          {currencies.map((c) => <option key={c}>{c}</option>)}</select></label>
        {f.currency === "GBP" && <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={f.pence} onChange={(e) => setF({ ...f, pence: e.target.checked })} />price in pence</label>}
        <label className={L}>Fee ({f.currency})<input aria-label="Fee" inputMode="decimal" className={`${input} w-20`} value={f.fee} onChange={(e) => setF({ ...f, fee: e.target.value })} /></label>
        <label className={L}>Broker<input aria-label="Broker" className={`${input} w-24`} value={f.broker} onChange={(e) => setF({ ...f, broker: e.target.value })} /></label>
        <label className={L}>Note<input aria-label="Trade note" className={`${input} w-36`} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
        <button className={btnPrimary} disabled={busy || !f.date || !f.name.trim() || !Number(f.shares) || f.price === ""} onClick={save}>{editing ? "Save changes" : "Add trade"}</button>
        {editing && <button className={btn} onClick={onCancel}>Cancel</button>}
      </div>
      {err && <div role="alert" className="text-xs text-rose-600">{err}</div>}
      <p className="text-xs text-slate-500">Use the same stock name as in your sheet (suggestions appear as you type) so FIFO matches it with your earlier trades.
        A sell takes shares from the oldest purchases first. Fees are added to a purchase&apos;s cost and taken off a sale&apos;s proceeds.</p>
    </div>
  );
}

function SheetTradeEditor({ t, onSaved, onClose }: { t: TradeRow; onSaved: (r: TradesResp) => void; onClose: () => void }) {
  const [fee, setFee] = useState(t.fee ? String(t.fee) : "");
  const [c, setC] = useState({ date: "", shares: "", price: "", sell: "", currency: "" });
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<TradesResp>) => {
    setErr(null);
    try {
      onSaved(await fn());
      notifyStatus();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  const fields: Record<string, string | number> = {};
  if (c.date) fields[t.kind === "sell" ? "sale_date" : "date"] = c.date;
  if (c.shares) fields.shares = Number(c.shares);
  if (c.price) fields.price = Number(c.price);
  if (c.sell) fields.live_price = Number(c.sell);
  if (c.currency) fields.currency = c.currency.toUpperCase();
  const L = "flex flex-col text-xs";
  return (
    <Section title={`${t.kind === "buy" ? "Purchase" : "Sale"} from the sheet: ${t.stock}, row ${t.row}`} right={<button className="text-sm underline" onClick={onClose}>close</button>}>
      <div className="space-y-3 text-sm">
        <p className="num text-slate-600 dark:text-slate-300">{t.date} · {qty(t.shares)} @ {num(t.price, 4)} {t.currency}{t.pence ? " (pence)" : ""} · {t.broker}</p>
        <div className="flex flex-wrap items-end gap-2">
          <label className={L}>Fee ({t.currency})<input aria-label="Fee on this trade" inputMode="decimal" className={`${input} w-24`} value={fee} onChange={(e) => setFee(e.target.value)} /></label>
          <button className={btn} onClick={() => run(() => apiFetch(`/api/trades/${t.id}/fee`, jsonInit("PUT", { fee: Number(fee || 0) })))}>Save fee</button>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className={L}>{t.kind === "sell" ? "Sale date" : "Buy date"}<input aria-label="Corrected date" type="date" className={input} value={c.date} onChange={(e) => setC({ ...c, date: e.target.value })} /></label>
          <label className={L}>Shares<input aria-label="Corrected shares" className={`${input} w-20`} value={c.shares} onChange={(e) => setC({ ...c, shares: e.target.value })} /></label>
          {t.kind === "buy"
            ? <label className={L}>Buy price<input aria-label="Corrected buy price" className={`${input} w-24`} value={c.price} onChange={(e) => setC({ ...c, price: e.target.value })} /></label>
            : <label className={L}>Sell price<input aria-label="Corrected sell price" className={`${input} w-24`} value={c.sell} onChange={(e) => setC({ ...c, sell: e.target.value })} /></label>}
          <label className={L}>Currency<input aria-label="Corrected currency" className={`${input} w-16 uppercase`} value={c.currency} onChange={(e) => setC({ ...c, currency: e.target.value })} /></label>
          <button className={btn} disabled={!Object.keys(fields).length} onClick={() => run(() => apiFetch(`/api/trades/${t.id}/correct`, jsonInit("PUT", { fields })))}>Save correction</button>
        </div>
        <p className="text-xs text-slate-500">Leave a box empty to keep the sheet&apos;s value. Corrections are kept when you import the same rows again, and dropped
          (with a note on the Import page) if that row changes in your sheet. To leave a trade out, use the Review page.</p>
        {err && <div role="alert" className="text-xs text-rose-600">{err}</div>}
      </div>
    </Section>
  );
}

export default function TradesPage() {
  const q = useApi<TradesResp>("/api/trades");
  const [editing, setEditing] = useState<TradeRow | null>(null);
  const [sheetEdit, setSheetEdit] = useState<TradeRow | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const remove = async (t: TradeRow) => {
    if (!window.confirm(`Delete the ${t.kind} of ${qty(t.shares)} ${t.stock} on ${t.date}?`)) return;
    q.setData(await apiFetch<TradesResp>(`/api/trades/${t.id}`, { method: "DELETE" }));
    notifyStatus();
  };
  const cols: Column<TradeRow>[] = [
    { key: "date", label: "Date", type: "date", get: (t) => t.date },
    { key: "kind", label: "Trade", type: "enum", get: (t) => t.kind, labels: { buy: "Buy", sell: "Sell" }, render: (t) => (t.kind === "buy" ? "Buy" : "Sell") },
    { key: "stock", label: "Stock", type: "text", get: (t) => t.stock },
    { key: "shares", label: "Shares", type: "number", align: "right", get: (t) => t.shares, render: (t) => qty(t.shares) },
    { key: "price", label: "Price", type: "number", align: "right", get: (t) => t.price, render: (t) => num(t.price, 2) },
    { key: "ccy", label: "Ccy", type: "enum", get: (t) => t.currency },
    { key: "fee", label: "Fee", type: "number", align: "right", get: (t) => t.fee, render: (t) => (t.fee ? num(t.fee, 2) : "") },
    { key: "gain", label: "Gain $ (FIFO)", type: "number", align: "right", get: (t) => t.gain_usd, render: (t) => (t.kind === "sell" ? <Usd v={t.gain_usd} /> : "") },
    { key: "broker", label: "Broker", type: "enum", get: (t) => t.broker },
    { key: "source", label: "From", type: "enum", get: (t) => (t.source === "app" ? "entered here" : "sheet"),
      render: (t) => (t.source === "app" ? <span className="rounded bg-sky-100 px-1.5 text-xs text-sky-800 dark:bg-sky-900 dark:text-sky-200">entered here</span> : <span className="text-xs text-slate-500">row {t.row}</span>) },
    { key: "act", label: "", type: "text", sortable: false, filterable: false, get: () => null,
      render: (t) => t.editable ? (
        <span className="flex gap-2 text-xs"><button className="underline" onClick={() => { setEditing(t); window.scrollTo({ top: 0, behavior: "smooth" }); }}>edit</button>
          <button className="text-rose-600 underline" onClick={() => remove(t)}>delete</button></span>
      ) : t.correctable ? <button className="text-xs underline" onClick={() => { setSheetEdit(t); window.scrollTo({ top: 0, behavior: "smooth" }); }}>fee / correct</button> : null },
  ];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Trades</h1>
      <Section title={editing ? `Edit trade ${editing.id}` : "Add a trade"}>
        <TradeForm key={editing?.id ?? "new"} stocks={d.stocks} currencies={d.currencies} editing={editing}
          onSaved={(r) => { q.setData(r); setEditing(null); }} onCancel={() => setEditing(null)} />
      </Section>
      {sheetEdit && <SheetTradeEditor t={sheetEdit} onSaved={(r) => q.setData(r)} onClose={() => setSheetEdit(null)} />}
      {d.stale_fees.length > 0 && <Note>{d.stale_fees.length} fees no longer apply because those rows changed in your sheet: {d.stale_fees.join(", ")}.</Note>}
      <Section title={`${d.trades.length} trades`}>
        <DataTable id="pt-trades" rows={d.trades} columns={cols} rowKey={(t) => t.id} initialSort={[{ key: "date", dir: "desc" }]} exportName="trades" />
        <p className="mt-1 text-xs text-slate-500">Trades from the sheet can get a fee or a correction; trades entered here can be edited or deleted.
          Rows still on the Review page aren&apos;t listed.</p>
      </Section>
    </div>
  );
}
