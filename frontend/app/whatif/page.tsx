"use client";

import Link from "next/link";
import { Fragment, useState } from "react";

import { ErrorBox, Loading, Note, Pct, Section, Stat, Usd, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type WIOverview, type WIRebalResp, type WISellResp, useApi } from "@/lib/api";
import { num, pct, qty, usd } from "@/lib/format";

function SaleResult({ r }: { r: WISellResp }) {
  const [open, setOpen] = useState<string | null>(null);
  const t = r.totals;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Gain / loss if sold now" value={<Usd v={t.gain_usd} />} sub={<Pct v={t.gain_pct} />} />
        <Stat label="Proceeds" value={usd(t.proceeds_usd)} sub={`FIFO cost ${usd(t.cost_usd)}`} />
        <Stat label="Gains / losses" value={<><Usd v={t.gains_usd} /> / <Usd v={t.losses_usd} /></>} sub="across the stocks sold" />
        <Stat label={`Realised this year`} value={<Usd v={r.year.realised_after_usd} />} sub={<>now <Usd v={r.year.realised_so_far_usd} /></>} />
      </div>
      <p className="text-xs text-slate-500">Held over a year: <Usd v={t.held_over_1y_gain_usd} /> · up to a year: <Usd v={t.held_under_1y_gain_usd} />. {r.notes}</p>
      <div className="overflow-x-auto">
        <table className="tbl num w-full text-sm">
          <thead><tr><th>Stock</th><th className="text-right">Shares</th><th className="text-right">Price</th><th className="text-right">Proceeds</th>
            <th className="text-right">FIFO cost</th><th className="text-right">Gain</th><th className="text-right">%</th><th className="text-right">Left</th><th></th></tr></thead>
          <tbody>{r.sales.map((s) => (
            <Fragment key={s.pool}>
              <tr><td>{s.stock} <span className="text-xs text-slate-500">{s.currency}</span></td><td className="text-right">{qty(s.shares)}</td>
                <td className="text-right">{num(s.price)}</td><td className="text-right">{usd(s.proceeds_usd)}</td><td className="text-right">{usd(s.cost_usd)}</td>
                <td className="text-right font-medium"><Usd v={s.gain_usd} /></td><td className="text-right"><Pct v={s.gain_pct} /></td><td className="text-right">{qty(s.remaining_shares)}</td>
                <td><button className="text-xs underline" onClick={() => setOpen(open === s.pool ? null : s.pool)}>{open === s.pool ? "hide" : `${s.lots.length} lot${s.lots.length > 1 ? "s" : ""}`}</button></td></tr>
              {open === s.pool && s.lots.map((l, i) => (
                <tr key={`${s.pool}${i}`} className="text-xs text-slate-600 dark:text-slate-300"><td className="pl-6">bought {l.bought} · {l.broker}</td><td className="text-right">{qty(l.shares)}</td>
                  <td className="text-right">{num(l.buy_price)}</td><td className="text-right">{usd(l.proceeds_usd)}</td><td className="text-right">{usd(l.cost_usd)}</td>
                  <td className="text-right"><Usd v={l.gain_usd} /></td><td className="text-right">{l.days_held} d</td><td></td><td></td></tr>
              ))}
            </Fragment>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

function SellTab({ o }: { o: WIOverview }) {
  const [pick, setPick] = useState<Record<string, string>>({});
  const [sector, setSector] = useState("");
  const [percent, setPercent] = useState("100");
  const [r, setR] = useState<WISellResp | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const run = async (body: unknown) => {
    setErr(null);
    try {
      setR(await apiFetch<WISellResp>("/api/whatif/sell", jsonInit("POST", body)));
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    }
  };
  const chosen = Object.entries(pick).filter(([, v]) => v !== "");
  const sectorsInUse = o.sectors.map((s) => s.sector).filter((s) => s !== "(no sector)");
  return (
    <div className="space-y-4">
      <Section title="Quick scenarios">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col text-xs">Sell this % of each
            <input aria-label="Percent to sell" inputMode="decimal" className={`${input} w-20`} value={percent} onChange={(e) => setPercent(e.target.value)} /></label>
          <button className={btn} onClick={() => run({ everything: true, percent: Number(percent) })}>…of the whole portfolio</button>
          <span className="flex items-end gap-1">
            <label className="flex flex-col text-xs">Sector
              <select aria-label="Sector to sell" className={input} value={sector} onChange={(e) => setSector(e.target.value)}>
                <option value="">choose…</option>{sectorsInUse.map((s) => <option key={s}>{s}</option>)}</select></label>
            <button className={btn} disabled={!sector} onClick={() => run({ sector, percent: Number(percent) })}>…of this sector</button>
          </span>
        </div>
        {sectorsInUse.length === 0 && <p className="mt-2 text-xs text-slate-500">No confirmed sectors yet: set or confirm them on <Link className="underline" href="/stocks">Data ▾ Names</Link>.</p>}
      </Section>
      <Section title="Choose stocks and shares" right={<button className={btnPrimary} disabled={!chosen.length}
        onClick={() => run({ items: chosen.map(([pool, v]) => (v.endsWith("%") ? { pool, percent: Number(v.slice(0, -1)) } : { pool, shares: Number(v) })) })}>
        Simulate sale of {chosen.length || ""} selected</button>}>
        <div className="max-h-96 overflow-auto">
          <table className="tbl num w-full text-sm">
            <thead className="sticky top-0 bg-white dark:bg-slate-900"><tr><th>Stock</th><th>Sector</th><th className="text-right">Shares</th><th className="text-right">Value</th>
              <th className="text-right">Unrealised</th><th>Sell (shares, or e.g. 50%)</th></tr></thead>
            <tbody>{o.holdings.map((h) => (
              <tr key={h.pool}><td>{h.stock} <span className="text-xs text-slate-500">{h.currency}</span></td><td className="text-xs">{h.sector ?? "—"}</td>
                <td className="text-right">{qty(h.shares)}</td><td className="text-right">{usd(h.value_usd)}</td><td className="text-right"><Usd v={h.unrealised_usd} /></td>
                <td><span className="flex items-center gap-1">
                  <input aria-label={`Shares of ${h.stock} to sell`} className={`${input} w-24`} placeholder="—" value={pick[h.pool] ?? ""} onChange={(e) => setPick({ ...pick, [h.pool]: e.target.value })} />
                  <button className="text-xs underline" onClick={() => setPick({ ...pick, [h.pool]: String(h.shares) })}>all</button></span></td></tr>
            ))}</tbody>
          </table>
        </div>
      </Section>
      <ErrorBox error={err} />
      {r && <Section title="If you sold now"><SaleResult r={r} /></Section>}
    </div>
  );
}

function RebalanceTab({ o }: { o: WIOverview }) {
  const [by, setBy] = useState<"stock" | "sector">("stock");
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [r, setR] = useState<WIRebalResp | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const rows = by === "stock"
    ? o.holdings.filter((h) => h.value_usd !== null).map((h) => ({ key: h.pool, name: h.stock, weight: h.weight_pct, value: h.value_usd }))
    : o.sectors.filter((s) => s.sector !== "(no sector)").map((s) => ({ key: s.sector, name: s.sector, weight: s.weight_pct, value: s.value_usd }));
  const set = Object.entries(targets).filter(([, v]) => v.trim() !== "");
  const run = async () => {
    setErr(null);
    try {
      setR(await apiFetch<WIRebalResp>("/api/whatif/rebalance", jsonInit("POST", { by, targets: Object.fromEntries(set.map(([k, v]) => [k, Number(v)])) })));
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    }
  };
  return (
    <div className="space-y-4">
      <Section title="Targets" right={<span className="flex gap-2">
        <span role="group" className="inline-flex overflow-hidden rounded border border-slate-300 text-xs dark:border-slate-700">
          {(["stock", "sector"] as const).map((k) => <button key={k} aria-pressed={by === k} onClick={() => { setBy(k); setTargets({}); setR(null); }}
            className={`px-2.5 py-1 ${by === k ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>by {k}</button>)}</span>
        <button className={btnPrimary} disabled={!set.length} onClick={run}>Preview</button></span>}>
        {by === "sector" && rows.length === 0 ? <p className="text-sm">No confirmed sectors yet: set or confirm them on <Link className="underline" href="/stocks">Data ▾ Names</Link>.</p> : (
          <div className="max-h-96 overflow-auto">
            <table className="tbl num w-full text-sm">
              <thead className="sticky top-0 bg-white dark:bg-slate-900"><tr><th>{by === "stock" ? "Stock" : "Sector"}</th><th className="text-right">Value</th><th className="text-right">Weight now</th><th>Target %</th></tr></thead>
              <tbody>{rows.map((x) => (
                <tr key={x.key}><td>{x.name}</td><td className="text-right">{usd(x.value)}</td><td className="text-right">{pct(x.weight, 1, false)}</td>
                  <td><input aria-label={`Target for ${x.name}`} inputMode="decimal" className={`${input} w-20`} placeholder="keep" value={targets[x.key] ?? ""}
                    onChange={(e) => setTargets({ ...targets, [x.key]: e.target.value })} /></td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-slate-500">Set a target only where you want a change; the rest stay as they are. Targets are % of today&apos;s total ({usd(o.total_usd)}).</p>
      </Section>
      <ErrorBox error={err} />
      {r && (
        <Section title="Preview (nothing is traded)">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Sell" value={usd(r.sold_usd)} sub={`${r.trades.filter((t) => t.action === "sell").length} trades`} />
            <Stat label="Buy" value={usd(r.bought_usd)} sub={`${r.trades.filter((t) => t.action === "buy").length} trades`} />
            <Stat label={r.cash_usd >= 0 ? "Cash raised" : "Extra cash needed"} value={usd(Math.abs(r.cash_usd))} />
            <Stat label="Gain realised by the sales" value={<Usd v={r.sale?.totals.gain_usd ?? 0} />} sub="FIFO, before tax" />
          </div>
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            <div className="overflow-x-auto">
              <table className="tbl num w-full text-sm">
                <thead><tr><th>Trade</th><th>Stock</th><th className="text-right">Shares</th><th className="text-right">≈ USD</th><th className="text-right">Gain</th></tr></thead>
                <tbody>{r.trades.length === 0 ? <tr><td colSpan={5} className="text-slate-500">No whole-share trades needed.</td></tr> : r.trades.map((t) => (
                  <tr key={t.pool + t.action}><td>{t.action === "buy" ? "Buy" : "Sell"}</td><td>{t.stock}</td><td className="text-right">{qty(t.shares)}</td><td className="text-right">{usd(t.value_usd)}</td>
                    <td className="text-right">{t.action === "sell" ? <Usd v={r.sale?.sales.find((s) => s.pool === t.pool)?.gain_usd} /> : ""}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <div className="overflow-x-auto">
              <table className="tbl num w-full text-sm">
                <thead><tr><th>{r.by === "stock" ? "Stock" : "Sector"}</th><th className="text-right">Before</th><th className="text-right">Target</th><th className="text-right">After</th></tr></thead>
                <tbody>{r.rows.filter((x) => x.target_pct !== null || Math.abs(x.after_usd - x.before_usd) > 0.5).map((x) => (
                  <tr key={x.key}><td>{x.name}</td><td className="text-right">{pct(x.before_pct, 1, false)}</td><td className="text-right">{x.target_pct === null ? "—" : pct(x.target_pct, 1, false)}</td>
                    <td className="text-right">{pct(x.after_pct, 1, false)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </div>
          <p className="mt-2 text-xs text-slate-500">{r.note} Before tax, at current prices.</p>
        </Section>
      )}
    </div>
  );
}

export default function WhatIfPage() {
  const q = useApi<WIOverview>("/api/whatif");
  const [tab, setTab] = useState<"sell" | "rebalance">("sell");
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">What-if</h1>
      <Note tone="slate">Simulations only: nothing is sold, bought or saved. FIFO (oldest purchases first), before tax, at each position&apos;s latest price
        ({q.data.as_of}). You can also just <Link className="underline" href="/ask">ask</Link> in words.</Note>
      <div role="tablist" className="inline-flex overflow-hidden rounded border border-slate-300 text-sm dark:border-slate-700">
        {(["sell", "rebalance"] as const).map((k) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
          className={`px-3 py-1 ${tab === k ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>{k === "sell" ? "If I sell…" : "Rebalance"}</button>)}
      </div>
      {tab === "sell" ? <SellTab o={q.data} /> : <RebalanceTab o={q.data} />}
    </div>
  );
}
