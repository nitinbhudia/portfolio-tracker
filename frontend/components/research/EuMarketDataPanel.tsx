"use client";

import Link from "next/link";
import { useState } from "react";

import { DataTable } from "@/components/research/DataTable";
import { ErrorBox, Loading, Section, Warn } from "@/components/research/ui";
import { ApiError, apiFetch, notifyAlerts, useApi } from "@/lib/research/api";
import { fmtTimestamp } from "@/lib/research/format";

type Tracked = { ticker: string; exchange: string; symbol: string; origin: string; listing_id: number | null; last_date: string | null; expected_session: string; suffix_unverified: boolean };
type EuStatus = {
  configured: boolean;
  exchanges: Record<string, string>;
  unverified_suffixes: string[];
  tracked: Tracked[];
  usage: { last_minute: number; last_day: number; minute_budget: number; daily_budget: number };
  last_refresh: { at: string; updated: number; failed: number } | null;
};
type FxStatus = {
  last_date: string | null;
  observations: number;
  latest: Record<string, { rate: number; date: string; source: string }>;
  note: string;
  last_refresh: { at: string } | null;
};
type Result = { ticker: string; exchange?: string; status: string; bars_added: number; last_date?: string | null; message?: string };

const EXCH: Record<string, string> = { XETR: "Xetra", XAMS: "Euronext Amsterdam", XPAR: "Euronext Paris", XSWX: "SIX Swiss", XLON: "London (LSE)" };
const ORIGIN: Record<string, string> = { sector: "sector ETF (Sector Rotation)", ibkr: "your IBKR holding", user: "added by you" };
const btn = "rounded border px-3 py-1.5 text-sm disabled:opacity-50";

export function EuMarketDataPanel({ onChanged }: { onChanged: () => void }) {
  const { data, error, loading, reload } = useApi<EuStatus>("/api/market-data/eu/status");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [results, setResults] = useState<Result[] | null>(null);
  const [sym, setSym] = useState("");
  const [mic, setMic] = useState("XETR");

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setErr(null);
    try {
      await fn();
      notifyAlerts();
      reload();
      onChanged();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(null);
    }
  };
  const refresh = () =>
    run("Downloading European prices from EODHD…", async () => {
      const r = await apiFetch<{ results: Result[] }>("/api/market-data/eu/refresh", { method: "POST" });
      setResults(r.results);
    });
  const add = () =>
    sym.trim() &&
    run(`Adding ${sym.toUpperCase()} (${EXCH[mic]})…`, async () => {
      const r = await apiFetch<Result>("/api/market-data/eu/symbols", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticker: sym, exchange: mic }),
      });
      setResults([r]);
      setSym("");
    });
  const remove = (t: Tracked) =>
    run(`Removing ${t.ticker}…`, async () => void (await apiFetch(`/api/market-data/eu/symbols/${t.exchange}/${encodeURIComponent(t.ticker)}`, { method: "DELETE" })));

  const upToDate = data.tracked.filter((t) => t.last_date && t.last_date >= t.expected_session).length;

  return (
    <Section title="Real European prices (EODHD, end-of-day)"
      right={<span className="text-xs text-slate-500">Requests today: {data.usage.last_day}/{data.usage.daily_budget}</span>}>
      <div className="space-y-3 text-sm">
        {!data.configured ? (
          <Warn>
            Add your EODHD key to <code>.env</code> as <code>EODHD_API_KEY=…</code> (plan &quot;EOD Historical&quot;, see
            {" "}<code>docs/data-provider-evaluation.md</code>), then restart the app. Until then, European holdings show &quot;needs price data&quot;.
          </Warn>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={refresh} disabled={!!busy}
              className={`${btn} border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900`}>
              Update European prices
            </button>
            <span className="text-xs text-slate-500">
              {upToDate}/{data.tracked.length} up to date{data.last_refresh && <> · last update {fmtTimestamp(data.last_refresh.at)}</>}
            </span>
            <span className="ml-auto flex flex-wrap items-center gap-1">
              <input value={sym} onChange={(e) => setSym(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()}
                placeholder="Ticker, e.g. SAP" aria-label="Add European ticker"
                className="w-32 rounded border border-slate-300 bg-transparent px-2 py-1 text-sm dark:border-slate-700" />
              <select aria-label="Exchange" value={mic} onChange={(e) => setMic(e.target.value)}
                className="rounded border border-slate-300 bg-transparent px-1 py-1 text-sm dark:border-slate-700">
                {Object.keys(data.exchanges).map((k) => <option key={k} value={k}>{EXCH[k] ?? k}</option>)}
              </select>
              <button onClick={add} disabled={!!busy || !sym.trim()} className={`${btn} border-slate-300 dark:border-slate-700`}>Add</button>
            </span>
          </div>
        )}
        {busy && <div className="text-amber-600" role="status">{busy}</div>}
        <ErrorBox error={err} />
        {results && (
          <div className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
            {results.map((r) => (
              <div key={`${r.ticker}${r.exchange ?? ""}`}>
                <b>{r.ticker}</b>:{" "}
                <span className={r.status === "failed" ? "text-rose-600" : r.status === "skipped_budget" ? "text-amber-600" : "text-emerald-600"}>
                  {r.status.replace("_", " ")}
                </span>
                {r.bars_added > 0 && <> (+{r.bars_added} days)</>}
                {r.last_date && <> · latest {r.last_date}</>}
                {r.message && <> · {r.message}</>}
              </div>
            ))}
          </div>
        )}
        {data.tracked.length > 0 && (
          <DataTable id="eu-symbols" compact rows={data.tracked} rowKey={(t) => t.symbol} initialSort={[{ key: "symbol", dir: "asc" }]}
            columns={[
              { key: "symbol", label: "EODHD symbol", type: "text", get: (t) => t.symbol,
                render: (t) => <>{t.listing_id && t.last_date ? <Link className="font-medium underline" href={`/research/analysis/${t.listing_id}`}>{t.symbol}</Link> : <span className="font-medium">{t.symbol}</span>}
                  {t.suffix_unverified && <span className="ml-1 text-xs text-amber-600" title="This exchange suffix isn't shown on EODHD's public pages. A 'not found' error may mean it's different.">(suffix unverified)</span>}</> },
              { key: "exchange", label: "Exchange", type: "enum", labels: EXCH, get: (t) => t.exchange, render: (t) => EXCH[t.exchange] ?? t.exchange },
              { key: "origin", label: "Why tracked", type: "enum", labels: ORIGIN, get: (t) => t.origin, render: (t) => ORIGIN[t.origin] ?? t.origin },
              { key: "last", label: "Latest day", type: "date", get: (t) => t.last_date,
                render: (t) => <span className={t.last_date && t.last_date >= t.expected_session ? "" : "text-amber-600"}>{t.last_date ?? "not downloaded"}</span> },
              { key: "remove", label: "", type: "text", sortable: false, filterable: false, get: () => null,
                render: (t) => t.origin === "user" ? <button className="text-rose-600 underline" onClick={() => remove(t)}>remove</button> : null },
            ]} />
        )}
        <p className="text-xs text-slate-500">
          Prices are adjusted for splits and dividends (open/high/low scaled by EODHD&apos;s adjusted close). A new dividend or split re-downloads
          the full history. Holidays follow built-in exchange calendars (not yet checked against each exchange&apos;s official list).
        </p>
      </div>
    </Section>
  );
}

export function FxPanel() {
  const { data, error, loading, reload } = useApi<FxStatus>("/api/fx/status");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const refresh = async () => {
    setBusy(true);
    setErr(null);
    try {
      await apiFetch("/api/fx/refresh", { method: "POST" });
      reload();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section title="Exchange rates (ECB reference rates)"
      right={<button onClick={refresh} disabled={busy} className="rounded border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-50 dark:border-slate-700">{busy ? "Updating…" : "Update rates"}</button>}>
      <div className="space-y-1 text-sm">
        {data.observations === 0 ? (
          <p className="text-slate-500">No ECB rates downloaded yet. Press <b>Update rates</b> (free, no key needed).</p>
        ) : (
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            {Object.entries(data.latest).map(([pair, r]) => (
              <span key={pair}>{pair} <b className="num">{r.rate.toFixed(4)}</b> <span className="text-xs text-slate-500">{r.date}{r.source === "ecb_derived" ? " (derived)" : ""}</span></span>
            ))}
            <span className="text-xs text-slate-500">{data.observations} published rates stored{data.last_refresh && <> · updated {fmtTimestamp(data.last_refresh.at)}</>}</span>
          </div>
        )}
        <ErrorBox error={err} />
        <p className="text-xs text-slate-500">{data.note} Used for IBKR holdings when the IBKR report has no rate. The synthetic demo keeps synthetic rates.</p>
      </div>
    </Section>
  );
}
