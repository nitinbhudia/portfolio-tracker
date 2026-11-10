"use client";

import { useState } from "react";

import { ErrorBox, Loading, Note, Section, btn, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type StockGroup, type StocksResp, useApi } from "@/lib/api";

function Row({ g, onChange }: { g: StockGroup; onChange: (s: StocksResp) => void }) {
  const [name, setName] = useState(g.display_name);
  const [ticker, setTicker] = useState(g.ticker ?? "");
  const dirty = name !== g.display_name || ticker !== (g.ticker ?? "");
  const save = async () => onChange(await apiFetch<StocksResp>(`/api/stocks/${encodeURIComponent(g.group_key)}`, jsonInit("PUT", { display_name: name, ticker })));
  const split = async (k: string) => onChange(await apiFetch<StocksResp>("/api/stocks/split", jsonInit("POST", { name_key: k })));
  return (
    <tr>
      <td><input aria-label={`Name for ${g.display_name}`} className={`${input} w-48`} value={name} onChange={(e) => setName(e.target.value)} /></td>
      <td><input aria-label={`Ticker for ${g.display_name}`} className={`${input} w-20 uppercase`} value={ticker} onChange={(e) => setTicker(e.target.value)} /></td>
      <td className="whitespace-normal text-xs">
        {g.names.map((n) => (
          <span key={n.name_key} className="mr-2 inline-block">{n.as_written.join(" / ")} <span className="text-slate-500">({n.rows})</span>
            {g.names.length > 1 && <button className="ml-1 underline" onClick={() => split(n.name_key)} aria-label={`Split ${n.as_written[0]} out`}>split</button>}
          </span>
        ))}
      </td>
      <td className="text-right">{g.rows}</td><td className="text-right">{g.open_rows}</td><td>{g.currencies.join(", ")}</td>
      <td>{dirty && <button className={btn} onClick={save}>Save</button>}</td>
    </tr>
  );
}

export default function StocksPage() {
  const q = useApi<StocksResp>("/api/stocks");
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const merge = async (keys: string[], label: string) => {
    setErr(null);
    try {
      q.setData(await apiFetch<StocksResp>("/api/stocks/merge", jsonInit("POST", { name_keys: keys, display_name: label })));
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    }
  };
  const shown = d.stocks.filter((g) => !filter || g.display_name.toLowerCase().includes(filter.toLowerCase()) || g.names.some((n) => n.name_key.includes(filter.toLowerCase())));
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Stocks</h1>
      <Note tone="slate">Your sheet&apos;s Ticker column can&apos;t be read outside Excel, so stocks are identified by their Stock Name. Names that differ only in spaces or
        capitals are already treated as one stock. Merge names that are the same stock; FIFO then runs across all their rows (per currency).</Note>
      <ErrorBox error={err} />
      {d.suggestions.length > 0 && (
        <Section title={`Possibly the same stock (${d.suggestions.length})`}>
          <p className="mb-2 text-xs text-slate-500">Suggestions only (similar spelling). Merge the ones that really are the same stock; ignore the rest (two different companies can have similar names).</p>
          <ul className="space-y-1 text-sm">
            {d.suggestions.map((s) => (
              <li key={s.map((x) => x.name_key).join("|")} className="flex flex-wrap items-center gap-2">
                <span>{s.map((x) => x.as_written.join(" / ")).join("  ↔  ")}</span>
                <button className={btn} onClick={() => merge(s.map((x) => x.name_key), s[s.length - 1].as_written[0])}>Merge as &quot;{s[s.length - 1].as_written[0]}&quot;</button>
              </li>
            ))}
          </ul>
        </Section>
      )}
      <Section title={`${d.stocks.length} stocks`} right={<input aria-label="Filter stocks" placeholder="filter…" className={input} value={filter} onChange={(e) => setFilter(e.target.value)} />}>
        <div className="overflow-x-auto">
          <table className="tbl w-full text-sm">
            <thead><tr><th>Name shown</th><th>Ticker</th><th>Names in the sheet (rows)</th><th className="text-right">Rows</th><th className="text-right">Open</th><th>Ccy</th><th></th></tr></thead>
            <tbody>{shown.map((g) => <Row key={g.group_key} g={g} onChange={(s) => q.setData(s)} />)}</tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
