"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type Position } from "@/lib/api";
import { num, pct } from "@/lib/format";

type Options = { exchanges: Record<string, string>; us_configured: boolean; eu_configured: boolean };
type TrackResp = {
  listing_id: number; ticker: string; exchange: string; watched: boolean; analysis_status: string;
  download: { status: string; bars_added: number; last_date: string | null };
  summary: null | { as_of: string; close: number; scores: Record<string, number | null>;
    nearest_fibonacci: null | { ratio: number; kind: string; price: number; distance_pct: number; distance_atr: number | null } };
};

const DEFAULT_EXCHANGE: Record<string, string> = { USD: "US", EUR: "XETR", GBP: "XLON", CHF: "XSWX" };
const memKey = (pool: string) => `research-track:${pool}`;

/** Remembered ticker/exchange for a non-US position (US tickers live in the app: Data ▾ Price history). */
export function remembered(p: Position): { ticker: string; exchange: string } {
  try {
    const v = JSON.parse(localStorage.getItem(memKey(p.pool)) || "null");
    if (v?.ticker) return v;
  } catch { /* ignore */ }
  return { ticker: p.ticker ?? "", exchange: DEFAULT_EXCHANGE[p.currency] ?? "US" };
}

/** Per-position actions on the Positions page: calculate the stock's Fibonacci levels and scores in Research (downloads
 * its price history and keeps it tracked), open it there, and put it on Research's watchlist. */
export function ResearchActions({ p, watched, onChange }: { p: Position; watched: boolean; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="ml-1.5 inline-flex items-center gap-1 align-middle">
      <button className="rounded border border-amber-400 px-1.5 text-xs text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950"
        title="Calculate Fibonacci levels and scores in Research" onClick={() => setOpen(true)}>φ</button>
      {watched && <span className="text-xs text-amber-500" title="On the Research watchlist" aria-label="On the watchlist">★</span>}
      {open && <TrackDialog p={p} onClose={() => setOpen(false)} onChange={onChange} />}
    </span>
  );
}

function TrackDialog({ p, onClose, onChange }: { p: Position; onClose: () => void; onChange: () => void }) {
  const router = useRouter();
  const [opts, setOpts] = useState<Options | null>(null);
  const start = remembered(p);
  const [ticker, setTicker] = useState(start.ticker);
  const [exchange, setExchange] = useState(start.exchange);
  const [busy, setBusy] = useState<null | "open" | "watch">(null);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<TrackResp | null>(null);

  useEffect(() => {
    apiFetch<Options>("/research/api/track/options").then(setOpts).catch(() => setOpts(null));
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const needKey = opts && (exchange === "US" ? !opts.us_configured : !opts.eu_configured);
  const run = async (mode: "open" | "watch") => {
    setErr(null);
    setBusy(mode);
    const t = ticker.trim().toUpperCase();
    try {
      // remember the ticker: in the app for US stocks (also used for price history), on this computer otherwise
      if (exchange === "US" && p.currency === "USD" && t !== (p.ticker ?? "")) {
        await apiFetch(`/api/price-history/ticker/${encodeURIComponent(p.stock_key)}`, jsonInit("PUT", { ticker: t }));
      } else if (exchange !== "US") {
        try { localStorage.setItem(memKey(p.pool), JSON.stringify({ ticker: t, exchange })); } catch { /* ignore */ }
      }
      const r = await apiFetch<TrackResp>("/research/api/track", jsonInit("POST", { ticker: t, exchange, watch: mode === "watch" }));
      onChange();
      if (mode === "open") {
        router.push(`/research/analysis/${r.listing_id}`);
        return;
      }
      setRes(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const nf = res?.summary?.nearest_fibonacci;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-24" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={`Research: ${p.stock}`} onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md whitespace-normal rounded-lg border border-slate-200 bg-white p-4 text-left text-sm shadow-xl dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-2">
          <h2 className="font-semibold"><span className="text-amber-500">φ</span> {p.stock} in Research</h2>
          <button className="text-slate-500" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <p className="mt-1 text-xs text-slate-500">Downloads the stock&apos;s daily price history, calculates its Fibonacci levels, moving averages, RSI,
          MACD and scores, and saves them. Research keeps it up to date from then on.</p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs">Ticker
            <input autoFocus aria-label="Ticker" className={`${input} w-28 uppercase`} value={ticker} placeholder="e.g. PYPL"
              onChange={(e) => setTicker(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ticker.trim() && run("open")} /></label>
          <label className="flex flex-col text-xs">Exchange
            <select aria-label="Exchange" className={input} value={exchange} onChange={(e) => setExchange(e.target.value)}>
              {Object.entries(opts?.exchanges ?? { US: "US (Tiingo)" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
        </div>
        {needKey && (
          <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
            {exchange === "US" ? "US prices need a Tiingo key: add TIINGO_API_KEY=… to the app's .env file and restart the app."
              : "European prices need an EODHD key: add EODHD_API_KEY=… to the app's .env file and restart the app."}</p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <button className={btnPrimary} disabled={!ticker.trim() || !!busy} onClick={() => run("open")}>
            {busy === "open" ? "Calculating…" : "Calculate & open in Research"}</button>
          <button className={btn} disabled={!ticker.trim() || !!busy} onClick={() => run("watch")}>
            {busy === "watch" ? "Calculating…" : "☆ Calculate & add to watchlist"}</button>
        </div>
        {err && <p className="mt-2 text-xs text-rose-700 dark:text-rose-400">{err}</p>}
        {res && (
          <div className="mt-3 rounded border border-slate-200 p-2 text-xs dark:border-slate-700">
            <p><b>{res.ticker}</b> {res.watched && <span className="text-amber-600">★ on the watchlist</span>} · {res.download.bars_added > 0 ? `${res.download.bars_added} new days of prices` : "prices up to date"}</p>
            {res.summary ? (
              <ul className="mt-1 space-y-0.5 num">
                <li>Close {num(res.summary.close)} on {res.summary.as_of}</li>
                {nf && <li>Nearest Fibonacci level: {(nf.ratio * 100).toFixed(1)}% ({nf.kind}) at {num(nf.price)}, {pct(nf.distance_pct)} away
                  {nf.distance_atr !== null && ` (${nf.distance_atr.toFixed(1)} ATR)`}</li>}
                <li>Scores: {Object.entries(res.summary.scores).map(([h, v]) => `${h} ${v === null ? "—" : Math.round(v)}`).join(" · ")}</li>
              </ul>
            ) : <p className="mt-1">Not enough price history for an analysis yet ({res.analysis_status}).</p>}
            <Link className="mt-1 inline-block underline" href={`/research/analysis/${res.listing_id}`}>Open in Research →</Link>
          </div>
        )}
      </div>
    </div>
  );
}
