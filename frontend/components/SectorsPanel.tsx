"use client";

import { useState } from "react";

import { ApiError, apiFetch, jsonInit, type SectorsResp, useApi } from "@/lib/api";

import { ErrorBox, Loading, Note, Section, btn, btnPrimary, input } from "./ui";

/** Sectors per stock: Claude suggests (unconfirmed), you check, change and confirm. Only confirmed sectors are used. */
export function SectorsPanel() {
  const q = useApi<SectorsResp>("/api/sectors");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  const run = async (fn: () => Promise<SectorsResp>, done?: (r: SectorsResp) => string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      q.setData(r);
      if (done) setMsg(done(r));
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(false);
    }
  };
  const rows = d.stocks.filter((s) => showAll || s.open);
  return (
    <Section title={`Sectors (${d.counts.open_confirmed} of ${d.counts.open} open positions confirmed)`} right={
      <span className="flex flex-wrap gap-2">
        {d.ai_available && <button className={btnPrimary} disabled={busy} onClick={() => run(() => apiFetch("/api/sectors/suggest", { method: "POST" }),
          (r) => `${r.suggested ?? 0} sectors suggested: check them below, then confirm.`)}>{busy ? "Asking Claude…" : "Suggest sectors with AI"}</button>}
        {d.counts.suggested_unconfirmed > 0 && <button className={btn} disabled={busy} onClick={() => run(() => apiFetch("/api/sectors/confirm-all", { method: "POST" }))}>
          Confirm all {d.counts.suggested_unconfirmed} suggestions</button>}
      </span>}>
      <p className="mb-2 text-xs text-slate-500">Used by What-if and Ask for sector questions. Only confirmed sectors are used. {d.ai_available
        ? "\"Suggest\" sends the names of your open positions (no amounts) to Anthropic's API and fills in unconfirmed suggestions; nothing you've set or confirmed is changed."
        : "Add an Anthropic API key to the app's .env file to get AI suggestions, or set them yourself."}</p>
      {msg && <Note tone="emerald">{msg}</Note>}
      <ErrorBox error={err} />
      <div className="max-h-[28rem] overflow-auto">
        <table className="tbl w-full text-sm">
          <thead className="sticky top-0 bg-white dark:bg-slate-900"><tr><th>Stock</th><th>Sector</th><th></th></tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.group_key}>
              <td>{s.stock}{!s.open && <span className="ml-1 text-xs text-slate-500">(closed)</span>}</td>
              <td><select aria-label={`Sector for ${s.stock}`} className={input} value={s.sector ?? ""}
                onChange={(e) => run(() => apiFetch(`/api/sectors/${encodeURIComponent(s.group_key)}`, jsonInit("PUT", { sector: e.target.value || null })))}>
                <option value="">—</option>{d.sectors.map((x) => <option key={x}>{x}</option>)}</select></td>
              <td className="text-xs">{s.sector && (s.confirmed
                ? <span className="text-emerald-700 dark:text-emerald-400">✓ {s.source === "ai" ? "AI, confirmed" : "set by you"}</span>
                : <span className="flex items-center gap-2"><span className="rounded bg-amber-100 px-1.5 text-amber-800 dark:bg-amber-900 dark:text-amber-200">AI suggestion</span>
                  <button className="underline" onClick={() => run(() => apiFetch(`/api/sectors/${encodeURIComponent(s.group_key)}`, jsonInit("PUT", { sector: s.sector })))}>confirm</button></span>)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <label className="mt-2 flex items-center gap-1 text-xs"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />show closed positions too</label>
    </Section>
  );
}
