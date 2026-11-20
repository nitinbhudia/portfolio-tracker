"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type Mode = { demo: boolean; built_at?: string | null; as_of?: string | null; resetting?: boolean; reset_error?: string | null };

const COOKIE = "pt_mode";

/** The browser's choice: the cookie the frontend uses to send /api/* to the live (8001) or demo (8002) backend. */
export function demoChosen(): boolean {
  return typeof document !== "undefined" && document.cookie.split(/;\s*/).includes(`${COOKIE}=demo`);
}

/** demoChosen() as React state (read after the first render, so server and browser render the same). */
export function useDemoChosen(): boolean {
  const [d, setD] = useState(false);
  useEffect(() => setD(demoChosen()), []);
  return d;
}

function choose(demo: boolean) {
  document.cookie = demo ? `${COOKIE}=demo; path=/; max-age=31536000; samesite=lax` : `${COOKIE}=; path=/; max-age=0; samesite=lax`;
  try { sessionStorage.removeItem("pt-update"); } catch { /* ignore */ }
  window.location.reload(); // nothing from the other mode stays on screen or in memory
}

function useMode() {
  const [chosen, setChosen] = useState(false);
  const [mode, setMode] = useState<Mode | null>(null);
  const [down, setDown] = useState(false);
  const load = useCallback(() => apiFetch<Mode>("/api/mode").then((m) => { setMode(m); setDown(false); return m; })
    .catch(() => { setDown(true); return null; }), []);
  useEffect(() => { setChosen(demoChosen()); load(); }, [load]);
  useEffect(() => {  // while a reset runs, follow it, then reload the page with the new data
    if (!mode?.resetting) return;
    const t = setInterval(() => load().then((m) => { if (m && !m.resetting && !m.reset_error) window.location.reload(); }), 3000);
    return () => clearInterval(t);
  }, [mode?.resetting, load]);
  return { chosen, mode, down, setMode };
}

/** Live | Demo switch in the header. */
export function DemoSwitch() {
  const { chosen } = useMode();
  const seg = (on: boolean) => `px-2 py-1 ${on ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`;
  return (
    <div role="group" aria-label="Data shown" className="flex shrink-0 overflow-hidden rounded border border-slate-300 text-xs dark:border-slate-700"
      title="Live: your real portfolio. Demo: a made-up portfolio for showing the app to others.">
      <button className={seg(!chosen)} aria-pressed={!chosen} onClick={() => chosen && choose(false)}>Live</button>
      <button className={`${seg(chosen)} border-l border-slate-300 dark:border-slate-700 ${chosen ? "!bg-amber-500 !text-slate-950" : ""}`}
        aria-pressed={chosen} onClick={() => !chosen && choose(true)}>Demo</button>
    </div>
  );
}

/** Under the header, on every page while the demo is on: says so, and offers Reset. Driven by what the backend says it
 * serves, so it can't claim "demo" while showing real data. */
export function DemoBanner() {
  const { chosen, mode, down, setMode } = useMode();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!chosen) return null;
  if (down || (mode && !mode.demo)) {
    return (
      <div role="alert" className="border-b border-rose-300 bg-rose-50 px-4 py-2 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-100">
        <b>Demo is selected, but the demo copy isn&apos;t running</b>, so no data is shown (your real data is never shown in its place).
        Restart the app to start it, or <button className="underline" onClick={() => choose(false)}>switch to Live</button>.
      </div>
    );
  }
  if (!mode) return null;
  const reset = async () => {
    if (!confirm("Rebuild the demo with fresh made-up data? Anything you changed in the demo is lost (your real data isn't touched).")) return;
    setBusy(true);
    setErr(null);
    try { setMode(await apiFetch<Mode>("/api/demo/reset", { method: "POST" })); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); } finally { setBusy(false); }
  };
  return (
    <div role="status" aria-label="Demo mode" className="border-b border-amber-300 bg-amber-100 px-4 py-1.5 text-sm text-amber-950 dark:border-amber-700 dark:bg-amber-900 dark:text-amber-50">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-1">
        <span className="rounded bg-amber-500 px-1.5 text-xs font-bold uppercase tracking-wide text-slate-950">Demo</span>
        <span>A made-up portfolio of invented companies with synthetic prices. Nothing here is your real data, and changes here never reach it.</span>
        <span className="ml-auto flex items-center gap-2 text-xs">
          {mode.resetting ? <span role="status">Building fresh demo data… (about half a minute)</span>
            : <>{mode.as_of && <span className="opacity-75">prices to {mode.as_of}</span>}
              <button className="rounded border border-amber-600 px-2 py-0.5 hover:bg-amber-200 disabled:opacity-50 dark:hover:bg-amber-800" disabled={busy} onClick={reset}>Reset demo data</button></>}
          <button className="underline" onClick={() => choose(false)}>Back to Live</button>
        </span>
        {(err || mode.reset_error) && <span className="w-full text-xs text-rose-800 dark:text-rose-200">Reset failed: {err || mode.reset_error}. The previous demo data is still there.</span>}
      </div>
    </div>
  );
}
