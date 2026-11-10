"use client";

import { useEffect, useState } from "react";

import { ErrorBox, Section, Stat, Usd, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type ADPlan, type ADResp, type WIOverview } from "@/lib/api";
import { num, pct, qty, usd } from "@/lib/format";

type Mode = "shares" | "amount_usd" | "target_break_even";
const MODES: [Mode, string][] = [["shares", "Shares to buy"], ["amount_usd", "Amount (USD)"], ["target_break_even", "Target break-even"]];

export default function AverageDownTab({ o }: { o: WIOverview }) {
  const held = o.holdings.filter((h) => h.price !== null && h.unrealised_usd !== null)
    .sort((a, b) => (a.unrealised_usd ?? 0) - (b.unrealised_usd ?? 0));
  const [pool, setPool] = useState(held[0]?.pool ?? "");
  const [price, setPrice] = useState("");
  const [mode, setMode] = useState<Mode>("shares");
  const [value, setValue] = useState("");
  const [r, setR] = useState<ADResp | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const h = held.find((x) => x.pool === pool);
  const unit = h?.pence ? "p" : h?.currency ?? "";

  const run = async (body: Record<string, unknown>) => {
    setErr(null);
    try {
      setR(await apiFetch<ADResp>("/api/whatif/average-down", jsonInit("POST", body)));
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    }
  };
  useEffect(() => { if (pool) run({ pool }); setValue(""); setPrice(""); }, [pool]);
  const calc = () => run({ pool, buy_price: price.trim() ? Number(price) : null, ...(value.trim() ? { [mode]: Number(value) } : {}) });

  if (!held.length) return <p className="text-sm">No open positions with a current price.</p>;
  const losers = held.filter((x) => (x.unrealised_usd ?? 0) < 0);
  return (
    <div className="space-y-4">
      <Section title="Buy more to lower your break-even">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">Position
            <select className={input} value={pool} onChange={(e) => setPool(e.target.value)}>
              {losers.length > 0 && <optgroup label="In loss (biggest first)">{losers.map((x) => <option key={x.pool} value={x.pool}>{x.stock} ({usd(x.unrealised_usd)})</option>)}</optgroup>}
              <optgroup label="In profit">{held.filter((x) => (x.unrealised_usd ?? 0) >= 0).map((x) => <option key={x.pool} value={x.pool}>{x.stock}</option>)}</optgroup>
            </select></label>
          <label className="flex flex-col gap-1">Buy price ({unit})
            <input aria-label="Buy price" inputMode="decimal" className={`${input} w-28`} placeholder={h ? `today ${num(h.price)}` : ""} value={price} onChange={(e) => setPrice(e.target.value)} /></label>
          <label className="flex flex-col gap-1">Plan by
            <select aria-label="Plan by" className={input} value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              {MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></label>
          <label className="flex flex-col gap-1">{MODES.find(([k]) => k === mode)?.[1]}{mode === "target_break_even" ? ` (${unit})` : ""}
            <input aria-label="Plan value" inputMode="decimal" className={`${input} w-28`} value={value} onChange={(e) => setValue(e.target.value)} /></label>
          <button className={btnPrimary} onClick={calc}>Calculate</button>
        </div>
        <p className="mt-2 text-xs text-slate-500">Leave the plan empty to see only the standard table. Whole shares for an amount or a target.</p>
      </Section>
      <ErrorBox error={err} />
      {r && <Result r={r} />}
    </div>
  );
}

function Compare({ r, p }: { r: ADResp; p: ADPlan }) {
  const unit = r.pence ? "p" : r.currency;
  const row = (label: string, a: React.ReactNode, b: React.ReactNode) => <tr><td>{label}</td><td className="text-right">{a}</td><td className="text-right">{b}</td></tr>;
  return (
    <table className="tbl num w-full text-sm">
      <thead><tr><th></th><th className="text-right">Do nothing</th><th className="text-right">Buy {qty(p.shares_added)} at {num(p.buy_price)}</th></tr></thead>
      <tbody>
        {row("Shares", qty(r.now.shares), qty(p.shares_after))}
        {row("Money in (FIFO cost)", usd(r.now.cost_usd), usd(p.cost_after_usd))}
        {row("Extra money", "—", usd(p.money_usd))}
        {row(`Break-even (${unit})`, num(r.now.break_even), <b>{num(p.break_even)}</b>)}
        {row("Rise needed from today", pct(r.now.rise_needed_pct), <b>{pct(p.rise_needed_from_today_pct)}</b>)}
        {row("Rise needed from the buy price", "—", pct(p.rise_needed_from_buy_pct))}
        {row(`If it then falls another ${r.stress_pct}%`, <Usd v={p.if_falls_further_without_usd} />, <Usd v={p.if_falls_further_usd} />)}
        {row("If it gets back to your old break-even", <Usd v={0} />, <Usd v={p.at_old_break_even_gain_usd} />)}
      </tbody>
    </table>
  );
}

function Result({ r }: { r: ADResp }) {
  const unit = r.pence ? "p" : r.currency;
  const p = r.plan;
  return (
    <>
      <Section title={`${r.stock} now`}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Shares" value={qty(r.now.shares)} sub={`price ${num(r.price)} ${unit} (${r.price_date ?? r.as_of})`} />
          <Stat label="Break-even" value={`${num(r.now.break_even)} ${unit}`} sub={`FIFO cost ${usd(r.now.cost_usd)}`} />
          <Stat label="Unrealised" value={<Usd v={r.now.unrealised_usd} />} />
          <Stat label="Rise needed to break even" value={pct(r.now.rise_needed_pct)} />
        </div>
        {!r.now.in_loss && <p className="mt-2 text-sm">This position is in profit, so buying more raises your break-even rather than lowering it.</p>}
      </Section>
      {p && (
        <Section title="Your plan vs doing nothing">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="overflow-x-auto"><Compare r={r} p={p} /></div>
            {p.sell_added_at_break_even && (
              <div className="text-sm">
                <p className="font-medium">FIFO catch</p>
                <p className="mt-1">If the price reaches the new break-even ({num(p.break_even)} {unit}) and you sell only {qty(p.shares_added)} shares
                  (as many as you bought), FIFO sells your oldest shares first and realises <Usd v={p.sell_added_at_break_even.gain_usd} />.
                  The position as a whole only breaks even when you sell all of it.</p>
                <table className="tbl num mt-2 w-full text-xs">
                  <thead><tr><th>Bought</th><th className="text-right">Shares</th><th className="text-right">Gain</th></tr></thead>
                  <tbody>{p.sell_added_at_break_even.lots.map((l, i) => <tr key={i}><td>{l.bought}</td><td className="text-right">{qty(l.shares)}</td><td className="text-right"><Usd v={l.gain_usd} /></td></tr>)}</tbody>
                </table>
              </div>
            )}
          </div>
        </Section>
      )}
      <Section title="Scenarios: when and how much">
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <thead><tr><th>Buy at</th>{r.table[0].plans.map((x) => <th key={x.multiple} className="text-right">+{qty(x.shares_added)} shares (×{x.multiple})</th>)}</tr></thead>
            <tbody>{r.table.map((row) => (
              <tr key={row.drop_pct}>
                <td>{num(row.buy_price)} {unit}<span className="text-slate-500"> {row.drop_pct ? `(−${row.drop_pct}%)` : "(today)"}</span></td>
                {row.plans.map((x) => (
                  <td key={x.multiple} className="text-right">
                    <div>break-even <b>{num(x.break_even)}</b></div>
                    <div className="text-xs text-slate-500">needs {pct(x.rise_needed_from_buy_pct)} from there · {usd(x.money_usd)}</div>
                    <div className="text-xs">−{r.stress_pct}% more: <Usd v={x.if_falls_further_usd} /></div>
                  </td>
                ))}
              </tr>
            ))}</tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">Bigger and cheaper buys lower the break-even faster (break even quickly) but put more money at risk; smaller or
          staged buys move it less (break even slowly). Without buying, a further {r.stress_pct}% fall from today means <Usd v={r.now.if_falls_further_usd} />.</p>
      </Section>
      <p className="text-xs text-slate-500">{r.notes}</p>
    </>
  );
}
