"use client";

import { useMemo, useState } from "react";

import { Lines } from "@/components/charts";
import { RangePicker, useRange } from "@/components/RangePicker";
import { ErrorBox, Loading, Note, Pct, Section, Usd, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, type BenchmarksResp, jsonInit, type RefreshResp, useApi } from "@/lib/api";
import { pct, usd } from "@/lib/format";
import { label } from "@/lib/range";

const COLORS: Record<string, string> = { spx: "var(--viz-1)", ndq: "var(--viz-2)", ndx: "var(--viz-3)", rut: "var(--viz-4)", ukx: "var(--viz-5)" };

function DataPanel({ status, onChanged }: { status: BenchmarksResp["status"]; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<RefreshResp["results"]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [sym, setSym] = useState<Record<string, string>>({});
  const run = async (fn: () => Promise<RefreshResp | { indexes: unknown }>) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      if ("results" in r) setMsgs(r.results as RefreshResp["results"]);
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const uploadFile = (id: string, f: File | undefined) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    run(() => apiFetch<RefreshResp>(`/api/benchmarks/${id}/upload`, { method: "POST", body: fd }));
  };
  const none = status.every((s) => s.points === 0);
  return (
    <Section title="Index data" right={<button className={btnPrimary} disabled={busy} onClick={() => run(() => apiFetch<RefreshResp>("/api/benchmarks/refresh", { method: "POST" }))}>
      {busy ? "Fetching…" : none ? "Get index data" : "Update all"}</button>}>
      {none && <p className="mb-2 text-sm">No index history yet. &quot;Get index data&quot; downloads daily closes from Stooq (free, no key). If that doesn&apos;t work,
        upload a CSV per index (columns Date as YYYY-MM-DD and Close), for example Stooq&apos;s own download in your browser:
        stooq.com/q/d/l/?s=^spx&amp;i=d.</p>}
      <div className="overflow-x-auto">
        <table className="tbl w-full text-sm">
          <thead><tr><th>Index</th><th>Stooq symbol</th><th className="text-right">Days</th><th>From</th><th>To</th><th>Upload CSV</th></tr></thead>
          <tbody>{status.map((s) => {
            const m = msgs.find((x) => x.id === s.id);
            return (
              <tr key={s.id}>
                <td><span className="mr-1.5 inline-block h-0.5 w-4 align-middle" style={{ background: COLORS[s.id] }} />{s.name} <span className="text-xs text-slate-500">{s.currency}</span>
                  {m && !m.ok && <div role="alert" className="max-w-xs whitespace-normal text-xs text-rose-600">{m.message}</div>}</td>
                <td><span className="flex items-center gap-1">
                  <input aria-label={`Stooq symbol for ${s.name}`} className={`${input} w-24`} value={sym[s.id] ?? s.symbol} onChange={(e) => setSym({ ...sym, [s.id]: e.target.value })} />
                  {(sym[s.id] ?? s.symbol) !== s.symbol && <button className={`${btn} text-xs`} onClick={() => run(() => apiFetch(`/api/benchmarks/${s.id}`, jsonInit("PUT", { symbol: sym[s.id] })))}>Save</button>}
                </span></td>
                <td className="num text-right">{s.points || "—"}</td><td className="num">{s.first ?? "—"}</td><td className="num">{s.last ?? "—"}</td>
                <td><input aria-label={`CSV for ${s.name}`} type="file" accept=".csv,text/csv" className="max-w-[12rem] text-xs" onChange={(e) => uploadFile(s.id, e.target.files?.[0])} /></td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      {err && <div role="alert" className="mt-1 text-xs text-rose-600">{err}</div>}
    </Section>
  );
}

export default function IndexesPage() {
  const { range } = useRange();
  const params: Record<string, string> = range.key === "CUSTOM"
    ? { ...(range.from ? { start: range.from } : {}), ...(range.to ? { end: range.to } : {}) }
    : { range: range.key };
  const q = useApi<BenchmarksResp>(`/api/benchmarks?${new URLSearchParams(params).toString()}`);
  const [pick, setPick] = useState("spx");
  const d = q.data;
  const avail = useMemo(() => d?.indexes.filter((x) => x.available) ?? [], [d]);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!d) return <Loading />;
  const chosen = avail.find((x) => x.id === pick) ?? avail[0];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Your trades vs the indexes</h1>
        <RangePicker />
      </div>
      <p className="text-xs text-slate-500">Period: {d.period.start} → {d.period.end} ({label(range)}){d.review_pending ? ` · ${d.review_pending} review items not included` : ""}</p>
      {avail.length > 0 && (
        <>
          <Section title="Did your trades beat the index? (same dollars, same holding periods)">
            <div className="overflow-x-auto">
              <table className="tbl num w-full text-sm">
                <thead><tr><th>Index</th><th className="text-right">Index change (USD)</th><th className="text-right">Your realised gain</th><th className="text-right">Same $ in the index</th>
                  <th className="text-right">Difference</th><th className="text-right">Sales that beat it</th>{d.indexes.some((x) => x.compare?.open) && <><th className="text-right">Open: your unrealised</th><th className="text-right">Open: same $ in index</th></>}</tr></thead>
                <tbody>{avail.map((x) => {
                  const c = x.compare!;
                  const diff = c.realised.gain_usd - c.realised.index_gain_usd;
                  return (
                    <tr key={x.id}>
                      <td><span className="mr-1.5 inline-block h-0.5 w-4 align-middle" style={{ background: COLORS[x.id] }} />{x.name}</td>
                      <td className="text-right"><Pct v={x.change_usd_pct} />{x.currency !== "USD" && <div className="text-[10px] text-slate-500">{pct(x.change_pct)} in {x.currency}</div>}</td>
                      <td className="text-right"><Usd v={c.realised.gain_usd} /></td><td className="text-right"><Usd v={c.realised.index_gain_usd} /></td>
                      <td className="text-right font-semibold"><Usd v={diff} /></td>
                      <td className="text-right">{c.realised.compared ? `${c.realised.beat} of ${c.realised.compared}` : "—"}</td>
                      {c.open ? <><td className="text-right"><Usd v={d.open?.unrealised_usd} /></td><td className="text-right"><Usd v={c.open.index_gain_usd} /></td></> : d.indexes.some((y) => y.compare?.open) ? <><td /><td /></> : null}
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-slate-500">For every sale in the period, each FIFO purchase it used is replayed in the index from the purchase date to the sale date,
              with the same dollars. Positive difference = your picks did better than the index would have. Open positions are compared from their purchase dates to the
              latest price date (shown when the period runs to today).</p>
          </Section>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="Indexes over the period (USD, start = 100)">
              <Lines label="Index levels in USD, indexed to 100 at the start of the period" fmt={(v) => v.toFixed(1)} dates={d.index_chart.dates}
                series={avail.map((x) => ({ name: x.name, color: COLORS[x.id], values: d.index_chart.lines[x.id] ?? [] }))} />
            </Section>
            <Section title="Cumulative realised gain vs the same $ in an index" right={
              <select aria-label="Index to compare" className={input} value={chosen?.id} onChange={(e) => setPick(e.target.value)}>
                {avail.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select>}>
              {d.cumulative.dates.length === 0 ? <p className="text-sm text-slate-500">No sales in this period.</p> : (
                <Lines label="Your cumulative realised gain and the index-equivalent gain" fmt={(v) => usd(v)} dates={d.cumulative.dates}
                  series={[{ name: "Your trades", color: "var(--viz-1)", values: d.cumulative.yours },
                    { name: `Same $ in ${chosen?.name}`, color: "var(--viz-2)", values: d.cumulative.index[chosen?.id ?? ""] ?? [] }]} />
              )}
            </Section>
          </div>
          {d.period.all_time && (
            <Section title="All time: if every purchase had bought the index instead">
              <div className="overflow-x-auto">
                <table className="tbl num w-full text-sm">
                  <thead><tr><th>Index</th><th className="text-right">Your money-weighted return</th><th className="text-right">Index, same cash flows</th>
                    <th className="text-right">Your open positions today</th><th className="text-right">Index holding today</th></tr></thead>
                  <tbody>{avail.map((x) => x.same_money && (
                    <tr key={x.id}><td>{x.name}</td><td className="text-right"><Pct v={x.same_money.your_xirr_pct} /></td><td className="text-right">{x.same_money.ran_out ? "—" : <Pct v={x.same_money.index_xirr_pct} />}</td>
                      <td className="text-right">{usd(x.same_money.your_end_value_usd)}</td>
                      <td className="text-right">{x.same_money.ran_out
                        ? <span className="whitespace-normal text-xs text-slate-500">ran out on {x.same_money.ran_out}: the index fell so far that a sale took out more than it was worth</span>
                        : usd(x.same_money.index_end_value_usd)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-slate-500">Every purchase buys the index for the same dollars; every sale sells the same dollar amount of it. Both returns are per year
                (XIRR) on exactly the same cash flows. Only for the whole history, because the value of your holdings on a past date isn&apos;t known.</p>
            </Section>
          )}
        </>
      )}
      <DataPanel status={d.status} onChanged={q.reload} />
      <Note tone="slate">{d.note}</Note>
    </div>
  );
}
