"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorBox, Loading, Note, Section, Stat, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type PHPool, type PriceHistory, useApi } from "@/lib/api";

type Filter = "attention" | "open" | "all";

function needsAttention(p: PHPool): boolean {
  return p.warnings.length > 0 || p.fetch_status === "not_found" || p.fetch_status === "error" ||
    (p.open && p.source === "trades") || (p.ticker_allowed && !p.ticker);
}

function Row({ p, onDone, onError }: { p: PHPool; onDone: () => void; onError: (e: ApiError) => void }) {
  const [tk, setTk] = useState(p.ticker ?? "");
  const call = async (f: () => Promise<unknown>) => {
    try { await f(); onDone(); } catch (e) { onError(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0)); }
  };
  const saveTicker = () => { if (tk.trim().toUpperCase() !== (p.ticker ?? "")) call(() => apiFetch(`/api/price-history/ticker/${encodeURIComponent(p.group_key)}`, jsonInit("PUT", { ticker: tk.trim() || null }))); };
  const upload = (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    call(() => apiFetch(`/api/price-history/csv?pool=${encodeURIComponent(p.pool)}`, { method: "POST", body: fd }));
  };
  const src = p.source === "tiingo" ? "Tiingo" : p.source === "csv" ? "CSV" : "trade prices only";
  return (
    <tr className="align-top">
      <td>{p.stock}<div className="text-xs text-slate-500">{p.currency}{p.pence ? " (pence)" : ""} · {p.open ? "open" : `closed ${p.last_trade}`}</div></td>
      <td>{p.ticker_allowed
        ? <input aria-label={`Ticker for ${p.stock}`} className={`${input} w-24 uppercase`} value={tk} placeholder="ticker"
            onChange={(e) => setTk(e.target.value)} onBlur={saveTicker} onKeyDown={(e) => e.key === "Enter" && saveTicker()} />
        : <span className="text-xs text-slate-500">not on Tiingo: CSV</span>}</td>
      <td><span className={p.source === "trades" ? "text-amber-700 dark:text-amber-400" : ""}>{src}</span>
        {p.coverage && <div className="text-xs text-slate-500 num">{p.coverage.first} → {p.coverage.last} ({p.coverage.days} days)</div>}</td>
      <td className="max-w-md whitespace-normal text-xs">
        {p.fetch_status && p.fetch_status !== "ok" && <div className="text-rose-700 dark:text-rose-400">{p.fetch_message}</div>}
        {p.warnings.map((w, i) => <div key={i} className="text-amber-700 dark:text-amber-400">{w}</div>)}
      </td>
      <td className="whitespace-nowrap">
        <label className={`${btn} cursor-pointer text-xs`}>CSV…<input type="file" accept=".csv,text/csv" className="sr-only"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} /></label>
        {p.source === "csv" && <button className="ml-1 text-xs underline" onClick={() => call(() => apiFetch(`/api/price-history/csv?pool=${encodeURIComponent(p.pool)}`, { method: "DELETE" }))}>remove</button>}
      </td>
    </tr>
  );
}

export default function PriceHistoryPage() {
  const q = useApi<PriceHistory>("/api/price-history");
  const [err, setErr] = useState<ApiError | null>(null);
  const [filter, setFilter] = useState<Filter>("attention");
  const [text, setText] = useState("");
  const s = q.data;
  const live = !!(s && (s.running || s.waiting_until));
  useEffect(() => {
    if (!live) return;
    const t = setInterval(q.reload, 5000);
    return () => clearInterval(t);
  }, [live, q.reload]);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!s) return <Loading />;
  const act = async (path: string) => {
    setErr(null);
    try { await apiFetch(path, { method: "POST" }); q.reload(); } catch (e) { setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0)); }
  };
  const rows = s.pools.filter((p) => (filter === "all" || (filter === "open" ? p.open : needsAttention(p))) &&
    (!text || p.stock.toLowerCase().includes(text.toLowerCase()) || (p.ticker ?? "").toLowerCase().includes(text.toLowerCase())));
  const waiting = s.waiting_until ? new Date(s.waiting_until) : null;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Price history</h1>
      <Note tone="slate">Daily prices let <Link className="underline" href="/performance">Performance</Link> value your positions day by day. US stocks: set the
        ticker and download from Tiingo (free key). Other listings: upload a CSV of daily prices per stock (e.g. Investing.com → the stock → Historical Data →
        Download), in the listing&apos;s own currency{" "}— pence for London. Without either, a stock is valued at its last trade price.</Note>
      <Section title="Tiingo download" right={s.key ? (
        <span className="flex gap-2">
          {live ? <button className={btn} onClick={() => act("/api/price-history/stop")}>Stop</button>
            : <button className={btnPrimary} disabled={!s.queue} onClick={() => act("/api/price-history/download")}>{s.last_run ? "Update" : "Download"}</button>}
        </span>) : null}>
        {!s.key ? <p className="text-sm">{s.setup}</p> : (
          <div className="space-y-1 text-sm">
            <p>{s.queue ? `${s.queue} ticker${s.queue === 1 ? "" : "s"} to download` : "Everything with a ticker is up to date."}
              {s.running && !waiting && " — downloading…"}
              {waiting && ` — Tiingo's hourly limit reached; continuing at ${waiting.toLocaleTimeString()} (keep the app running).`}</p>
            {s.message && !waiting && <p className="text-slate-600 dark:text-slate-300">{s.message}</p>}
            <p className="text-xs text-slate-500">Tiingo&apos;s free plan allows about 50 requests an hour, so a first download of a few hundred tickers takes several hours;
              it runs in the background and resumes where it stopped. Updates later only fetch open positions.</p>
          </div>
        )}
      </Section>
      <ErrorBox error={err} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Stocks with daily prices" value={`${s.counts.tiingo + s.counts.csv} / ${s.counts.pools}`} sub={`${s.counts.tiingo} Tiingo · ${s.counts.csv} CSV`} />
        <Stat label="Open, trade prices only" value={String(s.counts.open_trades_only)} sub={`of ${s.counts.open} open`} />
        <Stat label="US stocks without a ticker" value={String(s.counts.no_ticker_usd)} />
        <Stat label="With warnings" value={String(s.counts.warnings)} sub="split or ticker mismatch" />
      </div>
      <Section title="Stocks" right={
        <span className="flex flex-wrap items-center gap-2">
          <input aria-label="Search stocks" className={`${input} w-36`} placeholder="search" value={text} onChange={(e) => setText(e.target.value)} />
          <span role="group" className="inline-flex overflow-hidden rounded border border-slate-300 text-xs dark:border-slate-700">
            {([["attention", "Needs attention"], ["open", "Open"], ["all", "All"]] as const).map(([k, l]) => (
              <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}
                className={`px-2.5 py-1 ${filter === k ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>{l}</button>))}
          </span></span>}>
        <div className="max-h-[36rem] overflow-auto">
          <table className="tbl w-full text-sm">
            <thead className="sticky top-0 bg-white dark:bg-slate-900"><tr><th>Stock</th><th>Ticker</th><th>Prices from</th><th>Notes</th><th>Upload</th></tr></thead>
            <tbody>{rows.length === 0 ? <tr><td colSpan={5} className="text-slate-500">Nothing here.</td></tr>
              : rows.map((p) => <Row key={`${p.pool}|${p.ticker ?? ""}|${p.source}`} p={p} onDone={q.reload} onError={setErr} />)}</tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
