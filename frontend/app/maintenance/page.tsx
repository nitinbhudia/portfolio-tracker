"use client";

import { useEffect, useState } from "react";

import { ErrorBox, Loading, Note, Section, btn, btnPrimary } from "@/components/ui";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import { fmtTimestamp } from "@/lib/format";

type Backup = { id: string; reason: string; at: string; files: Record<string, number>; version: string | null };
type Maint = { version: { sha: string | null; date: string | null; note?: string }; supervised: boolean; backups: Backup[]; backups_folder: string };
type Check = { current: Maint["version"]; latest: { sha: string; date: string }; update_available: boolean; whats_new: string[] };

const REASON: Record<string, string> = { daily: "Daily (automatic)", manual: "Made by you", "before-update": "Before an update", "before-restore": "Before a restore" };
const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : "—");
const mb = (b: Backup) => `${(Object.values(b.files).reduce((a, x) => a + x, 0) / 1e6).toFixed(1)} MB`;

/** Wait for the app to go down and come back after a restart, then reload the page. */
async function waitForRestart(setStatus: (s: string) => void) {
  setStatus("Restarting the app… this page reloads by itself when it's back (usually under a minute).");
  const t0 = Date.now();
  await new Promise((r) => setTimeout(r, 4000));
  while (Date.now() - t0 < 5 * 60_000) {
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      if (r.ok) { window.location.reload(); return; }
    } catch { /* still restarting */ }
    await new Promise((r) => setTimeout(r, 2000));
  }
  setStatus("The app hasn't come back after 5 minutes: look at its Terminal window for a message, or start it again.");
}

export default function MaintenancePage() {
  const q = useApi<Maint>("/api/maintenance");
  const [chk, setChk] = useState<Check | null>(null);
  const [chkErr, setChkErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const check = () => {
    setChkErr(null);
    apiFetch<Check>("/api/maintenance/check").then((c) => {
      setChk(c);
      try { sessionStorage.setItem("pt-update", c.update_available ? "1" : "0"); } catch { /* ignore */ }
    }).catch((e) => setChkErr(e instanceof Error ? e.message : String(e)));
  };
  useEffect(check, []);

  const run = async (label: string, path: string, method = "POST") => {
    setBusy(label);
    setErr(null);
    try {
      const r = await apiFetch<{ restarting?: boolean; status?: string }>(path, { method });
      if (r.restarting) { await waitForRestart(setStatus); return; }
      if (r.status === "updated") setStatus("Updated. Close the app's Terminal window and start it again to finish (this copy can't restart itself yet).");
      if (path.includes("/restore")) setStatus("Restored. Close the app's Terminal window and start it again to finish.");
      q.reload();
      check();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(null);
    }
  };

  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const d = q.data;
  return (
    <div className="max-w-4xl space-y-4">
      <h1 className="text-xl font-semibold">Updates &amp; backups</h1>
      {status && <Note tone="slate"><span role="status">{status}</span></Note>}
      <ErrorBox error={err} />
      <Section title="Version">
        <div className="space-y-2 text-sm">
          <p>This copy: <b className="num">{short(d.version.sha)}</b>{d.version.date && <> from {fmtTimestamp(d.version.date)}</>}
            {!d.version.sha && <span className="text-slate-500"> ({d.version.note})</span>}</p>
          {chkErr ? <p className="text-rose-700 dark:text-rose-400">{chkErr}</p> : !chk ? <p className="text-slate-500">Checking GitHub for a newer version…</p> : chk.update_available ? (
            <>
              <p>Newest on GitHub: <b className="num">{short(chk.latest.sha)}</b> from {fmtTimestamp(chk.latest.date)}.</p>
              {chk.whats_new.length > 0 && (
                <div><p className="font-medium">What&apos;s new</p>
                  <ul className="mt-1 list-disc pl-5 text-slate-700 dark:text-slate-300">{chk.whats_new.map((w, i) => <li key={i}>{w}</li>)}</ul></div>
              )}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <button className={btnPrimary} disabled={!!busy}
                  onClick={() => window.confirm("Update now? Your databases are backed up first; your data, keys and settings are kept. The app restarts by itself.") && run("Updating…", "/api/maintenance/update")}>
                  {busy === "Updating…" ? "Downloading and installing…" : "Update now"}</button>
                <span className="text-xs text-slate-500">Backs up first, keeps your data and keys{d.supervised ? ", then restarts the app" : ""}.</span>
              </div>
            </>
          ) : <p className="text-emerald-700 dark:text-emerald-400">You have the newest version.</p>}
          {!d.supervised && <p className="text-xs text-amber-700 dark:text-amber-400">This copy was started by an older starter, so after an update or a restore
            close its Terminal window and start it again. From the next start, it restarts by itself.</p>}
          <button className={`${btn} text-xs`} onClick={check}>Check again</button>
        </div>
      </Section>
      <Section title="Backups" right={<button className={btnPrimary} disabled={!!busy} onClick={() => run("Backing up…", "/api/backups")}>{busy === "Backing up…" ? "Backing up…" : "Back up now"}</button>}>
        <p className="mb-2 text-xs text-slate-500">Copies of both databases (your portfolio, decisions, prices, shortcuts, and Research&apos;s watchlist and prices),
          in <span className="num">{d.backups_folder}</span>. One a day automatically (the last 14 are kept), one before every update or restore, and whenever you
          press Back up now. Restore puts a backup back (after backing up the current state) and restarts the app.</p>
        {d.backups.length === 0 ? <p className="text-sm text-slate-500">No backups yet.</p> : (
          <div className="overflow-x-auto">
            <table className="tbl num w-full text-sm">
              <thead><tr><th>When</th><th>Kind</th><th className="text-right">Size</th><th>Version</th><th></th></tr></thead>
              <tbody>{d.backups.map((b) => (
                <tr key={b.id}>
                  <td>{fmtTimestamp(b.at)}</td><td>{REASON[b.reason] ?? b.reason}</td><td className="text-right">{mb(b)}</td><td>{short(b.version)}</td>
                  <td className="whitespace-nowrap text-right">
                    <a className="text-xs underline" href={`/api/backups/${encodeURIComponent(b.id)}/download`}>download</a>
                    <button className="ml-3 text-xs underline" disabled={!!busy}
                      onClick={() => window.confirm(`Restore the backup from ${fmtTimestamp(b.at)}? Everything changed since then is replaced (the current state is backed up first). The app restarts.`)
                        && run("Restoring…", `/api/backups/${encodeURIComponent(b.id)}/restore`)}>restore</button>
                    <button className="ml-3 text-xs text-rose-700 underline dark:text-rose-400" disabled={!!busy}
                      onClick={() => window.confirm("Delete this backup?") && run("Deleting…", `/api/backups/${encodeURIComponent(b.id)}`, "DELETE")}>delete</button>
                  </td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
