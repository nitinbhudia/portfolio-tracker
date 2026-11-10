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
  const [busy, setBusy] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [edit, setEdit] = useState<Record<string, { source: string; symbol: string }>>({});
  const note = (id: string, ok: boolean, text: string) => setMsgs((m) => ({ ...m, [id]: { ok, text } }));
  const fail = (e: unknown) => (e instanceof ApiError ? e.message : String(e));
  const fetchAll = async () => {  // one index at a time: a slow site can't hold up the others
    for (const s of status) {
      setBusy(s.id);
      try {
        const r = await apiFetch<RefreshResp>(`/api/benchmarks/${s.id}/refresh`, { method: "POST" });
        const x = r.results[0];
        note(s.id, x.ok, x.ok ? `${x.points} days, up to ${x.last}` : x.message ?? "failed");
      } catch (e) {
        note(s.id, false, fail(e));
      }
    }
    setBusy(null);
    onChanged();
  };
  const uploadFile = async (id: string, f: File | undefined) => {
    if (!f) return;
    setBusy(id);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await apiFetch<RefreshResp>(`/api/benchmarks/${id}/upload`, { method: "POST", body: fd });
      note(id, true, `${r.results[0].points} days from ${f.name}`);
      onChanged();
    } catch (e) {
      note(id, false, fail(e));
    } finally {
      setBusy(null);
    }
  };
  const saveSource = async (id: string) => {
    try {
      await apiFetch(`/api/benchmarks/${id}`, jsonInit("PUT", edit[id]));
      setEdit((x) => { const n = { ...x }; delete n[id]; return n; });
      onChanged();
    } catch (e) {
      note(id, false, fail(e));
    }
  };
  const none = status.every((s) => s.points === 0);
  return (
    <Section title="Index data" right={<button className={btnPrimary} disabled={busy !== null} onClick={fetchAll}>
      {busy ? `Fetching ${status.find((s) => s.id === busy)?.name ?? ""}…` : none ? "Get index data" : "Update all"}</button>}>
      {none && <p className="mb-2 text-sm">No index history yet. &quot;Get index data&quot; downloads free daily closes: S&amp;P 500 and Nasdaq from FRED
        (Federal Reserve Bank of St. Louis), Russell 2000 and FTSE 100 from Stooq. If a download fails, upload a CSV for that index.</p>}
      <div className="overflow-x-auto">
        <table className="tbl w-full text-sm">
          <thead><tr><th>Index</th><th>Source</th><th className="text-right">Days</th><th>From</th><th>To</th><th>Upload CSV</th></tr></thead>
          <tbody>{status.map((s) => {
            const m = msgs[s.id];
            const e = edit[s.id] ?? { source: s.source, symbol: s.symbol };
            const dirty = e.source !== s.source || e.symbol !== s.symbol;
            return (
              <tr key={s.id}>
                <td><span className="mr-1.5 inline-block h-0.5 w-4 align-middle" style={{ background: COLORS[s.id] }} />{s.name} <span className="text-xs text-slate-500">{s.currency}</span>
                  {busy === s.id && <span className="ml-1 text-xs text-slate-500">working…</span>}
                  {m && <div role={m.ok ? "status" : "alert"} className={`max-w-sm whitespace-normal text-xs ${m.ok ? "text-emerald-700 dark:text-emerald-400" : "text-rose-600"}`}>{m.text}</div>}</td>
                <td><span className="flex items-center gap-1">
                  <select aria-label={`Source for ${s.name}`} className={input} value={e.source} onChange={(ev) => setEdit({ ...edit, [s.id]: { ...e, source: ev.target.value } })}>
                    <option value="fred">FRED</option><option value="stooq">Stooq</option></select>
                  <input aria-label={`Symbol for ${s.name}`} className={`${input} w-28`} value={e.symbol} onChange={(ev) => setEdit({ ...edit, [s.id]: { ...e, symbol: ev.target.value } })} />
                  {dirty && <button className={`${btn} text-xs`} onClick={() => saveSource(s.id)}>Save</button>}
                </span></td>
                <td className="num text-right">{s.points || "—"}</td><td className="num">{s.first ?? "—"}</td><td className="num">{s.last ?? "—"}</td>
                <td><input aria-label={`CSV for ${s.name}`} type="file" accept=".csv,text/csv" className="max-w-[12rem] text-xs" onChange={(ev) => uploadFile(s.id, ev.target.files?.[0])} /></td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">FRED series ids: SP500, NASDAQCOM, NASDAQ100. Stooq symbols: ^spx, ^ndq, ^ndx, ^rut, ^ukx.
        <b> CSV uploads</b> work with the daily-history downloads of most finance sites (Nasdaq.com, Investing.com, WSJ, Yahoo, FRED, Stooq…): a date
        column (2026-11-09, 11/09/2026, 09/11/2026, 09.11.2026, Nov 9, 2026…) and a Close, Close/Last or Price column. Day-first or month-first is worked
        out from the file; if it can&apos;t be told apart, the app says so instead of guessing.</p>
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
