"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useEffect, useMemo, useState } from "react";

import { type Column, DataTable } from "@/components/DataTable";
import { ErrorBox, Loading, Note, Section, Stat, Usd, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, useApi } from "@/lib/api";

import { GroupControls, type GroupOpt, Star, groupRows, useGrouping } from "./grouping";
import { Ideas } from "./Ideas";
import { num, pct, qty } from "@/lib/format";

type Entry = { reasons: string[]; target: number | null; stop: number | null; horizon_days: number | null; confidence: number | null;
  sell_reason: string | null; lesson: string | null; notes: string | null; skipped: boolean; updated_at: string | null };
type Exc = { best_pct: number; best_date: string; best_price: number; worst_pct: number; worst_date: string; worst_price: number };
type Check = { code: string; good: boolean | null; text: string };
type Row = {
  key: string; id: string; kind: "buy" | "sell"; date: string; stock: string; stock_key: string; pool: string; currency: string; pence: boolean;
  shares: number; price: number; broker: string; source: string; ticker: string | null; entry: Entry | null; status: "done" | "skipped" | "todo";
  from_high_pct?: number | null; market?: { above_200d: boolean; vs_200d_pct: number; change_3m_pct: number | null } | null;
  open_shares?: number; since?: Exc | null;
  gain_usd?: number | null; gain_pct?: number | null; days?: number | null; avg_buy_price?: number | null; spx_gain_usd?: number | null;
  vs_spx_usd?: number | null; excursion?: Exc | null; buy_keys?: string[]; group?: string | null; reasons?: string[]; confidence?: number | null; plan?: Check[];
  starred: boolean; sector: string | null;
};
type Detail = Row & { fibonacci: { listing_id: number; nearest: { ratio: number; kind: string; price: number } | null; direction: string } | null;
  buys?: Row[]; sales?: Row[] };
type View = { rows: Row[]; tags: { reasons: string[]; sell_reasons: string[] }; inbox: string[]; inbox_days: number;
  counts: { trades: number; done: number; skipped: number; todo_recent: number; todo_older: number } };
type Agg = { label: string; sales: number; wins: number; win_rate: number | null; avg_gain_pct: number | null; total_gain_usd: number; avg_days: number | null };
type Stats = { by_reason: Agg[]; by_group: Agg[]; by_sector: Agg[]; by_starred: Agg[]; by_confidence: Agg[]; by_sell_reason: Agg[]; by_holding: Agg[]; sales: number; journaled_sales: number;
  plan: { sales_with_plan: number; followed: number; broke: number; by_code: Record<string, number> };
  left_on_table: { sales: number; gave_back_15: number; examples: { key: string; stock: string; date: string; best_pct: number; gain_pct: number }[] };
  lessons: { key: string; stock: string; date: string; lesson: string }[] };

const unit = (r: Row) => (r.pence ? "p" : r.currency);
const kindTag = (k: string) => (
  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${k === "buy" ? "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200" : "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"}`}>{k}</span>
);

function Chips({ all, value, onChange }: { all: string[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {all.map((t) => {
        const on = value.includes(t);
        return <button key={t} type="button" aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== t) : [...value, t])}
          className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900" : "border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"}`}>{t}</button>;
      })}
    </div>
  );
}

function Context({ d }: { d: Detail }) {
  const lines: [string, React.ReactNode][] = [];
  if (d.kind === "buy") {
    if (d.from_high_pct != null) lines.push(["From its 1-year high", pct(d.from_high_pct, 1)]);
    if (d.market) lines.push(["S&P 500 that day", <>{d.market.above_200d ? "above" : "below"} its 200-day average ({pct(d.market.vs_200d_pct, 1)}){d.market.change_3m_pct != null && <>, {pct(d.market.change_3m_pct, 1)} over 3 months</>}</>]);
    if (d.fibonacci?.nearest) lines.push(["Nearest Fibonacci level", <>{(d.fibonacci.nearest.ratio * 100).toFixed(1)}% {d.fibonacci.nearest.kind} at {num(d.fibonacci.nearest.price)} ({pct((d.price / d.fibonacci.nearest.price - 1) * 100, 1)} from your price)
      {" "}<Link className="underline" href={`/research/analysis/${d.fibonacci.listing_id}`}>chart</Link></>]);
    if (d.open_shares) lines.push(["Still held", `${qty(d.open_shares)} shares`]);
    if (d.since) lines.push(["Since you bought", <>best {pct(d.since.best_pct, 0)} ({d.since.best_date}), worst {pct(d.since.worst_pct, 0)} ({d.since.worst_date})</>]);
  } else {
    lines.push(["Gain", <><Usd v={d.gain_usd} /> ({pct(d.gain_pct, 1)}) after {d.days ?? "?"} days</>]);
    if (d.vs_spx_usd != null) lines.push(["Same money in the S&P 500", <><Usd v={d.spx_gain_usd} /> · you did <Usd v={d.vs_spx_usd} /> {d.vs_spx_usd >= 0 ? "better" : "worse"}</>]);
    if (d.excursion) lines.push(["While you held it", <>best {pct(d.excursion.best_pct, 0)} ({d.excursion.best_date}), worst {pct(d.excursion.worst_pct, 0)} ({d.excursion.worst_date}) from your average buy price {num(d.avg_buy_price)}</>]);
    if (d.group) lines.push(["Group", d.group]);
  }
  if (!lines.length) return <p className="text-xs text-slate-500">No price history for this stock yet, so no automatic context (Data ▾ Price history).</p>;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      {lines.map(([k, v]) => <Fragment key={k}><dt className="text-slate-500">{k}</dt><dd className="num">{v}</dd></Fragment>)}
    </dl>
  );
}

function Editor({ k, tags, onSaved, onClose }: { k: string; tags: View["tags"]; onSaved: () => void; onClose: () => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [f, setF] = useState<Partial<Entry>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setD(null);
    setErr(null);
    apiFetch<Detail>(`/api/journal/entry?key=${encodeURIComponent(k)}`).then((x) => { setD(x); setF(x.entry ?? {}); })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [k]);
  const save = async (skipped = false) => {
    setBusy(true);
    setErr(null);
    try {
      const body = { ...f, skipped, target: f.target ?? null, stop: f.stop ?? null };
      const x = await apiFetch<Detail>(`/api/journal/entry?key=${encodeURIComponent(k)}`, jsonInit("PUT", body));
      setD(x);
      setF(x.entry ?? {});
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const numIn = (field: "target" | "stop" | "horizon_days", label: string, hint: string) => (
    <label className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">{label}
      <input inputMode="decimal" className={`${input} w-28`} value={f[field] ?? ""} placeholder={hint}
        onChange={(e) => setF({ ...f, [field]: e.target.value === "" ? null : Number(e.target.value) })} /></label>
  );
  return (
    <div role="dialog" aria-label="Journal entry" className="card space-y-3">
      <div className="flex items-start justify-between gap-2">
        {d ? <h2 className="text-base font-semibold">{kindTag(d.kind)} {d.stock}
          <span className="ml-2 text-sm font-normal text-slate-500 num">{d.date} · {qty(d.shares)} @ {num(d.price)} {unit(d)} · {d.broker}</span></h2> : <span />}
        <button className="text-sm underline" onClick={onClose}>close</button>
      </div>
      {err && <p className="text-sm text-rose-700 dark:text-rose-400">{err}</p>}
      {!d ? <Loading /> : (
        <>
          <Context d={d} />
          {d.kind === "sell" && d.plan && d.plan.length > 0 && (
            <ul className="space-y-0.5 text-sm" aria-label="Plan vs what happened">
              {d.plan.map((c) => <li key={c.code}><span aria-hidden className={c.good === true ? "text-emerald-700" : c.good === false ? "text-rose-700" : "text-slate-400"}>{c.good === true ? "✓" : c.good === false ? "✗" : "•"}</span>{" "}
                <span className="sr-only">{c.good === true ? "Followed the plan: " : c.good === false ? "Off plan: " : ""}</span>{c.text}</li>)}
            </ul>
          )}
          {d.kind === "sell" && d.buys && d.buys.some((b) => b.entry) && (
            <div className="rounded bg-slate-50 p-2 text-xs dark:bg-slate-800/60">
              <b>When you bought:</b>{d.buys.filter((b) => b.entry).map((b) => (
                <p key={b.key}>{b.date}: {(b.entry!.reasons || []).join(", ") || "no reason"}{b.entry!.target != null && ` · target ${num(b.entry!.target)}`}
                  {b.entry!.stop != null && ` · stop ${num(b.entry!.stop)}`}{b.entry!.confidence != null && ` · confidence ${b.entry!.confidence}/5`}{b.entry!.notes && ` · “${b.entry!.notes}”`}</p>
              ))}
            </div>
          )}
          {d.kind === "buy" ? (
            <div className="space-y-3">
              <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Why did you buy?</div>
                <Chips all={[...tags.reasons, ...(f.reasons ?? []).filter((x) => !tags.reasons.includes(x))]} value={f.reasons ?? []} onChange={(v) => setF({ ...f, reasons: v })} /></div>
              <div className="flex flex-wrap gap-3">
                {numIn("target", `Target (${unit(d)})`, "e.g. " + num(d.price * 1.3))}
                {numIn("stop", `Stop (${unit(d)})`, "e.g. " + num(d.price * 0.9))}
                {numIn("horizon_days", "Time frame (days)", "e.g. 90")}
                <label className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">Confidence
                  <select className={input} value={f.confidence ?? ""} onChange={(e) => setF({ ...f, confidence: e.target.value ? Number(e.target.value) : null })}>
                    <option value="">—</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} of 5</option>)}</select></label>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Why did you sell?</div>
                <Chips all={tags.sell_reasons} value={f.sell_reason ? [f.sell_reason] : []} onChange={(v) => setF({ ...f, sell_reason: v.filter((x) => x !== f.sell_reason)[0] ?? null })} /></div>
              <label className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">Lesson (what would you do differently?)
                <input className={input} value={f.lesson ?? ""} onChange={(e) => setF({ ...f, lesson: e.target.value })} /></label>
            </div>
          )}
          <label className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">Notes
            <textarea rows={3} className={input} value={f.notes ?? ""} onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
          <div className="flex flex-wrap items-center gap-2">
            <button className={btnPrimary} disabled={busy} onClick={() => save(false)}>Save</button>
            {d.status !== "done" && <button className={btn} disabled={busy} onClick={() => save(true)}>Nothing to write (skip)</button>}
            {d.entry?.updated_at && <span className="text-xs text-slate-500">saved {d.entry.updated_at.slice(0, 16).replace("T", " ")}</span>}
          </div>
          {d.kind === "buy" && d.sales && d.sales.length > 0 && (
            <p className="text-xs text-slate-500">Sold later: {d.sales.map((s) => `${s.date} (${pct(s.gain_pct, 0)})`).join(", ")}.</p>
          )}
        </>
      )}
    </div>
  );
}

function AggTable({ title, rows }: { title: string; rows: Agg[] }) {
  return (
    <Section title={title}>
      <div className="overflow-x-auto">
        <table className="tbl num w-full text-sm">
          <thead><tr><th></th><th className="text-right">Sales</th><th className="text-right">Winners</th><th className="text-right">Avg gain</th><th className="text-right">Total</th><th className="text-right">Avg days</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.label}><td className={r.label.startsWith("(") ? "text-slate-500" : ""}>{r.label}</td><td className="text-right">{r.sales}</td>
              <td className="text-right">{pct(r.win_rate, 0, false)}</td><td className="text-right">{pct(r.avg_gain_pct, 1)}</td>
              <td className="text-right"><Usd v={r.total_gain_usd} /></td><td className="text-right">{num(r.avg_days, 0)}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </Section>
  );
}

function Works({ tags, onOpen, onTags }: { tags: View["tags"]; onOpen: (k: string) => void; onTags: () => void }) {
  const q = useApi<Stats>("/api/journal/stats");
  const [r, setR] = useState(tags.reasons.join(", "));
  const [s, setS] = useState(tags.sell_reasons.join(", "));
  const [msg, setMsg] = useState<string | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const saveTags = async () => {
    const split = (x: string) => x.split(",").map((y) => y.trim()).filter(Boolean);
    await apiFetch("/api/journal/tags", jsonInit("PUT", { reasons: split(r), sell_reasons: split(s) }));
    setMsg("Saved.");
    onTags();
  };
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Sales with notes" value={`${d.journaled_sales} of ${d.sales}`} sub="the more you write, the more these tables say" />
        <Stat label="Plan followed / broken" value={`${d.plan.followed} / ${d.plan.broke}`} sub={`${d.plan.sales_with_plan} sales had a plan (target, stop or time frame)`} />
        <Stat label="Sold well below the best" value={`${d.left_on_table.gave_back_15} of ${d.left_on_table.sales}`} sub="the price had been 15+ points higher while you held it" />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AggTable title="By reason for buying" rows={d.by_reason} />
        <AggTable title="By group" rows={d.by_group} />
        <AggTable title="By sector" rows={d.by_sector} />
        <AggTable title="Starred stocks vs the rest" rows={d.by_starred} />
        <AggTable title="By reason for selling" rows={d.by_sell_reason} />
        <AggTable title="By how long you held" rows={d.by_holding} />
        <AggTable title="By confidence when buying" rows={d.by_confidence} />
        <Section title="Biggest gains given back">
          {d.left_on_table.examples.length === 0 ? <p className="text-sm text-slate-500">None: needs daily prices (Data ▾ Price history).</p> : (
            <ul className="space-y-1 text-sm">{d.left_on_table.examples.map((x) => (
              <li key={x.key}><button className="underline" onClick={() => onOpen(x.key)}>{x.stock}</button> sold {x.date} at {pct(x.gain_pct, 0)}; it had been {pct(x.best_pct, 0)}</li>
            ))}</ul>
          )}
        </Section>
      </div>
      {d.lessons.length > 0 && (
        <Section title="Your lessons">
          <ul className="space-y-1 text-sm">{d.lessons.map((l) => <li key={l.key}><button className="text-slate-500 underline" onClick={() => onOpen(l.key)}>{l.date} {l.stock}</button>: {l.lesson}</li>)}</ul>
        </Section>
      )}
      <Section title="Your tags">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs">Reasons for buying (comma separated)<textarea rows={3} className={input} value={r} onChange={(e) => setR(e.target.value)} /></label>
          <label className="flex flex-col gap-1 text-xs">Reasons for selling<textarea rows={3} className={input} value={s} onChange={(e) => setS(e.target.value)} /></label>
        </div>
        <div className="mt-2 flex items-center gap-2"><button className={btn} onClick={saveTags}>Save tags</button>{msg && <span className="text-xs text-slate-500">{msg}</span>}</div>
      </Section>
    </div>
  );
}

const buyReasons = (r: Row) => (r.kind === "buy" ? r.entry?.reasons ?? [] : r.reasons ?? []);
const TRADE_GROUPS: GroupOpt<Row>[] = [
  { key: "sector", label: "sector", of: (r) => [r.sector ?? "No sector set"] },
  { key: "stock", label: "stock", of: (r) => [r.stock], order: "name" },
  { key: "starred", label: "starred or not", of: (r) => [r.starred ? "★ Starred" : "Not starred"] },
  { key: "kind", label: "buys / sales", of: (r) => [r.kind === "buy" ? "Buys" : "Sales"] },
  { key: "reason", label: "reason for buying", of: (r) => (buyReasons(r).length ? buyReasons(r) : ["(no reason written)"]) },
  { key: "sell", label: "reason for selling", of: (r) => (r.kind === "sell" ? [r.entry?.sell_reason ?? "(no reason written)"] : ["(buys)"]) },
  { key: "group", label: "sale group", of: (r) => (r.kind === "sell" ? [r.group ?? "Not grouped"] : ["(buys)"]) },
  { key: "currency", label: "currency", of: (r) => [r.currency] },
  { key: "broker", label: "broker", of: (r) => [r.broker || "(no broker)"] },
  { key: "year", label: "year", of: (r) => [r.date.slice(0, 4)], order: "desc" },
  { key: "notes", label: "notes written or not", of: (r) => [r.status === "done" ? "With notes" : r.status === "skipped" ? "Skipped" : "No notes yet"] },
];

function GroupSummary({ name, rows }: { name: string; rows: Row[] }) {
  const sales = rows.filter((r) => r.kind === "sell" && r.gain_usd != null);
  const gain = sales.reduce((a, r) => a + (r.gain_usd ?? 0), 0);
  const wins = sales.filter((r) => (r.gain_usd ?? 0) > 0).length;
  return (
    <span className="flex flex-wrap items-baseline gap-x-3"><b>{name}</b><span className="text-xs text-slate-500">{rows.length} trades
      {sales.length > 0 && <> · {sales.length} sales · {Math.round((wins / sales.length) * 100)}% winners · realised <Usd v={gain} /></>}</span></span>
  );
}

function JournalPage() {
  const params = useSearchParams();
  const q = useApi<View>("/api/journal");
  const [tab, setTab] = useState<"todo" | "all" | "ideas" | "works">(params.get("tab") === "ideas" ? "ideas" : "todo");
  const [open, setOpen] = useState<string | null>(null);
  const [stock, setStock] = useState<string | null>(params.get("stock"));
  const [busy, setBusy] = useState(false);
  const [openAll, setOpenAll] = useState<boolean | null>(null);
  const grouping = useGrouping("journal-trades");
  const d = q.data;
  useEffect(() => {  // from Sales/Positions: open the trade, or show that stock's trades
    if (!d) return;
    const id = params.get("trade");
    const key = params.get("key") ?? (id ? d.rows.find((r) => r.id === id)?.key : null);
    if (key) { setOpen(key); setTab("all"); }
    if (params.get("stock")) setTab("all");
  }, [d, params]);
  const byKey = useMemo(() => new Map((d?.rows ?? []).map((r) => [r.key, r])), [d]);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!d) return <Loading />;
  const inbox = d.inbox.map((k) => byKey.get(k)!).filter(Boolean);
  const rows = (stock ? d.rows.filter((r) => r.stock_key === stock) : d.rows).filter((r) => !grouping.starredOnly || r.starred);
  const gopt = TRADE_GROUPS.find((g) => g.key === grouping.group);
  const groups = gopt ? groupRows(rows, gopt) : null;
  const skip = async (body: { keys?: string[]; older?: boolean }) => {
    setBusy(true);
    try { q.setData(await apiFetch<View>("/api/journal/skip", jsonInit("POST", body))); } finally { setBusy(false); }
  };
  const cols: Column<Row>[] = [
    { key: "date", label: "Date", type: "date", get: (r) => r.date },
    { key: "kind", label: "", type: "enum", get: (r) => r.kind, render: (r) => kindTag(r.kind) },
    { key: "star", label: "★", type: "enum", get: (r) => (r.starred ? "★" : "☆"), title: "Your most interesting stocks",
      render: (r) => <Star starKey={r.stock_key} on={r.starred} label={r.stock} onChange={q.reload} /> },
    { key: "stock", label: "Stock", type: "text", get: (r) => r.stock },
    { key: "sector", label: "Sector", type: "enum", get: (r) => r.sector ?? "No sector set", defaultHidden: true },
    { key: "shares", label: "Shares", type: "number", align: "right", get: (r) => r.shares, render: (r) => qty(r.shares) },
    { key: "price", label: "Price", type: "number", align: "right", get: (r) => r.price, render: (r) => num(r.price) },
    { key: "gain", label: "Gain $", type: "number", align: "right", firstDir: "desc", get: (r) => r.gain_usd ?? null, render: (r) => r.kind === "sell" ? <Usd v={r.gain_usd} /> : "" },
    { key: "gpct", label: "Gain %", type: "number", align: "right", firstDir: "desc", get: (r) => r.gain_pct ?? null, render: (r) => r.kind === "sell" ? pct(r.gain_pct, 1) : "" },
    { key: "days", label: "Days", type: "number", align: "right", get: (r) => r.days ?? null, render: (r) => r.days ?? "" },
    { key: "best", label: "Best while held", type: "number", align: "right", get: (r) => r.excursion?.best_pct ?? null, render: (r) => r.excursion ? pct(r.excursion.best_pct, 0) : "",
      title: "Highest close between buying and selling, from your average buy price" },
    { key: "vsspx", label: "vs S&P 500", type: "number", align: "right", get: (r) => r.vs_spx_usd ?? null, render: (r) => r.vs_spx_usd != null ? <Usd v={r.vs_spx_usd} /> : "", defaultHidden: true },
    { key: "why", label: "Why", type: "text", get: (r) => (r.kind === "buy" ? r.entry?.reasons?.join(", ") : r.entry?.sell_reason) ?? "",
      render: (r) => <span className="text-xs">{(r.kind === "buy" ? r.entry?.reasons?.join(", ") : [r.entry?.sell_reason, ...(r.reasons?.length ? [`(bought: ${r.reasons.join(", ")})`] : [])].filter(Boolean).join(" ")) || ""}</span> },
    { key: "group", label: "Group", type: "enum", get: (r) => r.group ?? "", defaultHidden: true },
    { key: "status", label: "Notes", type: "enum", get: (r) => r.status === "done" ? "written" : r.status === "skipped" ? "skipped" : "not yet",
      render: (r) => <button className="text-xs underline" onClick={() => setOpen(r.key)}>{r.status === "done" ? "📝 open" : "📝 write"}</button> },
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Trade journal</h1>
        <div className="flex items-center gap-2">
          <div role="tablist" aria-label="Journal views" className="flex overflow-hidden rounded border border-slate-300 text-sm dark:border-slate-700">
            {([["todo", `To journal (${inbox.length})`], ["all", "All trades"], ["ideas", "Watch list & ideas"], ["works", "What works"]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`px-2.5 py-1 ${tab === k ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>{l}</button>
            ))}
          </div>
          <a className={btn} href="/api/journal/export.csv">Export CSV</a>
        </div>
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-300">One entry per trade: why you bought or sold, and your plan. The app adds what the prices say: the context
        on the day, the best and worst point while you held it, and whether you stuck to your plan. Over time, <b>What works</b> shows which kinds of trades pay off for you.</p>
      <div>
        <div className="min-w-0 space-y-4">
          {tab === "todo" && (
            <Section title={`New trades from the last ${d.inbox_days} days without notes`}>
              {inbox.length === 0 ? <p className="text-sm text-slate-500">All caught up. New trades from your next upload (or the Trades page) appear here.</p> : (
                <ul className="divide-y divide-slate-200 dark:divide-slate-800">{inbox.map((r) => (
                  <li key={r.key} className={`flex flex-wrap items-center gap-2 py-2 text-sm ${open === r.key ? "bg-slate-50 dark:bg-slate-800/50" : ""}`}>
                    {kindTag(r.kind)}<span className="num text-slate-500">{r.date}</span><b>{r.stock}</b>
                    <span className="num text-slate-500">{qty(r.shares)} @ {num(r.price)} {unit(r)}</span>
                    {r.kind === "sell" && <span className="num"><Usd v={r.gain_usd} /> ({pct(r.gain_pct, 0)})</span>}
                    <span className="ml-auto flex gap-2"><button className={btn} onClick={() => setOpen(r.key)}>Write</button>
                      <button className={btn} disabled={busy} onClick={() => skip({ keys: [r.key] })}>Skip</button></span>
                  </li>
                ))}</ul>
              )}
              {d.counts.todo_older > 0 && (
                <p className="mt-3 text-xs text-slate-500">{d.counts.todo_older} older trades have no notes; they&apos;re all on <b>All trades</b> (and already count in <b>What works</b>).
                  {" "}<button className="underline" disabled={busy} onClick={() => skip({ older: true })}>Mark them as skipped</button></p>
              )}
            </Section>
          )}
          {tab === "all" && (
            <Section title={stock ? `${rows[0]?.stock ?? stock}: ${rows.length} trades` : `${d.counts.trades} trades · ${d.counts.done} with notes`}
              right={stock ? <button className="text-sm underline" onClick={() => setStock(null)}>show all stocks</button> : undefined}>
              <GroupControls opts={TRADE_GROUPS} group={grouping.group} setGroup={(g) => { grouping.setGroup(g); setOpenAll(null); }}
                starredOnly={grouping.starredOnly} setStarredOnly={grouping.setStarredOnly}
                extra={groups && <span className="flex gap-2 text-xs"><button className="underline" onClick={() => setOpenAll(true)}>expand all</button>
                  <button className="underline" onClick={() => setOpenAll(false)}>collapse all</button></span>} />
              {grouping.starredOnly && rows.length === 0 && <p className="text-sm text-slate-500">No starred stocks yet: press ☆ next to a stock to star it.</p>}
              {!groups ? (
                <DataTable id="pt-journal" rows={rows} columns={cols} rowKey={(r) => r.key} initialSort={[{ key: "date", dir: "desc" }]} exportName="journal"
                  rowClassName={(r) => (r.key === open ? "bg-slate-50 dark:bg-slate-800/50" : "")} />
              ) : (
                <div className="space-y-2">
                  {groups.map((g, i) => (
                    <details key={`${grouping.group}:${g.name}:${openAll}`} open={openAll ?? i === 0} className="group rounded border border-slate-200 dark:border-slate-700">
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 [&::-webkit-details-marker]:hidden">
                        <span aria-hidden className="text-xs text-slate-500 transition-transform group-open:rotate-90">▶</span><GroupSummary name={g.name} rows={g.rows} /></summary>
                      <div className="px-3 pb-3">
                        <DataTable id="pt-journal-grouped" rows={g.rows} columns={cols} rowKey={(r) => r.key} initialSort={[{ key: "date", dir: "desc" }]} compact
                          rowClassName={(r) => (r.key === open ? "bg-slate-50 dark:bg-slate-800/50" : "")} />
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </Section>
          )}
          {tab === "ideas" && <Ideas onOpenTrade={(k) => setOpen(k)} />}
          {tab === "works" && <Works tags={d.tags} onOpen={(k) => setOpen(k)} onTags={q.reload} />}
          {d.counts.trades > 0 && (tab === "todo" || tab === "all") && d.rows.every((r) => !r.excursion && !r.since) && (
            <Note tone="slate">No daily prices yet, so the best/worst points and plan checks are empty: add them on <Link className="underline" href="/history">Data ▾ Price history</Link>.</Note>
          )}
        </div>
        {open && (  // a panel that slides over the right of the page, so the table keeps its width
          <div className="fixed inset-0 z-40 bg-black/20" onClick={() => setOpen(null)}>
            <div className="absolute inset-y-0 right-0 w-[34rem] max-w-full overflow-y-auto bg-[var(--viz-surface)] p-3 shadow-xl" onClick={(e) => e.stopPropagation()}>
              <Editor k={open} tags={d.tags} onClose={() => setOpen(null)} onSaved={q.reload} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Loading />}><JournalPage /></Suspense>;
}
