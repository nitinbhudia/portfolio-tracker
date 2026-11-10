"use client";

import { useState } from "react";

import { ErrorBox, Loading, Note, Section, Stat, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, type DividendsResp, jsonInit, type TradesResp, useApi } from "@/lib/api";
import { num, usd } from "@/lib/format";

const CURS = ["USD", "EUR", "GBP", "CHF", "CAD", "SEK", "HUF"];

export default function DividendsPage() {
  const q = useApi<DividendsResp>("/api/dividends");
  const names = useApi<TradesResp>("/api/trades");
  const [f, setF] = useState({ date: "", name: "", amount: "", tax: "", currency: "USD", note: "" });
  const [err, setErr] = useState<string | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const add = async () => {
    setErr(null);
    try {
      q.setData(await apiFetch<DividendsResp>("/api/dividends", jsonInit("POST", { ...f, amount: Number(f.amount), tax: Number(f.tax || 0) })));
      setF({ ...f, amount: "", tax: "", note: "" });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  const L = "flex flex-col text-xs";
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Dividends</h1>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Dividends received" value={usd(d.total_usd)} sub={`${d.dividends.length} entries, after withholding tax`} />
        {d.by_year.slice(-3).reverse().map((y) => <Stat key={y.year} label={String(y.year)} value={usd(y.usd)} />)}
      </div>
      <Section title="Add a dividend">
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <label className={L}>Paid on<input aria-label="Dividend date" type="date" className={input} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
          <label className={L}>Stock<input aria-label="Dividend stock" list="pt-div-stocks" className={`${input} w-44`} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <datalist id="pt-div-stocks">{(names.data?.stocks ?? []).map((s) => <option key={s} value={s} />)}</datalist></label>
          <label className={L}>Received (after tax)<input aria-label="Dividend amount" inputMode="decimal" className={`${input} w-28`} value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></label>
          <label className={L}>Tax withheld<input aria-label="Tax withheld" inputMode="decimal" className={`${input} w-24`} value={f.tax} onChange={(e) => setF({ ...f, tax: e.target.value })} /></label>
          <label className={L}>Currency<select aria-label="Dividend currency" className={input} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>
            {CURS.map((c) => <option key={c}>{c}</option>)}</select></label>
          <label className={L}>Note<input aria-label="Dividend note" className={`${input} w-36`} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
          <button className={btnPrimary} disabled={!f.date || !f.name.trim() || !Number(f.amount)} onClick={add}>Add</button>
        </div>
        {err && <div role="alert" className="mt-1 text-xs text-rose-600">{err}</div>}
        <p className="mt-2 text-xs text-slate-500">The amount received counts in total gain, returns, per year and per stock (converted at the ECB rate of the payment
          date). Withheld tax is kept for your information only.</p>
      </Section>
      {d.problems.map((p) => <Note key={p}>{p}</Note>)}
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Section title="All dividends">
          {d.dividends.length === 0 ? <p className="text-sm text-slate-500">None entered yet.</p> : (
            <div className="overflow-x-auto">
              <table className="tbl num w-full text-sm">
                <thead><tr><th>Date</th><th>Stock</th><th className="text-right">Received</th><th className="text-right">Tax</th><th>Ccy</th><th className="text-right">USD</th><th></th></tr></thead>
                <tbody>{d.dividends.map((x) => (
                  <tr key={x.id}><td>{x.date}</td><td>{x.name}</td><td className="text-right">{num(x.amount)}</td><td className="text-right">{x.tax ? num(x.tax) : ""}</td>
                    <td>{x.currency}</td><td className="text-right">{usd(x.usd, 2)}</td>
                    <td><button className={`${btn} text-xs`} aria-label={`Delete dividend of ${x.date}`} onClick={async () => q.setData(await apiFetch<DividendsResp>(`/api/dividends/${x.id}`, { method: "DELETE" }))}>delete</button></td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Section>
        <Section title="By stock">
          {d.by_stock.length === 0 ? <p className="text-sm text-slate-500">—</p> : (
            <table className="tbl num w-full text-sm"><tbody>{d.by_stock.map((s) => <tr key={s.name}><td>{s.name}</td><td className="text-right">{usd(s.usd)}</td></tr>)}</tbody></table>
          )}
        </Section>
      </div>
    </div>
  );
}
