"use client";

import { useState } from "react";

import { ErrorBox, Loading, Note, Section, btn, btnPrimary, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit, type PriceRow, type PricesResp, useApi } from "@/lib/api";
import { num, qty, usd } from "@/lib/format";

function Row({ r, onSaved }: { r: PriceRow; onSaved: (p: PricesResp) => void }) {
  const [v, setV] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setErr(null);
    try {
      onSaved(await apiFetch<PricesResp>(`/api/prices?pool=${encodeURIComponent(r.pool)}`, jsonInit("PUT", { price: Number(v) })));
      setV("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  const last = r.history[0];
  return (
    <tr>
      <td className="whitespace-normal">{r.stock}</td><td>{r.currency}{r.pence ? " (p)" : ""}</td><td className="text-right">{qty(r.shares)}</td>
      <td className="text-right font-medium">{num(r.price, 2)}</td><td>{r.price_date ?? "—"}</td>
      <td className="whitespace-normal text-xs text-slate-500">{r.price_source ?? "no price yet"}</td><td className="text-right">{usd(r.value_usd)}</td>
      <td>
        <span className="flex items-center gap-1">
          <input aria-label={`New price for ${r.stock}`} inputMode="decimal" className={`${input} w-24`} placeholder="today's price" value={v} onChange={(e) => setV(e.target.value)} />
          <button className={`${btn} text-xs`} disabled={!Number(v)} onClick={save}>Save</button>
          {last && last.source === "typed in the app" && (
            <button className="text-xs text-slate-500 underline" title="Remove the last price you typed"
              onClick={async () => onSaved(await apiFetch<PricesResp>(`/api/prices/${last.id}`, { method: "DELETE" }))}>undo</button>
          )}
        </span>
        {err && <div role="alert" className="text-xs text-rose-600">{err}</div>}
      </td>
    </tr>
  );
}

export default function PricesPage() {
  const q = useApi<PricesResp>("/api/prices");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [result, setResult] = useState<PricesResp | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await apiFetch<PricesResp>("/api/prices/workbook", { method: "POST", body: fd });
      setResult(r);
      q.setData(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Prices</h1>
      <Section title="Update prices from your workbook">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <input aria-label="Workbook for prices" type="file" accept=".xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="max-w-full" />
          <button className={btnPrimary} disabled={!file || busy} onClick={upload}>{busy ? "Reading…" : "Update prices"}</button>
        </div>
        <p className="mt-2 text-xs text-slate-500">Reads only the Live Price of the open rows in the Live Portfolio tab, dated on the day the workbook was saved.
          Trades, review decisions and everything else stay as they are.</p>
        <ErrorBox error={err} />
        {result && (
          <div className="mt-2 space-y-1">
            <Note tone="emerald">{result.updated} prices updated from the workbook saved on {result.workbook_saved}.</Note>
            {result.not_held && result.not_held.length > 0 && <Note>Open in the workbook but not held in the app (add the trades on the Trades page): {result.not_held.join(", ")}.</Note>}
            {result.no_price_in_workbook && result.no_price_in_workbook.length > 0 && <Note tone="slate">Held in the app but with no open row in the workbook (price unchanged): {result.no_price_in_workbook.length} stocks.</Note>}
          </div>
        )}
      </Section>
      <Section title={`Open positions (${q.data.prices.length})`}>
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <thead><tr><th>Stock</th><th>Ccy</th><th className="text-right">Shares</th><th className="text-right">Price</th><th>Date</th><th>From</th><th className="text-right">Value</th><th>Type a new price</th></tr></thead>
            <tbody>{q.data.prices.map((r) => <Row key={r.pool} r={r} onSaved={(p) => q.setData(p)} />)}</tbody>
          </table>
        </div>
        <p className="mt-1 text-xs text-slate-500">The newest price wins: a price you type is dated today; the sheet&apos;s prices are dated {q.data.sheet_as_of}. GBP prices are in pence when marked (p).</p>
      </Section>
    </div>
  );
}
