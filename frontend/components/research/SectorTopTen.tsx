"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Empty, ErrorBox, Section } from "@/components/research/ui";
import { WatchStar } from "@/components/research/WatchStar";
import { ApiError, apiFetch, type SectorDetail } from "@/lib/research/api";
import { fmtTimestamp, num, pct, signClass } from "@/lib/research/format";

const STALE_DAYS = 3;
const btnS = "rounded border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-50 dark:border-slate-700";

/** The ETF's ten biggest holdings, first thing on a sector page: downloaded automatically from the issuer's daily file,
 * with one-click analysis (Fibonacci, scores, strength vs the sector) and watchlist for each, or for all ten at once. */
export function SectorTopTen({ d, reload }: { d: SectorDetail; reload: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const tried = useRef<string | null>(null);
  const h = d.holdings;
  const real = d.data === "real";

  const post = async <T,>(label: string, path: string, body?: unknown): Promise<T | null> => {
    setBusy(label);
    setErr(null);
    setMsg(null);
    try {
      return await apiFetch<T>(path, body === undefined ? { method: "POST" }
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
      return null;
    } finally {
      setBusy(null);
    }
  };

  // Holdings missing or older than a few days: fetch the issuer's file once, quietly (free, no key needed).
  useEffect(() => {
    const age = h.fetched_at ? (Date.now() - new Date(h.fetched_at).getTime()) / 86_400_000 : Infinity;
    if (age < STALE_DAYS || tried.current === d.ticker) return;
    tried.current = d.ticker;
    post("Downloading the ETF's holdings…", `/api/sectors/holdings/refresh?ticker=${d.ticker}`).then((r) => { if (r) reload(); });
  }, [d.ticker, h.fetched_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const analyseAll = async () => {
    const r = await post<{ results: { ticker: string; status: string; message?: string }[] }>(
      "Downloading prices and analysing the top 10…", `/api/sectors/${d.ticker}/constituents/download`);
    if (r) {
      const failed = r.results.filter((x) => x.status === "failed");
      const waiting = r.results.filter((x) => x.status === "skipped_budget");
      setMsg(`${r.results.length - failed.length - waiting.length} analysed` + (waiting.length ? `, ${waiting.length} wait for the provider's hourly limit` : "")
        + (failed.length ? `, ${failed.length} failed (${failed[0].ticker}: ${failed[0].message})` : "") + ".");
      reload();
    }
  };
  const track = async (ticker: string, mic: string, watch: boolean) => {
    const r = await post<{ ticker: string }>(`${watch ? "Adding" : "Analysing"} ${ticker}…`, "/api/track", { ticker, exchange: mic, watch });
    if (r) { setMsg(`${r.ticker} ${watch ? "added to the watchlist and analysed" : "analysed"}.`); reload(); }
  };

  const missing = h.missing_prices.length;
  return (
    <Section title={`Top 10 stocks in ${d.sector}`} right={<span className="text-xs text-slate-500">{h.source}{h.as_of && <> · as of {h.as_of}</>}</span>}>
      <p className="mb-2 text-xs text-slate-600 dark:text-slate-300">The ten biggest holdings of {d.ticker} ({d.etf_name}) by weight: the stocks that move this
        sector most. Analyse them to see each one&apos;s Fibonacci levels, scores and whether it is stronger than the sector.</p>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        {real && missing > 0 && (
          <button disabled={!!busy} onClick={analyseAll}
            className="rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">φ Analyse all {missing}</button>
        )}
        <button disabled={!!busy} className={btnS} onClick={async () => { if (await post("Updating holdings…", `/api/sectors/holdings/refresh?ticker=${d.ticker}`)) reload(); }}>
          {h.count ? "Update holdings" : "Download holdings"}</button>
        {busy && <span className="text-xs text-amber-600" role="status">{busy}</span>}
        {msg && <span className="text-xs text-slate-600 dark:text-slate-300">{msg}</span>}
        {h.fetched_at && <span className="text-xs text-slate-500">holdings downloaded {fmtTimestamp(h.fetched_at)}</span>}
      </div>
      <ErrorBox error={err} />
      {h.count === 0 ? <Empty>{busy ? "Downloading…" : `No holdings yet. They come from the issuer's daily file for ${d.ticker}; press Download holdings.`}</Empty> : (
        <>
          <div className="overflow-x-auto">
            <table className="tbl num w-full text-xs">
              <thead><tr><th>#</th><th>Stock</th><th>Ticker</th>{d.region?.id === "eu" && <th>Exchange</th>}<th className="text-right">Weight</th>
                <th className="text-right">20D</th><th className="text-right" title="Above 100 = stronger than the sector">RS vs sector</th><th>Actions</th></tr></thead>
              <tbody>
                {h.top10.map((x) => {
                  const a = x.analysis;
                  const canTrack = real && !!x.ticker && !!x.mic;
                  return (
                    <tr key={x.rank}>
                      <td>{x.rank}</td>
                      <td>{x.name}{x.held_by_you && <span className="ml-1.5 rounded bg-emerald-100 px-1 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">you hold</span>}</td>
                      <td>{x.ticker ?? "—"}</td>
                      {d.region?.id === "eu" && <td>{x.exchange ?? "—"}</td>}
                      <td className="text-right">{num(x.weight_pct, 2)}%</td>
                      <td className="text-right"><span className={signClass(a?.change_20d_pct)}>{pct(a?.change_20d_pct, 1)}</span></td>
                      <td className="text-right">{a?.rs_ratio_vs_sector == null ? "—" : <span className={a.beats_sector ? "text-emerald-700 dark:text-emerald-400" : ""}>{num(a.rs_ratio_vs_sector, 1)}</span>}</td>
                      <td className="whitespace-nowrap">
                        {a ? (
                          <span className="inline-flex items-center gap-2">
                            <Link href={`/research/analysis/${a.listing_id}`} className="underline">φ analysis</Link>
                            <WatchStar listingId={a.listing_id} on={a.watchlisted} onChange={reload} />
                          </span>
                        ) : canTrack ? (
                          <span className="inline-flex gap-1">
                            <button className={btnS} disabled={!!busy} onClick={() => track(x.ticker!, x.mic!, false)}>φ Analyse</button>
                            <button className={btnS} disabled={!!busy} onClick={() => track(x.ticker!, x.mic!, true)}>☆ Watch</button>
                          </span>
                        ) : <span className="text-slate-400">{x.price_supported === false ? "exchange not supported yet" : real ? "no ticker" : "synthetic mode"}</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {h.unsupported_exchanges && h.unsupported_exchanges.length > 0 && (
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">Prices aren&apos;t available yet for holdings on: {h.unsupported_exchanges.join(", ")}.
              Supported: Xetra, London, Euronext Amsterdam and Paris, SIX (via EODHD).</p>
          )}
          <p className="mt-1 text-xs text-slate-500">Top 10 = {num(h.top10_weight_pct, 1)}% of the fund ({h.count} holdings). A big weight means the stock
            moves the sector, not that it&apos;s a good buy; use the analysis to look further.
            {!real && " Weights are real; switch Sector Rotation to real data (needs your Tiingo key) to analyse the stocks."}</p>
        </>
      )}
    </Section>
  );
}
