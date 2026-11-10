"use client";

import { useState } from "react";

import { ErrorBox, Note, Section, btnPrimary } from "@/components/ui";
import { ApiError, apiFetch, notifyStatus, type Status, useApi } from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";

export default function ImportPage() {
  const status = useApi<Status>("/api/status");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState<Status | null>(null);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const s = await apiFetch<Status>("/api/import", { method: "POST", body: fd });
      setDone(s);
      status.setData(s);
      notifyStatus();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(false);
    }
  };
  const s = done ?? status.data;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Import your workbook</h1>
      <Section title="Upload">
        <div className="space-y-3 text-sm">
          <p>Choose your Excel workbook (.xlsx). Only the <b>Live Portfolio</b> tab is read; every other tab is ignored. The file itself isn&apos;t kept:
            only what was read from it is stored, in the local database on this computer.</p>
          <div className="flex flex-wrap items-center gap-3">
            <input aria-label="Workbook file" type="file" accept=".xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="max-w-full text-sm" />
            <button className={btnPrimary} onClick={upload} disabled={!file || busy}>{busy ? "Reading… (and fetching ECB rates)" : "Import"}</button>
          </div>
          <p className="text-xs text-slate-500">Importing again replaces the previous import. Your review decisions are kept for rows that haven&apos;t changed.
            Password-protected or labelled (encrypted) files can&apos;t be read: save an unprotected copy first.</p>
        </div>
      </Section>
      <ErrorBox error={err} />
      {s && s.imported && (
        <Section title={done ? "Imported" : "Current import"}>
          <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            <dt className="text-slate-500">File</dt><dd>{s.filename}</dd>
            <dt className="text-slate-500">Tab</dt><dd>&quot;{s.sheet}&quot; (positions rows {s.position_rows.join("–")}, sales log rows {s.sales_rows?.join("–") ?? "not found"})</dd>
            <dt className="text-slate-500">Workbook saved</dt><dd>{fmtTimestamp(s.saved_at)} — prices are as of this date</dd>
            <dt className="text-slate-500">Imported</dt><dd>{fmtTimestamp(s.uploaded_at)}</dd>
            <dt className="text-slate-500">Position rows</dt>
            <dd>{s.accounting.position_rows}: {s.accounting.open_buys} open purchases · {s.accounting.closed_buys} closed purchases (P/L 0) ·{" "}
              {s.accounting.sales} sales · {s.accounting.excluded} excluded · {s.accounting.not_classified} waiting on review</dd>
            <dt className="text-slate-500">Sales-log rows</dt><dd>{s.accounting.sales_log_rows}: {s.accounting.sales_log_linked} linked to a position row, {s.accounting.sales_log_unlinked} typed by hand</dd>
            <dt className="text-slate-500">Exchange rates (ECB)</dt>
            <dd>{s.fx?.status === "error" ? <span className="text-rose-600">{s.fx.message}</span> : <>up to {s.fx_latest ?? "—"}</>}</dd>
          </dl>
          {s.stale_decisions.length > 0 && <div className="mt-2"><Note>{s.stale_decisions.length} earlier review decisions no longer apply because those rows changed in the sheet: {s.stale_decisions.slice(0, 20).join(", ")}{s.stale_decisions.length > 20 ? "…" : ""}</Note></div>}
          {s.review_pending > 0 && <div className="mt-3"><Note>Next: go to <a className="underline" href="/review">Review</a> to decide on the {s.review_pending} rows the app can&apos;t rebuild on its own. Until then they&apos;re left out of the results.</Note></div>}
        </Section>
      )}
    </div>
  );
}
