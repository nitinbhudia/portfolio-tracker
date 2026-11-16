"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Section } from "@/components/research/ui";
import { ApiError, apiFetch } from "@/lib/research/api";

type Hit = { ticker: string; name: string | null; exchange: string; source: string; asset_type?: string };
type SearchResp = { local: Hit[]; remote: Hit[] | null };
type Options = { exchanges: Record<string, string>; us_configured: boolean; eu_configured: boolean };

const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const field = "rounded border border-slate-300 bg-transparent px-2 py-1 text-sm dark:border-slate-700";

/** Add any stock to Research by ticker or name: downloads its history, calculates and stores its analysis (Fibonacci,
 * scores) and, optionally, puts it on the watchlist. `onAdded` runs afterwards (the scanner re-scans). */
export function AddStock({ onAdded }: { onAdded: (ticker: string) => Promise<void> | void }) {
  const [q, setQ] = useState("");
  const [exchange, setExchange] = useState("US");
  const [opts, setOpts] = useState<Options | null>(null);
  const [res, setRes] = useState<SearchResp | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: React.ReactNode } | null>(null);

  useEffect(() => { apiFetch<Options>("/api/track/options").then(setOpts).catch(() => {}); }, []);
  useEffect(() => {  // free suggestions as you type: your holdings and stocks already in Research
    const text = q.trim();
    if (!text) { setRes(null); return; }
    const t = setTimeout(() => apiFetch<SearchResp>(`/api/search?q=${encodeURIComponent(text)}`).then(setRes).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);

  const searchTiingo = async () => {
    setMsg(null);
    setBusy("search");
    try { setRes(await apiFetch<SearchResp>(`/api/search?q=${encodeURIComponent(q.trim())}&remote=true`)); }
    catch (e) { setMsg({ ok: false, text: e instanceof ApiError ? e.message : String(e) }); }
    finally { setBusy(null); }
  };
  const add = async (ticker: string, ex: string, watch: boolean) => {
    setMsg(null);
    setBusy(ticker + (watch ? "+w" : ""));
    try {
      const r = await apiFetch<{ listing_id: number; ticker: string; analysis_status: string }>("/api/track", json({ ticker, exchange: ex, watch }));
      await onAdded(r.ticker);
      setMsg({ ok: true, text: <>Added <Link className="underline" href={`/research/analysis/${r.listing_id}`}>{r.ticker}</Link>
        {watch ? " to the watchlist" : ""}{r.analysis_status === "ok" ? " and calculated its Fibonacci levels and scores." : " (not enough price history for an analysis yet)."}</> });
      setQ("");
      setRes(null);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  const typed = q.trim().toUpperCase();
  const looksLikeTicker = /^[A-Z0-9.\-]{1,6}$/.test(typed);  // longer entries are names: use "Search by name"
  const needKey = opts && (exchange === "US" ? !opts.us_configured : !opts.eu_configured);
  const hits = [...(res?.local ?? []), ...(res?.remote ?? [])];
  const row = (h: Hit, ex: string) => (
    <li key={`${h.source}:${h.ticker}`} className="flex flex-wrap items-center justify-between gap-2 py-1">
      <span><b>{h.ticker}</b> <span className="text-slate-600 dark:text-slate-300">{h.name}</span>
        <span className="ml-1 text-xs text-slate-500">· {h.source}{h.asset_type && h.asset_type !== "Stock" ? ` · ${h.asset_type}` : ""}</span></span>
      <span className="flex gap-1">
        <button className="rounded border border-slate-300 px-2 py-0.5 text-xs dark:border-slate-700" disabled={!!busy} onClick={() => add(h.ticker, ex, false)}>
          {busy === h.ticker ? "Adding…" : "Add"}</button>
        <button className="rounded border border-slate-300 px-2 py-0.5 text-xs dark:border-slate-700" disabled={!!busy} onClick={() => add(h.ticker, ex, true)}>
          {busy === h.ticker + "+w" ? "Adding…" : "☆ Add & watch"}</button>
      </span>
    </li>
  );
  return (
    <Section title="Add a stock">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-xs">Ticker or company name
          <input aria-label="Ticker or company name" className={`${field} w-64`} placeholder="e.g. PLTR or Palantir" value={q}
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q.trim().length >= 2 && searchTiingo()} /></label>
        <label className="flex flex-col text-xs">Exchange
          <select aria-label="Exchange" className={field} value={exchange} onChange={(e) => setExchange(e.target.value)}>
            {Object.entries(opts?.exchanges ?? { US: "US (Tiingo)" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        {exchange === "US" && <button className="rounded border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700" disabled={q.trim().length < 2 || !!busy}
          onClick={searchTiingo}>{busy === "search" ? "Searching…" : "Search by name"}</button>}
      </div>
      {needKey && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{exchange === "US" ? "US prices need a Tiingo key (TIINGO_API_KEY in .env)."
        : "European prices need an EODHD key (EODHD_API_KEY in .env)."}</p>}
      {typed && (
        <ul className="mt-2 divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {looksLikeTicker && !hits.some((h) => h.ticker === typed) && row({ ticker: typed, name: "as typed", exchange, source: exchange === "US" ? "ticker" : opts?.exchanges[exchange] ?? exchange }, exchange)}
          {hits.map((h) => row(h, h.exchange === "US" ? "US" : h.exchange))}
          {res?.remote && res.remote.length === 0 && <li className="py-1 text-xs text-slate-500">Tiingo found nothing else for “{q.trim()}”.</li>}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate-500">Adding downloads the stock&apos;s daily price history, calculates its Fibonacci levels, moving averages, RSI,
        MACD and scores, and keeps it updated; the scanner then includes it. Searching by name uses one Tiingo request.</p>
      {msg && <p className={`mt-2 text-sm ${msg.ok ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>{msg.text}</p>}
    </Section>
  );
}
