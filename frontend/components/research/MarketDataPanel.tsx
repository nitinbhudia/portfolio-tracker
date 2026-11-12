"use client";

import Link from "next/link";
import { useState } from "react";

import { DataTable } from "@/components/research/DataTable";
import { ErrorBox, Loading, Section, Warn } from "@/components/research/ui";
import { ApiError, apiFetch, useApi } from "@/lib/research/api";
import { fmtTimestamp } from "@/lib/research/format";

type Tracked = { ticker: string; exchange: string; origin: string; listing_id: number | null; bars: number; last_date: string | null };
type Usage = { last_hour: number; last_day: number; hourly_budget: number; daily_budget: number };
type Status = {
  provider: string;
  configured: boolean;
  expected_session: string;
  tracked: Tracked[];
  usage: Usage;
  last_refresh: { at: string; session: string; updated: number; failed: number } | null;
  limits_note: string;
};
type RefreshResult = { ticker: string; status: string; bars_added: number; last_date?: string | null; message?: string; error_code?: string };

const ORIGIN: Record<string, string> = { benchmark: "US market benchmark", sector: "sector ETF (Sector Rotation)", ibkr: "your IBKR holding", user: "added by you" };

export function MarketDataPanel({ onChanged }: { onChanged: () => void }) {
  const { data, error, loading, reload } = useApi<Status>("/api/market-data/status");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [results, setResults] = useState<RefreshResult[] | null>(null);
  const [sym, setSym] = useState("");

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setErr(null);
    try {
      await fn();
      reload();
      onChanged();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(null);
    }
  };

  const refresh = () =>
    run("Downloading prices from Tiingo… (the first time takes a little longer)", async () => {
      const r = await apiFetch<{ results: RefreshResult[] }>("/api/market-data/refresh", { method: "POST" });
      setResults(r.results);
    });

  const add = () =>
    sym.trim() &&
    run(`Adding ${sym.toUpperCase()}…`, async () => {
      const r = await apiFetch<RefreshResult>("/api/market-data/symbols", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: sym }),
      });
      setResults([r]);
      setSym("");
    });

  const remove = (t: string) => run(`Removing ${t}…`, async () => void (await apiFetch(`/api/market-data/symbols/${encodeURIComponent(t)}`, { method: "DELETE" })));

  const upToDate = data.tracked.filter((t) => t.last_date && t.last_date >= data.expected_session).length;
  const btn = "rounded border px-3 py-1.5 text-sm disabled:opacity-50";

  return (
    <Section
      title="Real US prices (Tiingo, end-of-day)"
      right={
        <span className="text-xs text-slate-500">
          Requests: {data.usage.last_hour}/{data.usage.hourly_budget} this hour · {data.usage.last_day}/{data.usage.daily_budget} today
        </span>
      }
    >
      {!data.configured ? (
        <Warn>
          Add your free Tiingo key to <code>.env</code> as <code>TIINGO_API_KEY=…</code>, then restart the app (Control + C, then{" "}
          <code>./scripts/dev.sh</code>).
        </Warn>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={refresh} disabled={!!busy}
              className={`${btn} border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900`}>
              Update prices
            </button>
            <span className="text-xs text-slate-500">
              {upToDate}/{data.tracked.length} up to date for {data.expected_session}
              {data.last_refresh && <> · last update {fmtTimestamp(data.last_refresh.at)}</>}
            </span>
            <span className="ml-auto flex items-center gap-1">
              <input value={sym} onChange={(e) => setSym(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()}
                placeholder="Add US ticker, e.g. MSFT" aria-label="Add US ticker"
                className="w-44 rounded border border-slate-300 bg-transparent px-2 py-1 text-sm dark:border-slate-700" />
              <button onClick={add} disabled={!!busy || !sym.trim()} className={`${btn} border-slate-300 dark:border-slate-700`}>Add</button>
            </span>
          </div>
          {busy && <div className="text-amber-600" role="status">{busy}</div>}
          <ErrorBox error={err} />
          {results && (
            <div className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
              {results.map((r) => (
                <div key={r.ticker}>
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
          <DataTable
            id="tracked-symbols"
            compact
            rows={data.tracked}
            rowKey={(t) => t.ticker + t.exchange}
            initialSort={[{ key: "origin", dir: "asc" }]}
            columns={[
              { key: "ticker", label: "Symbol", type: "text", get: (t) => t.ticker,
                render: (t) => <>{t.listing_id && t.bars > 0 ? <Link className="font-medium underline" href={`/research/analysis/${t.listing_id}`}>{t.ticker}</Link> : <span className="font-medium">{t.ticker}</span>}<span className="ml-1 text-xs text-slate-500">{t.exchange}</span></> },
              { key: "origin", label: "Why tracked", type: "enum", labels: ORIGIN, get: (t) => t.origin, render: (t) => ORIGIN[t.origin] ?? t.origin },
              { key: "bars", label: "Days of history", type: "number", align: "right", get: (t) => t.bars },
              { key: "last", label: "Latest day", type: "date", get: (t) => t.last_date,
                render: (t) => <span className={t.last_date && t.last_date >= data.expected_session ? "" : "text-amber-600"}>{t.last_date ?? "not downloaded"}</span> },
              { key: "uptodate", label: "Up to date", type: "bool", labels: { true: "yes", false: "no" }, get: (t) => !!t.last_date && t.last_date >= data.expected_session,
                render: (t) => (t.last_date && t.last_date >= data.expected_session ? "yes" : "no") },
              { key: "remove", label: "", type: "text", sortable: false, filterable: false, get: () => null,
                render: (t) => t.origin === "user" ? <button className="text-rose-600 underline" onClick={() => remove(t.ticker)}>remove</button> : null },
            ]}
          />
          <p className="text-xs text-slate-500">
            {data.limits_note} Prices are adjusted for splits and dividends. Index levels aren&apos;t included in the free plan, so the S&amp;P 500,
            Nasdaq-100, Dow and Russell 2000 are tracked with their ETFs (SPY, QQQ, DIA, IWM). European listings (e.g. ASML, SAP, NESN) come from
            EODHD (see below).
          </p>
        </div>
      )}
    </Section>
  );
}
