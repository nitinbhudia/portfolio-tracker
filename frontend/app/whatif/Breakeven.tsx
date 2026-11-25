"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorBox, Section, Stat, btn, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type PositionsResp } from "@/lib/api";
import { buyMore, cents, defaultSteps, holding, roundTargets, sharesForBudget, sharesForTarget } from "@/lib/breakeven";
import { num, pct, qty } from "@/lib/format";

type Lot = { shares: number | null; price: number | null; fee: number | null; date?: string | null };
export type Calc = { id: string; name: string; currency: string; lots: Lot[]; price: number | null; buy_price: number | null; buy_fee: number | null;
  steps: number[]; target: number | null; budget: number | null; pool?: string | null; notes?: string | null;
  ticker?: string | null; exchange?: string | null; watch_id?: number | null };

const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const blank = (): Calc => ({ id: newId(), name: "", currency: "USD", lots: [{ shares: null, price: null, fee: null }], price: null, buy_price: null,
  buy_fee: null, steps: [], target: null, budget: null });
const money = (v: number | null | undefined, cur: string) => (v == null ? "—"
  : `${v < 0 ? "−" : ""}${cur === "USD" ? "$" : ""}${num(Math.abs(cents(v)))}${cur === "USD" ? "" : ` ${cur}`}`);
const toNum = (s: string): number | null => (s.trim() === "" || isNaN(Number(s.replace(/,/g, ""))) ? null : Number(s.replace(/,/g, "")));

/** A number box that keeps what you type (e.g. "633.") and reports the number. */
function NumBox({ value, onChange, label, w = "w-24", placeholder }: { value: number | null; onChange: (v: number | null) => void; label: string; w?: string; placeholder?: string }) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => { if (toNum(text) !== value) setText(value == null ? "" : String(value)); }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return <input aria-label={label} inputMode="decimal" className={`${input} num ${w}`} value={text} placeholder={placeholder}
    onChange={(e) => { setText(e.target.value); onChange(toNum(e.target.value)); }} />;
}

const EXCHANGES = ["US", "XETR", "XAMS", "XPAR", "XSWX", "XLON"];

/** Put the buy-more price (and the break-even) on the journal's opportunity watch list: flagged within 10%, 5%, and when hit. */
function WatchButton({ c, buyAt, average, onChange }: { c: Calc; buyAt: number | null; average: number | null; onChange: (p: Partial<Calc>) => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const cur = c.currency || "USD";
  const add = async () => {
    if (!c.ticker || buyAt == null) return;
    setBusy(true);
    setMsg(null);
    try {
      const levels = [{ label: `Buy more at ${num(buyAt)}`, kind: "entry", price: buyAt },
        ...(average != null && Math.abs(average - buyAt) / buyAt > 0.005 ? [{ label: "Back to break-even", kind: "target", price: Math.round(average * 100) / 100 }] : [])];
      const i = await apiFetch<{ id: number; price_error: string | null }>("/api/journal/ideas", jsonInit("POST", {
        ticker: c.ticker, exchange: c.exchange || "US", stock: c.name || c.ticker, side: "buy", levels, alert_pcts: [10, 5],
        notes: `From the break-even calculator: break-even ${money(average, cur)}; buying more at ${money(buyAt, cur)} ${average != null && buyAt < average ? "lowers" : "raises"} it.` }));
      onChange({ watch_id: i.id });
      setMsg(i.price_error ? `Added, but no prices yet: ${i.price_error}` : null);
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded border border-amber-300 bg-amber-50/60 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/30">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">Opportunity watch list</span>
        {c.watch_id ? (
          <span>✓ Watching {money(buyAt, cur)}: you&apos;ll be flagged when the price is within 10%, then 5%, and when it&apos;s reached.{" "}
            <Link className="underline" href="/whatif?tab=watch">Open the watch list</Link>{" "}
            <button className="text-xs underline" onClick={() => onChange({ watch_id: null })}>add again</button></span>
        ) : (
          <>
            <label className="flex items-center gap-1 text-xs">Ticker<input aria-label="Ticker" className={`${input} w-20 uppercase`} value={c.ticker ?? ""} placeholder="MU"
              onChange={(e) => onChange({ ticker: e.target.value.toUpperCase().trim() || null })} /></label>
            <select aria-label="Exchange" className={`${input} text-xs`} value={c.exchange ?? "US"} onChange={(e) => onChange({ exchange: e.target.value })}>
              {EXCHANGES.map((x) => <option key={x} value={x}>{x}</option>)}</select>
            <button className={btn} disabled={busy || !c.ticker || buyAt == null} onClick={add}>
              {busy ? "Adding (downloading prices)…" : `☆ Watch for ${buyAt != null ? money(buyAt, cur) : "a buy price"}`}</button>
            <span className="text-xs text-slate-500">{!c.ticker ? "enter the ticker to watch its price" : buyAt == null ? "enter a price to buy more at" : "flags within 10% and 5%, then when it's reached"}</span>
          </>
        )}
      </div>
      {msg && <p className="mt-1 text-xs text-rose-700 dark:text-rose-400">{msg}</p>}
    </div>
  );
}

function CalcCard({ c, onChange, onRemove, onCopy }: { c: Calc; onChange: (c: Calc) => void; onRemove: () => void; onCopy: () => void }) {
  const [stepText, setStepText] = useState("");
  const h = holding(c.lots);
  const cur = c.currency || "USD";
  const buyAt = c.buy_price ?? c.price;
  const fee = c.buy_fee ?? 0;
  const steps = c.steps.length ? c.steps : defaultSteps(h);
  const set = (p: Partial<Calc>) => onChange({ ...c, ...p });
  const setLot = (i: number, p: Partial<Lot>) => set({ lots: c.lots.map((l, j) => (j === i ? { ...l, ...p } : l)) });
  const pl = c.price != null && h.shares ? h.shares * c.price - h.cost : null;
  const rows = buyAt != null && h.average != null ? steps.map((n) => buyMore(h, buyAt, n, fee)) : [];
  const targets = buyAt != null ? roundTargets(h, buyAt) : [];
  const tShares = buyAt != null && c.target != null ? sharesForTarget(h, buyAt, c.target, fee) : null;
  const bShares = buyAt != null && c.budget != null ? sharesForBudget(c.budget, buyAt, fee) : null;
  const addStep = () => {
    const n = Math.round(toNum(stepText) ?? 0);
    if (n > 0) set({ steps: [...new Set([...steps, n])].sort((a, b) => a - b) });
    setStepText("");
  };
  return (
    <li className="card space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label="Stock" className={`${input} w-80 max-w-full font-semibold`} placeholder="Stock (e.g. Micron)" value={c.name} onChange={(e) => set({ name: e.target.value })} />
        <input aria-label="Currency" className={`${input} w-16 uppercase`} value={c.currency} onChange={(e) => set({ currency: e.target.value.toUpperCase().slice(0, 5) })} />
        {c.pool && <span className="text-xs text-slate-500">from your positions</span>}
        <span className="ml-auto flex gap-3 text-xs"><button className="underline" onClick={onCopy}>duplicate</button>
          <button className="underline" onClick={() => { if (confirm(`Remove ${c.name || "this calculation"}?`)) onRemove(); }}>remove</button></span>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Your buys</h3>
          <div className="overflow-x-auto">
            <table className="tbl num w-full text-sm">
              <thead><tr><th>Shares</th><th>Price</th><th title="Optional: fees count in your break-even">Fee</th><th className="text-right">Cost</th><th></th></tr></thead>
              <tbody>
                {c.lots.map((l, i) => (
                  <tr key={i}>
                    <td><NumBox label={`Shares, buy ${i + 1}`} value={l.shares} onChange={(v) => setLot(i, { shares: v })} w="w-20" placeholder="6" /></td>
                    <td><NumBox label={`Price, buy ${i + 1}`} value={l.price} onChange={(v) => setLot(i, { price: v })} placeholder="883" /></td>
                    <td><NumBox label={`Fee, buy ${i + 1}`} value={l.fee} onChange={(v) => setLot(i, { fee: v })} w="w-16" placeholder="0" /></td>
                    <td className="text-right">{l.shares && l.price != null ? money(l.shares * l.price + (l.fee ?? 0), cur) : "—"}</td>
                    <td><button className="text-xs underline" aria-label={`Remove buy ${i + 1}`} onClick={() => set({ lots: c.lots.filter((_, j) => j !== i) })}>×</button></td>
                  </tr>
                ))}
                <tr className="font-semibold"><td>{qty(h.shares)}</td><td colSpan={2} className="text-slate-500">total</td><td className="text-right">{money(h.cost, cur)}</td><td></td></tr>
              </tbody>
            </table>
          </div>
          <button className="mt-1 text-xs underline" onClick={() => set({ lots: [...c.lots, { shares: null, price: null, fee: null }] })}>+ add a buy</button>
        </div>
        <div className="grid grid-cols-2 gap-3 self-start">
          <Stat label="Break-even (average cost)" value={money(h.average, cur)} sub={h.fees ? `includes ${money(h.fees, cur)} fees` : `${qty(h.shares)} shares`} />
          <div className="card">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Price now</div>
            <NumBox label="Price now" value={c.price} onChange={(v) => set({ price: v })} w="mt-1 w-28" placeholder="633.55" />
          </div>
          <Stat label="Gain / loss" value={pl == null ? "—" : <span className={pl < 0 ? "text-rose-700 dark:text-rose-400" : "text-emerald-700 dark:text-emerald-400"}>{money(pl, cur)}</span>}
            sub={pl != null && h.cost ? pct((pl / h.cost) * 100, 1) : "enter the price now"} />
          <Stat label="Rise needed to break even" value={c.price && h.average ? (c.price >= h.average ? "in profit" : pct((h.average / c.price - 1) * 100, 1)) : "—"}
            sub={c.price && h.average && c.price >= h.average ? "already above break-even" : "from the price now"} />
        </div>
      </div>

      {h.average != null && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3 text-sm">
            <label className="flex flex-col gap-1 text-xs">Buy more at<NumBox label="Buy more at" value={c.buy_price} onChange={(v) => set({ buy_price: v })}
              placeholder={c.price != null ? String(c.price) : "price"} /></label>
            <label className="flex flex-col gap-1 text-xs">Fee per buy<NumBox label="Fee per buy" value={c.buy_fee} onChange={(v) => set({ buy_fee: v })} w="w-16" placeholder="0" /></label>
            <span className="text-xs text-slate-500">{c.buy_price == null && c.price != null ? "using the price now. " : ""}
              {buyAt != null && h.average != null && buyAt > h.average ? "Buying above your break-even raises it (averaging up)." : ""}</span>
          </div>
          {buyAt == null ? <p className="text-sm text-slate-500">Enter the price now, or a price to buy more at, to see what averaging does.</p> : (
            <>
              <div className="overflow-x-auto">
                <table className="tbl num w-full text-sm">
                  <thead><tr><th className="text-right">Additional shares</th><th className="text-right">Extra investment</th><th className="text-right">Total shares</th>
                    <th className="text-right">New average (break-even)</th><th className="text-right">Change in average</th>
                    <th className="text-right" title="From the buy price up to the new average">Rise needed</th><th></th></tr></thead>
                  <tbody>{rows.map((r) => (
                    <tr key={r.add}><td className="text-right">{qty(r.add)}</td><td className="text-right">{money(r.extra, cur)}</td><td className="text-right">{qty(r.shares)}</td>
                      <td className="text-right font-semibold">{money(r.average, cur)}</td><td className="text-right">{r.change > 0 ? "+" : r.change < 0 ? "−" : ""}{money(Math.abs(r.change), cur)}</td>
                      <td className="text-right">{r.riseNeededPct != null && r.riseNeededPct > 0 ? pct(r.riseNeededPct, 1) : "in profit"}</td>
                      <td>{c.steps.length > 0 && <button className="text-xs underline" aria-label={`Remove the ${r.add} shares row`} onClick={() => set({ steps: steps.filter((x) => x !== r.add) })}>×</button>}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <input aria-label="Add a row: shares" inputMode="numeric" className={`${input} w-20`} placeholder="shares" value={stepText}
                  onChange={(e) => setStepText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addStep()} />
                <button className="underline" onClick={addStep}>+ add a row</button>
                {c.steps.length > 0 && <button className="underline" onClick={() => set({ steps: [] })}>back to the default rows</button>}
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="rounded bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
                  <div className="mb-1 font-semibold">To bring your average down to…</div>
                  <ul className="space-y-0.5">
                    {targets.map((t) => { const n = sharesForTarget(h, buyAt, t, fee); return n == null ? null : (
                      <li key={t}>below {money(t, cur)}: <b>{qty(n)} more {n === 1 ? "share" : "shares"}</b> ({money(buyMore(h, buyAt, n, fee).extra, cur)}) → {money(buyMore(h, buyAt, n, fee).average, cur)}</li>); })}
                    <li className="flex flex-wrap items-center gap-2 pt-1">your own target <NumBox label="Target average" value={c.target} onChange={(v) => set({ target: v })} w="w-24" />
                      {c.target != null && (tShares == null
                        ? <span className="text-slate-500">{c.target <= buyAt ? `can't go below the buy price (${money(buyAt, cur)})` : "your average is already there"}</span>
                        : <span><b>{qty(tShares)} more {tShares === 1 ? "share" : "shares"}</b> ({money(buyMore(h, buyAt, tShares, fee).extra, cur)}) → {money(buyMore(h, buyAt, tShares, fee).average, cur)}</span>)}</li>
                  </ul>
                </div>
                <div className="rounded bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
                  <div className="mb-1 font-semibold">If I spend…</div>
                  <div className="flex flex-wrap items-center gap-2"><NumBox label="Budget" value={c.budget} onChange={(v) => set({ budget: v })} w="w-28" placeholder="5000" />
                    {bShares != null && (bShares === 0 ? <span className="text-slate-500">not enough for 1 share</span>
                      : <span>buys <b>{qty(bShares)} {bShares === 1 ? "share" : "shares"}</b> → average {money(buyMore(h, buyAt, bShares, fee).average, cur)} ({money(c.budget! - buyMore(h, buyAt, bShares, fee).extra, cur)} left)</span>)}</div>
                </div>
              </div>
              <WatchButton c={c} buyAt={buyAt} average={h.average} onChange={set} />
              <p className="text-sm">Formula: <b className="num">new average = ({money(h.cost, cur)}{fee ? ` + ${money(fee, cur)}` : ""} + {money(buyAt, cur)} × additional shares) ÷ ({qty(h.shares)} + additional shares)</b></p>
              <p className="text-xs text-slate-500">Any buy below your break-even lowers it, but doesn&apos;t make a profit more likely: it puts more money into the same stock. You are in profit
                only when the price rises above the new average{fee ? "" : " (fees and taxes not included unless you enter them)"}.</p>
            </>
          )}
        </div>
      )}
    </li>
  );
}

export default function BreakevenTab({ pool }: { pool?: string | null }) {
  const [calcs, setCalcs] = useState<Calc[] | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState<"saved" | "saving" | null>(null);
  const [positions, setPositions] = useState<PositionsResp | null>(null);
  const [pick, setPick] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadedPool = useRef(false);

  useEffect(() => {
    apiFetch<{ calcs: Calc[] }>("/api/breakeven").then((r) => setCalcs(r.calcs.length ? r.calcs : [blank()]))
      .catch((e) => setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0)));
    apiFetch<PositionsResp>("/api/positions").then(setPositions).catch(() => setPositions(null));
  }, []);

  const save = useCallback((next: Calc[]) => {
    setCalcs(next);
    setSaved("saving");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      apiFetch("/api/breakeven", jsonInit("PUT", { calcs: next })).then(() => setSaved("saved"))
        .catch((e) => { setSaved(null); setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0)); });
    }, 600);
  }, []);

  const fromPosition = useCallback((poolKey: string, list: Calc[]) => {
    const p = positions?.positions.find((x) => x.pool === poolKey);
    if (!p) return list;
    const s = p.pence ? 0.01 : 1;
    const c: Calc = { ...blank(), name: p.stock, currency: p.currency, pool: p.pool, ticker: p.ticker ?? null, exchange: "US", price: p.price != null ? p.price * s : null,
      lots: p.lots.map((l) => ({ shares: l.shares, price: Math.round(l.price * s * 1e6) / 1e6, date: l.date,
        fee: Math.round(Math.max(0, l.cost_local - l.shares * l.price * s) * 100) / 100 || null })) };
    const rest = list.filter((x) => x.pool !== poolKey && !(list.length === 1 && !x.name && !x.lots.some((l) => l.shares))); // replace an empty first card
    return [c, ...rest];
  }, [positions]);

  useEffect(() => {  // opened from Positions with ?pool=…: load that position on top
    if (!pool || loadedPool.current || !calcs || !positions) return;
    loadedPool.current = true;
    const existing = calcs.find((x) => x.pool === pool);
    if (!existing) save(fromPosition(pool, calcs));
  }, [pool, calcs, positions, fromPosition, save]);

  const held = useMemo(() => (positions?.positions ?? []).filter((p) => p.shares > 0), [positions]);
  if (err && !calcs) return <ErrorBox error={err} />;
  if (!calcs) return null;
  return (
    <Section title="Break-even calculator" right={<span className="text-xs text-slate-500" role="status">{saved === "saving" ? "saving…" : saved === "saved" ? "saved" : ""}</span>}>
      <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">Type any stock and the prices you bought at (or load one of your positions): it shows your break-even, and
        what buying more at another price does to it: the extra money, the new average, and how many shares it takes to get the average below a level.
        Saved here as you type.</p>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <button className={btn} onClick={() => save([blank(), ...calcs])}>+ Add a stock</button>
        {held.length > 0 && <>
          <span className="text-slate-500">or load</span>
          <select aria-label="Load one of your positions" className={input} value={pick} onChange={(e) => { setPick(""); if (e.target.value) save(fromPosition(e.target.value, calcs)); }}>
            <option value="">one of your positions…</option>
            {held.map((p) => <option key={p.pool} value={p.pool}>{p.stock} ({qty(p.shares)} shares)</option>)}
          </select></>}
      </div>
      <ErrorBox error={err} />
      <ul className="space-y-4">
        {calcs.map((c, i) => (
          <CalcCard key={c.id} c={c} onChange={(n) => save(calcs.map((x, j) => (j === i ? n : x)))} onRemove={() => save(calcs.filter((_, j) => j !== i))}
            onCopy={() => save([...calcs.slice(0, i + 1), { ...c, id: newId(), name: `${c.name} (copy)`, pool: null }, ...calcs.slice(i + 1)])} />
        ))}
      </ul>
    </Section>
  );
}
