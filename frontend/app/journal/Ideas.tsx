"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Loading, Section, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, notifyStatus, useApi } from "@/lib/api";
import { num, pct } from "@/lib/format";

type Level = { label: string; kind: "entry" | "target" | "stop" | "alert"; price: number; distance_pct?: number | null };
type Event = { id: number; label: string; level: number; kind: "near" | "hit"; date: string; price: number; seen: boolean };
export type Idea = {
  id: number; stock: string; ticker: string; exchange: string; side: "buy" | "sell" | "watch"; near_pct: number; levels: Level[];
  reasons: string[]; confidence: number | null; notes: string | null; status: "watching" | "done" | "dropped"; listing_id: number | null;
  price_error: string | null; bought_key: string | null; created_at: string; last: { date: string; close: number } | null; events: Event[];
};
type IdeasResp = { ideas: Idea[]; unseen: number; kinds: string[]; sides: string[]; exchanges: string[]; tags: { reasons: string[] } };
type Buy = { key: string; date: string; stock: string; shares: number; price: number };
type FibLevel = { ratio: number; kind: string; price: number };

const KIND_LABEL: Record<string, string> = { entry: "Entry", target: "Target", stop: "Stop", alert: "Alert" };
const blank = { ticker: "", exchange: "US", stock: "", side: "buy" as Idea["side"], near_pct: 3, levels: [{ label: "Entry", kind: "entry", price: 0 }] as Level[],
  reasons: [] as string[], confidence: null as number | null, notes: "" };

function IdeaForm({ idea, opts, onDone, onCancel }: { idea?: Idea; opts: IdeasResp; onDone: () => void; onCancel: () => void }) {
  const [f, setF] = useState(() => idea ? { ticker: idea.ticker, exchange: idea.exchange, stock: idea.stock, side: idea.side, near_pct: idea.near_pct,
    levels: idea.levels.map(({ label, kind, price }) => ({ label, kind, price })), reasons: idea.reasons, confidence: idea.confidence, notes: idea.notes ?? "" } : blank);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [fib, setFib] = useState<FibLevel[] | null>(null);
  useEffect(() => {
    if (!idea?.listing_id) return;
    apiFetch<{ fibonacci?: { status: string; levels?: FibLevel[] } }>(`/research/api/listings/${idea.listing_id}/analysis`)
      .then((a) => setFib(a.fibonacci?.status === "ok" ? a.fibonacci.levels ?? [] : [])).catch(() => setFib([]));
  }, [idea?.listing_id]);
  const setLevel = (i: number, patch: Partial<Level>) => setF({ ...f, levels: f.levels.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = { ...f, levels: f.levels.filter((l) => l.price > 0) };
      if (idea) await apiFetch(`/api/journal/ideas/${idea.id}`, jsonInit("PUT", body));
      else await apiFetch("/api/journal/ideas", jsonInit("POST", body));
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3 rounded border border-slate-200 p-3 dark:border-slate-700">
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-xs">Ticker<input aria-label="Ticker" disabled={!!idea} className={`${input} w-24 uppercase`} value={f.ticker}
          onChange={(e) => setF({ ...f, ticker: e.target.value })} placeholder="PYPL" /></label>
        <label className="flex flex-col gap-1 text-xs">Exchange<select disabled={!!idea} className={input} value={f.exchange} onChange={(e) => setF({ ...f, exchange: e.target.value })}>
          {opts.exchanges.map((x) => <option key={x} value={x}>{x === "US" ? "US" : x}</option>)}</select></label>
        <label className="flex flex-col gap-1 text-xs">Name<input className={`${input} w-48`} value={f.stock} onChange={(e) => setF({ ...f, stock: e.target.value })} placeholder="PayPal" /></label>
        <label className="flex flex-col gap-1 text-xs">Idea<select className={input} value={f.side} onChange={(e) => setF({ ...f, side: e.target.value as Idea["side"] })}>
          <option value="buy">Buy</option><option value="sell">Sell / trim</option><option value="watch">Just watch</option></select></label>
        <label className="flex flex-col gap-1 text-xs" title="A level counts as near when a day's close is within this % of it">Near = within
          <span className="flex items-center gap-1"><input inputMode="decimal" className={`${input} w-14`} value={f.near_pct} onChange={(e) => setF({ ...f, near_pct: Number(e.target.value) || 0 })} />%</span></label>
      </div>
      <div>
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Price levels{idea?.last && <span className="ml-2 font-normal normal-case">last close {num(idea.last.close)} ({idea.last.date})</span>}</div>
        <div className="space-y-1.5">
          {f.levels.map((l, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <select aria-label="Level type" className={input} value={l.kind} onChange={(e) => setLevel(i, { kind: e.target.value as Level["kind"] })}>
                {opts.kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select>
              <input aria-label="Level price" inputMode="decimal" className={`${input} w-24`} value={l.price || ""} placeholder="price"
                onChange={(e) => setLevel(i, { price: Number(e.target.value) || 0 })} />
              <input aria-label="Level name" className={`${input} w-56`} value={l.label} onChange={(e) => setLevel(i, { label: e.target.value })} />
              <button className="text-xs underline" onClick={() => setF({ ...f, levels: f.levels.filter((_, j) => j !== i) })}>remove</button>
            </div>
          ))}
        </div>
        <button className="mt-1.5 text-xs underline" onClick={() => setF({ ...f, levels: [...f.levels, { label: `Alert ${f.levels.length + 1}`, kind: "alert", price: 0 }] })}>+ add a level</button>
        {fib && fib.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs"><span className="text-slate-500">Fibonacci levels:</span>
            {fib.map((x) => { const label = `${(x.ratio * 100).toFixed(1)}% ${x.kind}`; return (
              <button key={label} className="rounded-full border border-slate-300 px-2 py-0.5 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
                onClick={() => setF({ ...f, levels: [...f.levels.filter((l) => l.label !== label), { label, kind: "alert", price: Math.round(x.price * 100) / 100 }] })}>+ {label} {num(x.price)}</button>); })}
          </div>
        )}
        {!idea && <p className="mt-1 text-xs text-slate-500">Saving downloads the stock&apos;s daily prices into Research (like φ); then the Fibonacci levels can be added here with one click.</p>}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {opts.tags.reasons.map((t) => { const on = f.reasons.includes(t); return (
          <button key={t} aria-pressed={on} onClick={() => setF({ ...f, reasons: on ? f.reasons.filter((x) => x !== t) : [...f.reasons, t] })}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900" : "border-slate-300 dark:border-slate-700"}`}>{t}</button>); })}
        <select aria-label="Confidence" className={`${input} text-xs`} value={f.confidence ?? ""} onChange={(e) => setF({ ...f, confidence: e.target.value ? Number(e.target.value) : null })}>
          <option value="">confidence —</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} of 5</option>)}</select>
      </div>
      <textarea aria-label="Notes" rows={2} className={`${input} w-full`} placeholder="Why, and what would make you act" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      {err && <p className="text-sm text-rose-700 dark:text-rose-400">{err}</p>}
      <div className="flex gap-2"><button className={btnPrimary} disabled={busy || (!idea && !f.ticker.trim())} onClick={save}>{busy ? (idea ? "Saving…" : "Downloading prices…") : "Save idea"}</button>
        <button className={btn} onClick={onCancel}>Cancel</button></div>
    </div>
  );
}

function LevelState({ l, events, isNew }: { l: Level; events: Event[]; isNew: (e: Event) => boolean }) {
  const hit = events.find((e) => e.label === l.label && e.kind === "hit");
  const near = events.find((e) => e.label === l.label && e.kind === "near");
  const e = hit ?? near;
  if (!e) return <span className="text-slate-400">waiting</span>;
  return (
    <span className={`whitespace-nowrap ${isNew(e) ? "font-semibold" : ""}`}>
      <span aria-hidden className={hit ? "text-emerald-700 dark:text-emerald-400" : "text-amber-600"}>{hit ? "●" : "◐"}</span>{" "}
      {hit ? "hit" : "near"} {e.date} at {num(e.price)}{isNew(e) && <span className="ml-1 rounded bg-amber-500 px-1 text-[10px] font-bold text-slate-950">NEW</span>}
    </span>
  );
}

function Bought({ idea, onDone }: { idea: Idea; onDone: () => void }) {
  const q = useApi<{ buys: Buy[] }>(`/api/journal/ideas/${idea.id}/buys`);
  if (!q.data) return <Loading label="Looking for your buys…" />;
  if (!q.data.buys.length) return <p className="text-xs text-slate-500">No buy of {idea.stock} since {idea.created_at.slice(0, 10)} yet. Once it&apos;s in your
    workbook upload or on the Trades page, choose it here and the idea&apos;s plan goes into that buy&apos;s journal entry.</p>;
  return (
    <div className="text-xs"><span className="text-slate-500">Which buy was it?</span>
      <ul className="mt-1 space-y-1">{q.data.buys.map((b) => (
        <li key={b.key}><button className="underline" onClick={async () => { await apiFetch(`/api/journal/ideas/${idea.id}/bought`, jsonInit("POST", { key: b.key })); onDone(); }}>
          {b.date}: {b.stock}, {num(b.shares, 0)} @ {num(b.price)}</button></li>
      ))}</ul>
    </div>
  );
}

export function Ideas({ onOpenTrade }: { onOpenTrade: (key: string) => void }) {
  const q = useApi<IdeasResp>("/api/journal/ideas");
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [bought, setBought] = useState<number | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const fresh = useRef<Set<number> | null>(null);
  useEffect(() => {  // remember what was new when the tab opened, then clear the menu badge
    if (!q.data || fresh.current) return;
    fresh.current = new Set(q.data.ideas.flatMap((i) => i.events.filter((e) => !e.seen).map((e) => e.id)));
    if (fresh.current.size) apiFetch("/api/journal/ideas/seen", { method: "POST" }).then(notifyStatus).catch(() => {});
  }, [q.data]);
  if (!q.data) return <Loading />;
  const d = q.data;
  const isNew = (e: Event) => fresh.current?.has(e.id) ?? !e.seen;
  const open = d.ideas.filter((i) => i.status === "watching");
  const closed = d.ideas.filter((i) => i.status !== "watching");
  const setStatus = async (i: Idea, status: Idea["status"]) => { await apiFetch(`/api/journal/ideas/${i.id}`, jsonInit("PUT", { status })); q.reload(); };
  const card = (i: Idea) => (
    <li key={i.id} className="card space-y-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${i.side === "buy" ? "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200" : i.side === "sell" ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200" : "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100"}`}>{i.side}</span>
        <b>{i.stock}</b><span className="text-sm text-slate-500">{i.ticker}{i.exchange !== "US" && ` · ${i.exchange}`}</span>
        {i.last && <span className="num text-sm">{num(i.last.close)} <span className="text-xs text-slate-500">({i.last.date})</span></span>}
        {i.status !== "watching" && <span className="text-xs text-slate-500">{i.status === "done" ? "carried out" : "dropped"}</span>}
        <span className="ml-auto flex flex-wrap gap-2 text-xs">
          {i.listing_id && <Link className="underline" href={`/research/analysis/${i.listing_id}`}>chart</Link>}
          <button className="underline" onClick={() => setEditing(i.id)}>edit</button>
          {i.status === "watching" && i.side === "buy" && <button className="underline" onClick={() => setBought(bought === i.id ? null : i.id)}>I bought it</button>}
          {i.bought_key && <button className="underline" onClick={() => onOpenTrade(i.bought_key!)}>the buy</button>}
          {i.status === "watching" ? <button className="underline" onClick={() => setStatus(i, "dropped")}>drop</button>
            : <button className="underline" onClick={() => setStatus(i, "watching")}>watch again</button>}
          <button className="underline" onClick={async () => { if (confirm(`Delete the idea for ${i.stock}?`)) { await apiFetch(`/api/journal/ideas/${i.id}`, { method: "DELETE" }); q.reload(); } }}>delete</button>
        </span>
      </div>
      {i.price_error && <p className="text-xs text-rose-700 dark:text-rose-400">No prices yet: {i.price_error}{" "}
        <button className="underline" onClick={async () => { await apiFetch(`/api/journal/ideas/${i.id}`, jsonInit("PUT", { retry_prices: true })); q.reload(); }}>try again</button></p>}
      {editing === i.id ? <IdeaForm idea={i} opts={d} onDone={() => { setEditing(null); q.reload(); }} onCancel={() => setEditing(null)} /> : (
        <>
          {i.levels.length > 0 && (
            <div className="overflow-x-auto">
              <table className="tbl num w-full text-sm">
                <thead><tr><th>Level</th><th></th><th className="text-right">Price</th><th className="text-right" title="From the last close">Away</th><th>Status</th></tr></thead>
                <tbody>{i.levels.map((l) => (
                  <tr key={l.label}><td>{l.label}</td><td className="text-xs text-slate-500">{KIND_LABEL[l.kind]}</td><td className="text-right">{num(l.price)}</td>
                    <td className="text-right">{pct(l.distance_pct, 1)}</td><td><LevelState l={l} events={i.events} isNew={isNew} /></td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {(i.reasons.length > 0 || i.notes || i.confidence) && (
            <p className="text-sm text-slate-600 dark:text-slate-300">{i.reasons.join(", ")}{i.confidence && ` · confidence ${i.confidence}/5`}{i.notes && <> · {i.notes}</>}</p>
          )}
          <p className="text-xs text-slate-500">Written {i.created_at.slice(0, 10)} · near = within {num(i.near_pct, 1)}% of a level · checked after every price refresh</p>
          {bought === i.id && <Bought idea={i} onDone={() => { setBought(null); q.reload(); }} />}
        </>
      )}
    </li>
  );
  return (
    <div className="space-y-4">
      <Section title={`Ideas you're watching (${open.length})`} right={editing !== "new" ? <button className={btn} onClick={() => setEditing("new")}>+ New idea</button> : undefined}>
        <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">Write down a trade before you make it: the stock, the price levels that matter (entry, target, stop,
          or any level to watch) and why. After every price refresh the app checks each level and flags it when a close comes <b>near</b> it or the day&apos;s
          range <b>hits</b> it; new ones show as a badge on Journal. When you buy, <b>I bought it</b> copies the plan into that buy&apos;s journal entry.</p>
        {editing === "new" && <IdeaForm opts={d} onDone={() => { setEditing(null); q.reload(); }} onCancel={() => setEditing(null)} />}
        {open.length === 0 && editing !== "new" ? <p className="text-sm text-slate-500">No ideas yet.</p> : <ul className="mt-3 space-y-3">{open.map(card)}</ul>}
      </Section>
      {closed.length > 0 && (
        <Section title={`Carried out or dropped (${closed.length})`} right={<button className="text-sm underline" onClick={() => setShowClosed(!showClosed)}>{showClosed ? "hide" : "show"}</button>}>
          {showClosed ? <ul className="space-y-3">{closed.map(card)}</ul> : <p className="text-sm text-slate-500">{closed.map((i) => i.stock).join(", ")}</p>}
        </Section>
      )}
    </div>
  );
}
