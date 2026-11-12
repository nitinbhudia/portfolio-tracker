"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Columns, Lines, Navigator, Tooltip, type Tip } from "@/components/charts";
import { RangePicker, useRange } from "@/components/RangePicker";
import { ErrorBox, Loading, Note, Section, Stat, Usd, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type OddTrade, type Performance, type PriceHistory, type WIOverview, useApi } from "@/lib/api";
import { num, pct, qty, usd } from "@/lib/format";
import { inRange, resolve } from "@/lib/range";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const SLOTS = 8; // categorical palette size: the 8th is "Other"

function Allocation({ o }: { o: WIOverview }) {
  const [by, setBy] = useState<"stock" | "sector">("stock");
  const [tip, setTip] = useState<Tip>(null);
  const items = (by === "stock"
    ? o.holdings.filter((h) => h.value_usd !== null).map((h) => ({ key: h.pool, label: h.stock, value: h.value_usd as number }))
    : o.sectors.map((s) => ({ key: s.sector, label: s.sector, value: s.value_usd }))).sort((a, b) => b.value - a.value);
  const total = items.reduce((a, x) => a + x.value, 0);
  const top = items.length > SLOTS ? items.slice(0, SLOTS - 1) : items;
  const rest = items.length > SLOTS ? items.slice(SLOTS - 1) : [];
  const segs = [...top.map((x, i) => ({ ...x, color: `var(--viz-${i + 1})` })),
    ...(rest.length ? [{ key: "__other", label: `Other (${rest.length})`, value: rest.reduce((a, x) => a + x.value, 0), color: "var(--viz-muted)" }] : [])];
  const colorOf = (k: string) => segs.find((s) => s.key === k)?.color ?? "var(--viz-muted)";
  return (
    <Section title="Allocation" right={
      <span role="group" className="inline-flex overflow-hidden rounded border border-slate-300 text-xs dark:border-slate-700">
        {(["stock", "sector"] as const).map((k) => <button key={k} aria-pressed={by === k} onClick={() => setBy(k)}
          className={`px-2.5 py-1 ${by === k ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>by {k}</button>)}
      </span>}>
      <p className="mb-2 text-xs text-slate-500">Market value of open positions today ({usd(total)}).</p>
      <div className="relative" onPointerLeave={() => setTip(null)}>
        <div className="flex h-9 w-full overflow-hidden rounded" role="img" aria-label={`Allocation: ${segs.map((s) => `${s.label} ${pct((s.value / total) * 100, 1, false)}`).join(", ")}`}>
          {segs.map((s) => {
            const w = (s.value / total) * 100;
            return <div key={s.key} style={{ width: `${w}%`, background: s.color, borderRight: "2px solid var(--viz-surface)" }}
              onPointerMove={(e) => { const box = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect(); setTip({ x: e.clientX - box.left, y: 0, lines: [[s.label, ""], ["Value", usd(s.value)], ["Share", pct(w, 1, false)]] }); }} />;
          })}
        </div>
        <Tooltip tip={tip} />
      </div>
      <ul className="mt-3 max-h-72 space-y-1 overflow-auto pr-1 text-sm">
        {items.map((x, i) => (
          <li key={x.key} className="grid grid-cols-[minmax(6rem,11rem)_1fr_3.5rem] items-center gap-2">
            <span className="flex items-center gap-1.5 truncate">
              <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: i < top.length ? colorOf(x.key) : "var(--viz-muted)" }} />
              <span className="truncate">{x.label}</span></span>
            <span className="h-2 rounded-r" style={{ width: `${(x.value / items[0].value) * 100}%`, background: "var(--viz-axis)" }} />
            <span className="num text-right">{pct((x.value / total) * 100, 1, false)}</span>
          </li>
        ))}
      </ul>
      {by === "sector" && o.sectors.length <= 1 && <p className="mt-2 text-xs text-slate-500">Set sectors on <Link className="underline" href="/stocks">Data ▾ Names</Link>.</p>}
    </Section>
  );
}

export default function PerformancePage() {
  const q = useApi<Performance>("/api/performance");
  const ov = useApi<WIOverview>("/api/whatif");
  const { range, setRange } = useRange();
  const [closed, setClosed] = useState(false);
  const [unit, setUnit] = useState<"usd" | "pct">("usd");
  const d = q.data;
  const win = useMemo(() => (d ? resolve(range, d.as_of) : null), [d, range]);
  const idx = useMemo(() => (d && win ? d.dates.map((x, i) => (inRange(x, win) ? i : -1)).filter((i) => i >= 0) : []), [d, win]);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!d || !win) return <Loading />;
  const dates = idx.map((i) => d.dates[i]);
  const base = idx.length ? idx[0] : 0;
  // P/L within the range: change since the day before the range starts (all-time when the range starts at the beginning)
  const since = (a: number[]) => { const b0 = base > 0 ? a[base - 1] : 0; return idx.map((i) => a[i] - b0); };
  const total = since(d.total), open = since(d.open_pl), closedPl = since(d.realised);
  const last = idx[idx.length - 1] ?? d.dates.length - 1;
  const months = d.months.filter((m) => (!win.start || m.month >= win.start.slice(0, 7)) && m.month <= win.end.slice(0, 7));
  const estPct = d.estimated_now_pct ?? 0;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Performance</h1>
        <RangePicker />
      </div>
      {d.odd_trades.length > 0 && <OddTrades items={d.odd_trades} onDone={q.reload} />}
      {d.problems.length > 0 && <Note>{d.problems.join(" ")}</Note>}
      {estPct > 5 && (
        <Note>{pct(estPct, 0, false)} of today&apos;s value has no daily price history, so those positions are valued at their last trade price until the
          sheet&apos;s current price, and their gains or losses show up in jumps rather than day by day. Download prices on{" "}
          <Link className="underline" href="/history">Data ▾ Price history</Link>.</Note>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Total P/L in range" value={<Usd v={total[total.length - 1]} />} sub="closed + change in open" />
        <Stat label="Closed (realised)" value={<Usd v={closedPl[closedPl.length - 1]} />} />
        <Stat label="Open (unrealised) change" value={<Usd v={open[open.length - 1]} />} />
        <Stat label="Market value" value={usd(d.value[last])} sub={`cost ${usd(d.cost[last])} · ${dates[dates.length - 1] ?? ""}`} />
      </div>
      <Section title="Profit / loss over time">
        <p className="mb-2 text-xs text-slate-500">{base > 0 ? `Change since ${d.dates[base - 1]}.` : "Since your first trade."} Click a legend item to hide or show its line.</p>
        <Lines hideable label="Total, open and closed profit/loss over time" fmt={(v) => usd(v)} dates={dates} height={300}
          series={[{ name: "Total", color: "var(--viz-1)", values: total }, { name: "Open positions", color: "var(--viz-2)", values: open },
            { name: "Closed positions", color: "var(--viz-3)", values: closedPl }]} />
        <Navigator dates={d.dates} values={d.total} start={win.start} end={win.end}
          onChange={(a, b) => setRange({ key: "CUSTOM", from: a, to: b })} />
      </Section>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Market value and cost" right={<label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} />include closed positions</label>}>
          <p className="mb-2 text-xs text-slate-500">{closed ? "Open value plus everything sold (proceeds), against the cost of everything bought." : "Open positions only: value at each day's price, and their FIFO cost."}</p>
          <Lines hideable label="Market value and cost over time" fmt={(v) => usd(v)} dates={dates}
            series={[{ name: "Market value", color: "var(--viz-1)", values: idx.map((i) => d.value[i] + (closed ? d.sold_proceeds[i] : 0)) },
              { name: "Cost", color: "var(--viz-2)", values: idx.map((i) => d.cost[i] + (closed ? d.sold_cost[i] : 0)) }]} />
        </Section>
        {ov.data ? <Allocation o={ov.data} /> : ov.error ? <ErrorBox error={ov.error} onRetry={ov.reload} /> : <Loading />}
      </div>
      <Section title="Monthly P/L" right={
        <span role="group" className="inline-flex overflow-hidden rounded border border-slate-300 text-xs dark:border-slate-700">
          {(["usd", "pct"] as const).map((k) => <button key={k} aria-pressed={unit === k} onClick={() => setUnit(k)}
            className={`px-2.5 py-1 ${unit === k ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>{k === "usd" ? "USD" : "%"}</button>)}
        </span>}>
        <p className="mb-2 text-xs text-slate-500">Change in total P/L each month (realised gains plus the change in open positions){unit === "pct" ? ", as % of the market value at the start of the month" : ""}. Click a month for its split.</p>
        <MonthBars months={months} unit={unit} />
      </Section>
      <p className="text-xs text-slate-500">{d.note}</p>

    </div>
  );
}

function MonthBars({ months, unit }: { months: Performance["months"]; unit: "usd" | "pct" }) {
  const [sel, setSel] = useState<string | null>(null);
  const m = months.find((x) => x.month === sel);
  const name = (k: string) => `${MONTHS[+k.slice(5, 7) - 1]} ${k.slice(2, 4)}`;
  return (
    <>
      <Columns label={unit === "usd" ? "Monthly P/L in USD" : "Monthly P/L in %"} fmt={(v) => (unit === "usd" ? usd(v) : pct(v))} onPick={setSel}
        data={months.map((x) => ({ key: x.month, label: name(x.month), value: unit === "usd" ? x.change_usd : x.change_pct ?? 0,
          lines: [["Total", usd(x.change_usd)], ["%", x.change_pct === null ? "—" : pct(x.change_pct)], ["Closed (realised)", usd(x.closed_usd)], ["Open (change)", usd(x.open_usd)]] }))} />
      {m && (
        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <b>{name(m.month)}</b>
          <span>Total <Usd v={m.change_usd} /> {m.change_pct !== null && `(${pct(m.change_pct)})`}</span>
          <span>Closed <Usd v={m.closed_usd} /></span><span>Open <Usd v={m.open_usd} /></span>
          <span>Value at month end {usd(m.value_end_usd)}</span>
          <button className="underline" onClick={() => setSel(null)}>close</button>
        </div>
      )}
    </>
  );
}

/** Trades priced far from the same stock's other trades that month: usually another stock written with the same name.
 * Rename them (e.g. "Lumentum" -> "Lumen Tech") or mark them as correct. */
function OddTrades({ items, onDone }: { items: OddTrade[]; onDone: () => void }) {
  const names = useApi<PriceHistory>("/api/price-history");
  const groups = Object.values(items.reduce<Record<string, OddTrade[]>>((a, x) => ({ ...a, [x.pool]: [...(a[x.pool] ?? []), x] }), {}));
  return (
    <Note>
      <b>Check {items.length === 1 ? "this trade" : `these ${items.length} trades`}</b>: each is priced far from the same stock&apos;s other trades
      that month, so it is probably a different stock with a similar name. Until it&apos;s fixed it distorts the charts (e.g. a spike).
      <datalist id="stock-names">{[...new Set((names.data?.pools ?? []).map((p) => p.stock))].sort().map((n) => <option key={n} value={n} />)}</datalist>
      <div className="mt-2 space-y-3">{groups.map((g) => <OddGroup key={g[0].pool} g={g} onDone={onDone} />)}</div>
    </Note>
  );
}

function OddGroup({ g, onDone }: { g: OddTrade[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const run = async (f: () => Promise<unknown>) => {
    setErr(null);
    try { await f(); onDone(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  };
  return (
    <div className="rounded border border-amber-300 bg-white/60 p-2 text-slate-800 dark:border-amber-700 dark:bg-slate-900/40 dark:text-slate-100">
      <p className="text-sm"><b>{g[0].stock}</b> usually traded around {num(g[0].typical)} {g[0].currency} at the time, but:</p>
      <ul className="mt-1 list-disc pl-5 text-sm">{g.map((x) => (
        <li key={x.id} className="num">{x.kind === "buy" ? "Bought" : "Sold"} {qty(x.shares)} at {num(x.price, 4)} on {x.date} (sheet row {x.row})</li>))}</ul>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-1.5">Rename {g.length === 1 ? "it" : "them"} to
          <input aria-label={`Correct stock name for the ${g[0].stock} rows`} list="stock-names" className={`${input} w-44`} placeholder="e.g. Lumen Tech"
            value={name} onChange={(e) => setName(e.target.value)} /></label>
        <button className={btnPrimary} disabled={!name.trim() || g.some((x) => x.id.startsWith("M"))}
          onClick={() => run(() => apiFetch("/api/trades/rename", jsonInit("POST", { ids: g.map((x) => x.id), name: name.trim() })))}>Rename</button>
        <button className={btn} onClick={() => run(() => apiFetch("/api/performance/odd-trades/ignore", jsonInit("POST", { items: g })))}>They&apos;re correct</button>
      </div>
      {g.some((x) => x.id.startsWith("M")) && <p className="mt-1 text-xs">Trades you entered in the app: edit them on Data ▾ Trades.</p>}
      {err && <p className="mt-1 text-sm text-rose-700 dark:text-rose-400">{err}</p>}
    </div>
  );
}
