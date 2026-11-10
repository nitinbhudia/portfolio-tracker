"use client";

import { useState } from "react";

import { ErrorBox, Loading, Note, Pct, Section, Stat, Usd, btn, btnPrimary, input } from "@/components/ui";
import { type Analysis, ApiError, apiFetch, type CapitalResp, jsonInit, useApi } from "@/lib/api";
import { num, usd } from "@/lib/format";

export default function ReturnsPage() {
  const an = useApi<Analysis>("/api/analysis");
  const cap = useApi<CapitalResp>("/api/capital");
  const [f, setF] = useState({ date: "", amount: "", currency: "USD", account: "", note: "", kind: "deposit" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (an.error) return <ErrorBox error={an.error} onRetry={an.reload} />;
  if (!an.data || !cap.data) return <Loading />;
  const r = an.data.returns;
  const add = async () => {
    setBusy(true);
    setErr(null);
    try {
      const amount = Math.abs(Number(f.amount)) * (f.kind === "withdrawal" ? -1 : 1);
      cap.setData(await apiFetch<CapitalResp>("/api/capital", jsonInit("POST", { date: f.date, amount, currency: f.currency, account: f.account, note: f.note })));
      setF({ ...f, amount: "", note: "" });
      an.reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const del = async (id: number) => {
    cap.setData(await apiFetch<CapitalResp>(`/api/capital/${id}`, { method: "DELETE" }));
    an.reload();
  };
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Returns</h1>
      <Section title="Return on your trades">
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="Money-weighted return (XIRR)" value={<Pct v={r.money_in_shares.xirr_pct} />} sub="per year" />
          <Stat label="Realised ÷ cost of shares sold" value={<Pct v={r.money_in_shares.return_on_cost_sold_pct} />} sub={`on ${usd(r.money_in_shares.cost_of_shares_sold_usd)}`} />
          <Stat label="Total gain" value={<Usd v={r.total_gain_usd} />} sub={<>realised <Usd v={r.realised_usd} /> + unrealised <Usd v={r.unrealised_usd} /></>} />
        </div>
        <p className="mt-2 text-xs text-slate-500">{r.money_in_shares.explain}</p>
      </Section>
      <Section title="Return on capital">
        {r.capital ? (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Money-weighted return (XIRR)" value={<Pct v={r.capital.xirr_pct} />} sub="per year, on what you put in" />
              <Stat label="Total gain ÷ net capital" value={<Pct v={r.capital.simple_return_pct} />} sub={`${usd(r.capital.net_usd)} net put in`} />
              <Stat label="Implied value now" value={usd(r.capital.end_value_usd)} sub={`deposits ${usd(r.capital.deposits_usd)} · withdrawals ${usd(r.capital.withdrawals_usd)}`} />
            </div>
            <p className="mt-2 text-xs text-slate-500">{r.capital.explain} Per-year return on capital is on the <a className="underline" href="/years">Per year</a> page.</p>
          </>
        ) : (
          <Note>Enter the money you put into (and took out of) your brokerage accounts, with dates, to see your return on capital. Your sheet doesn&apos;t
            record deposits: the cash block in it shows balances (see below), so nothing is assumed.</Note>
        )}
        {an.data.capital_problems.map((p) => <Note key={p}>{p}</Note>)}
        <div className="mt-4 space-y-2">
          <h3 className="text-sm font-semibold">Deposits and withdrawals</h3>
          <div className="flex flex-wrap items-end gap-2 text-sm">
            <label className="flex flex-col text-xs">Type
              <select aria-label="Type" className={input} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                <option value="deposit">Deposit (money in)</option><option value="withdrawal">Withdrawal (money out)</option>
              </select></label>
            <label className="flex flex-col text-xs">Date<input aria-label="Date" type="date" className={input} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
            <label className="flex flex-col text-xs">Amount<input aria-label="Amount" inputMode="decimal" className={`${input} w-28`} value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></label>
            <label className="flex flex-col text-xs">Currency
              <select aria-label="Currency" className={input} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>
                {["USD", "EUR", "GBP", "CHF", "CAD", "SEK", "HUF"].map((c) => <option key={c}>{c}</option>)}
              </select></label>
            <label className="flex flex-col text-xs">Account<input aria-label="Account" className={`${input} w-28`} placeholder="e.g. IBKR" value={f.account} onChange={(e) => setF({ ...f, account: e.target.value })} /></label>
            <label className="flex flex-col text-xs">Note<input aria-label="Note" className={`${input} w-40`} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
            <button className={btnPrimary} disabled={busy || !f.date || !Number(f.amount)} onClick={add}>Add</button>
          </div>
          {err && <div role="alert" className="text-xs text-rose-600">{err}</div>}
          {cap.data.flows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="tbl num w-full text-sm">
                <thead><tr><th>Date</th><th className="text-right">Amount</th><th>Ccy</th><th className="text-right">USD (ECB rate of the day)</th><th>Account</th><th>Note</th><th></th></tr></thead>
                <tbody>{cap.data.flows.map((x) => (
                  <tr key={x.id}><td>{x.date}</td><td className="text-right"><Usd v={x.amount} digits={2} /></td><td>{x.currency}</td><td className="text-right">{usd(x.usd)}</td>
                    <td>{x.account}</td><td className="whitespace-normal">{x.note}</td><td><button className={`${btn} text-xs`} onClick={() => del(x.id)} aria-label={`Delete entry of ${x.date}`}>delete</button></td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </div>
      </Section>
      {cap.data.sheet_cash.length > 0 && (
        <Section title="Cash block in your sheet (for reference)">
          <p className="mb-2 text-xs text-slate-500">{cap.data.sheet_cash_note}</p>
          <div className="grid gap-4 lg:grid-cols-2">
            {cap.data.sheet_cash.map((b) => (
              <div key={b.header_row} className="overflow-x-auto">
                <div className="mb-1 text-xs text-slate-500">Rows {b.header_row}–{b.totals[b.totals.length - 1]?.row ?? b.rows[b.rows.length - 1]?.row}{b.title ? ` · "${b.title}"` : ""}</div>
                <table className="tbl num w-full text-xs">
                  <thead><tr><th>Row</th><th>Label</th><th className="text-right">Orginal</th><th className="text-right">Dollar</th></tr></thead>
                  <tbody>
                    {b.rows.map((x) => <tr key={x.row}><td>{x.row}</td><td>{x.label}</td><td className="text-right">{num(x.original)}</td><td className="text-right">{num(x.usd)}</td></tr>)}
                    {b.totals.map((x) => <tr key={x.row} className="font-semibold"><td>{x.row}</td><td>{x.label}</td><td></td><td className="text-right">{num(x.usd)}</td></tr>)}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </Section>
      )}
      <p className="text-xs text-slate-500">{an.data.limits}</p>
    </div>
  );
}
