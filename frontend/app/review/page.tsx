"use client";

import { useEffect, useMemo, useState } from "react";

import { Empty, ErrorBox, Loading, Note, Section, btn, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, notifyStatus, type ReviewItem, type ReviewResp, useApi } from "@/lib/api";
import { num, qty } from "@/lib/format";

const BULK: Record<string, { action: string; label: string; explain: string }> = {
  unsold_buy: { action: "exclude", label: "Leave out all remaining shares",
    explain: "Purchases marked Closed (P/L 0) whose shares no sale in the log accounts for, after matching every sale to the oldest purchases of the same stock. Usually sold before the log started (2020) or recorded differently. Leaving them out keeps them out of open positions; enter a sale to include one." },
  closed_no_sale: { action: "exclude", label: "Exclude all of these",
    explain: "Closed rows with a P/L but no sales-log line. If the row is the sale of an earlier purchase (your usual layout, dated on the sale day), choose 'Sale on …'; if the row is both purchase and sale, enter the sale date and price; or exclude." },
  sale_unlinked: { action: "sheet_only", label: "Keep all as sheet-only",
    explain: "Sales typed straight into the log. They stay in your sheet's totals; the app can't rebuild them without a position row. Link one to a row to include it." },
};
const PAGE = 100;

function decisionText(d: Record<string, unknown> | null): string {
  if (!d) return "";
  switch (d.action) {
    case "exclude": return d.scope === "leftover" ? "Remaining shares left out" : "Excluded";
    case "add_buy": return `Purchase entered: ${d.shares} on ${d.date} at ${d.price}`;
    case "sell": return `Sold on ${d.date} at ${d.price}`;
    case "sale_row": return "Treated as a sale on the row's date";
    case "keep_open": return "Kept open (sales-log link ignored)";
    case "keep": return "Kept as it is";
    case "fix": return `Fixed: ${Object.entries((d.fields as Record<string, unknown>) ?? {}).map(([k, v]) => `${k} ${v}`).join(", ")}`;
    case "sheet_only": return "Sheet only (not rebuilt)";
    case "link": return `Linked to row(s) ${(d.rows as number[]).join(", ")}`;
    default: return String(d.action);
  }
}

function ItemRow({ it, onDone }: { it: ReviewItem; onDone: (msg?: string) => void }) {
  const d = it.data;
  const [date, setDate] = useState("");
  const [price, setPrice] = useState(d.sell_price != null ? String(d.sell_price) : "");
  const [fix, setFix] = useState({ currency: d.currency ?? "", shares: String(d.shares ?? ""), price: String(d.price ?? ""), date: d.date ?? "", pence: false });
  const [rows, setRows] = useState("");
  const [buy, setBuy] = useState({ date: "", price: String(d.price ?? ""), shares: String(d.missing_shares ?? d.shares ?? "") });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (body: unknown) => {
    setBusy(true);
    setErr(null);
    try {
      await apiFetch(`/api/review/${it.key}`, jsonInit("PUT", body));
      notifyStatus();
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const undo = async () => {
    await apiFetch(`/api/review/${it.key}`, { method: "DELETE" }).catch(() => {});
    notifyStatus();
    onDone();
  };
  const isSale = it.key.startsWith("S");
  return (
    <li className="border-t border-slate-100 py-3 text-sm first:border-t-0 dark:border-slate-800">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-xs text-slate-500">{isSale ? "Sales log" : "Row"} {it.row}</span>
        <b>{isSale ? d.stock : d.name}</b>
        {!isSale && <span className="num text-slate-600 dark:text-slate-300">bought {d.date} · {qty(d.shares)} @ {num(d.price, 4)} {d.currency} · {d.broker} · {d.status}</span>}
        {!isSale && d.sheet_pl != null && <span className="text-xs text-slate-500">sheet P/L {num(d.sheet_pl)}</span>}
        {isSale && <span className="num text-slate-600 dark:text-slate-300">{d.date} · sheet P/L {num(d.sheet_pl)}{d.formula ? ` · formula ${d.formula}` : ""}</span>}
      </div>
      <div className="mt-0.5 text-xs text-slate-500">{it.detail}</div>
      {it.status === "resolved" ? (
        <div className="mt-1 flex items-center gap-2 text-xs"><span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">{decisionText(it.decision)}</span>
          <button className="underline" onClick={undo}>undo</button></div>
      ) : (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          {it.actions.includes("sell") && (
            <span className="flex flex-wrap items-end gap-1">
              <label className="flex flex-col text-xs">Sale date<input aria-label={`Sale date row ${it.row}`} type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} /></label>
              <label className="flex flex-col text-xs">Sell price ({d.currency}{d.currency === "GBP" ? " pence" : ""})<input aria-label={`Sell price row ${it.row}`} inputMode="decimal" className={`${input} w-28`} value={price} onChange={(e) => setPrice(e.target.value)} /></label>
              <button className={btn} disabled={busy || !date || price === ""} onClick={() => send({ action: "sell", date, price: Number(price) })}>Record sale</button>
            </span>
          )}
          {it.actions.includes("fix") && (
            <span className="flex flex-wrap items-end gap-1">
              <label className="flex flex-col text-xs">Currency<input aria-label={`Currency row ${it.row}`} className={`${input} w-16 uppercase`} value={fix.currency} onChange={(e) => setFix({ ...fix, currency: e.target.value })} /></label>
              <label className="flex flex-col text-xs">Shares<input aria-label={`Shares row ${it.row}`} className={`${input} w-20`} value={fix.shares} onChange={(e) => setFix({ ...fix, shares: e.target.value })} /></label>
              <label className="flex flex-col text-xs">Buy price<input aria-label={`Buy price row ${it.row}`} className={`${input} w-24`} value={fix.price} onChange={(e) => setFix({ ...fix, price: e.target.value })} /></label>
              <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={fix.pence} onChange={(e) => setFix({ ...fix, pence: e.target.checked })} />prices in pence/cents</label>
              <button className={btn} disabled={busy} onClick={() => send({ action: "fix", fields: { currency: fix.currency, shares: fix.shares, price: fix.price, ...(fix.pence ? { pence: true } : {}) } })}>Save fix</button>
            </span>
          )}
          {it.actions.includes("add_buy") && (
            <span className="flex flex-wrap items-end gap-1">
              <label className="flex flex-col text-xs">Bought on<input aria-label={`Purchase date row ${it.row}`} type="date" className={input} value={buy.date} onChange={(e) => setBuy({ ...buy, date: e.target.value })} /></label>
              <label className="flex flex-col text-xs">Shares<input aria-label={`Purchase shares row ${it.row}`} className={`${input} w-20`} value={buy.shares} onChange={(e) => setBuy({ ...buy, shares: e.target.value })} /></label>
              <label className="flex flex-col text-xs">Buy price<input aria-label={`Purchase price row ${it.row}`} className={`${input} w-24`} value={buy.price} onChange={(e) => setBuy({ ...buy, price: e.target.value })} /></label>
              <button className={btn} disabled={busy || !buy.date || !buy.shares || buy.price === ""} onClick={() => send({ action: "add_buy", date: buy.date, shares: Number(buy.shares), price: Number(buy.price) })}>Enter purchase</button>
            </span>
          )}
          {it.actions.includes("sale_row") && d.sell_price != null && (
            <button className={btn} disabled={busy} onClick={() => send({ action: "sale_row" })}>Sale on {d.date} at {num(d.sell_price, 2)}</button>
          )}
          {it.actions.includes("keep_open") && <button className={btn} disabled={busy} onClick={() => send({ action: "keep_open" })}>Keep open</button>}
          {it.actions.includes("keep") && <button className={btn} disabled={busy} onClick={() => send({ action: "keep" })}>Keep as it is</button>}
          {it.actions.includes("link") && (
            <span className="flex items-end gap-1">
              <label className="flex flex-col text-xs">Position row(s)<input aria-label={`Link rows for ${it.row}`} placeholder="e.g. 812, 813" className={`${input} w-32`} value={rows} onChange={(e) => setRows(e.target.value)} /></label>
              <button className={btn} disabled={busy || !rows.trim()} onClick={() => send({ action: "link", rows: rows.split(/[ ,;]+/).filter(Boolean).map(Number) })}>Link</button>
            </span>
          )}
          {it.actions.includes("sheet_only") && <button className={btn} disabled={busy} onClick={() => send({ action: "sheet_only" })}>Keep as sheet-only</button>}
          {it.actions.includes("exclude") && (
            <button className={`${btn} text-rose-700 dark:text-rose-300`} disabled={busy}
              onClick={() => send(it.kind === "unsold_buy" ? { action: "exclude", scope: "leftover" } : { action: "exclude" })}>
              {it.kind === "unsold_buy" ? "Leave out remaining shares" : it.kind === "sale_missing_buy" ? "Exclude this sale" : "Exclude"}
            </button>
          )}
        </div>
      )}
      {err && <div role="alert" className="mt-1 text-xs text-rose-600">{err}</div>}
    </li>
  );
}

export default function ReviewPage() {
  const [which, setWhich] = useState<"pending" | "resolved">("pending");
  const [kind, setKind] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  const [msg, setMsg] = useState<string | null>(null);
  const q = useApi<ReviewResp>(`/api/review?which=${which}`);
  const counts = useMemo<Record<string, number>>(() => q.data?.counts[which] ?? {}, [q.data, which]);
  const kinds = useMemo(() => Object.keys(q.data?.kinds ?? {}).filter((k) => counts[k]), [q.data, counts]);
  useEffect(() => {
    if (q.data && (!kind || !counts[kind])) setKind(kinds[0] ?? null);
  }, [q.data, kind, counts, kinds]);
  useEffect(() => {
    setShown(PAGE);
  }, [kind, which]);

  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const data = q.data;
  const items = q.data.items.filter((i) => i.kind === kind);
  const bulk = kind ? BULK[kind] : undefined;
  const runBulk = async () => {
    if (!kind || !bulk) return;
    const r = await apiFetch<{ applied: number }>("/api/review/bulk", jsonInit("POST", { kind, action: bulk.action }));
    setMsg(`${bulk.label}: applied to ${r.applied} rows.`);
    notifyStatus();
    q.reload();
  };
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Review</h1>
      <Note tone="slate">Rows the app can&apos;t rebuild on its own wait here and are left out of every result until you decide. Nothing is guessed.
        Decisions are saved and kept when you import the same rows again.</Note>
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Pending or done">
        {(["pending", "resolved"] as const).map((w) => (
          <button key={w} role="tab" aria-selected={which === w} onClick={() => setWhich(w)}
            className={`rounded px-3 py-1 text-sm ${which === w ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "border border-slate-300 dark:border-slate-700"}`}>
            {w === "pending" ? "To review" : "Decided"} ({Object.values(data.counts[w]).reduce((a, b) => a + b, 0)})
          </button>
        ))}
      </div>
      {msg && <Note tone="emerald">{msg}</Note>}
      {kinds.length === 0 ? <Empty>{which === "pending" ? "Nothing left to review. 🎉" : "No decisions yet."}</Empty> : (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <nav aria-label="Kinds" className="card flex flex-col gap-1 self-start p-2">
            {kinds.map((k) => (
              <button key={k} onClick={() => setKind(k)} className={`rounded px-2 py-1.5 text-left text-sm ${k === kind ? "bg-slate-100 font-semibold dark:bg-slate-800" : ""}`}>
                {data.kinds[k]} <span className="text-slate-500">({counts[k]})</span>
              </button>
            ))}
          </nav>
          <Section title={kind ? q.data.kinds[kind] : ""} right={which === "pending" && bulk ? <button className={btn} onClick={runBulk}>{bulk.label} ({counts[kind!]})</button> : null}>
            {which === "pending" && bulk && <p className="mb-2 text-xs text-slate-500">{bulk.explain}</p>}
            <ul>{items.slice(0, shown).map((it) => <ItemRow key={it.key} it={it} onDone={() => q.reload()} />)}</ul>
            {items.length > shown && <button className={`${btn} mt-2`} onClick={() => setShown(shown + PAGE)}>Show {Math.min(PAGE, items.length - shown)} more of {items.length - shown}</button>}
          </Section>
        </div>
      )}
    </div>
  );
}
