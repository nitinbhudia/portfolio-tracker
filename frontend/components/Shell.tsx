"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, type Status, STATUS_EVENT } from "@/lib/api";

import { RangeProvider } from "./RangePicker";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/positions", label: "Positions" },
  { href: "/sales", label: "Sales" },
  { href: "/by-stock", label: "Per stock" },
  { href: "/years", label: "Per year" },
  { href: "/returns", label: "Returns" },
  { href: "/stats", label: "Statistics" },
  { href: "/indexes", label: "vs Indexes" },
];
// Entering and maintaining data: grouped under one menu.
const DATA = [
  { href: "/trades", label: "Trades" },
  { href: "/dividends", label: "Dividends" },
  { href: "/prices", label: "Prices" },
  { href: "/review", label: "Review" },
  { href: "/stocks", label: "Names" },
  { href: "/check", label: "Check vs sheet" },
  { href: "/import", label: "Import" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [pending, setPending] = useState(0);
  // null = not known yet; pages only load (and ask the backend for results) once an import exists
  const [imported, setImported] = useState<boolean | null>(null);

  useEffect(() => {
    const load = () => apiFetch<Status>("/api/status")
      .then((s) => { setPending(s.imported ? s.review_pending : 0); setImported(s.imported); })
      .catch(() => setImported(true)); // backend unreachable: let the page show its own error
    load();
    window.addEventListener(STATUS_EVENT, load);
    return () => window.removeEventListener(STATUS_EVENT, load);
  }, [path]);

  useEffect(() => {
    const saved = localStorage.getItem("theme");
    const d = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(d);
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    setOpen(false);
    setDataOpen(false);
  }, [path]);

  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const badge = (href: string) => href === "/review" && pending > 0 && (
    <span className="ml-1 rounded-full bg-amber-500 px-1.5 text-[10px] font-bold text-white" aria-label={`${pending} rows to review`}>{pending}</span>
  );
  return (
    <RangeProvider>
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2">
          <Link href="/" className="font-semibold tracking-tight">Portfolio Tracker</Link>
          <nav className="hidden gap-0.5 lg:flex">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href}
                className={`rounded px-2.5 py-1.5 text-sm ${active(n.href) ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
                {n.label}{badge(n.href)}
              </Link>
            ))}
            <div className="relative">
              <button aria-expanded={dataOpen} aria-haspopup="true" onClick={() => setDataOpen(!dataOpen)}
                className={`rounded px-2.5 py-1.5 text-sm ${DATA.some((n) => active(n.href)) ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
                Data{pending > 0 && <span className="ml-1 rounded-full bg-amber-500 px-1.5 text-[10px] font-bold text-white" aria-label={`${pending} rows to review`}>{pending}</span>} ▾
              </button>
              {dataOpen && (
                <div className="absolute left-0 top-full z-20 mt-1 flex w-48 flex-col rounded-md border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
                  {DATA.map((n) => (
                    <Link key={n.href} href={n.href} className={`rounded px-2.5 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${active(n.href) ? "font-semibold" : ""}`}>
                      {n.label}{badge(n.href)}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button aria-label="Toggle dark mode" onClick={() => { localStorage.setItem("theme", dark ? "light" : "dark"); setDark(!dark); }}
              className="rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700">{dark ? "☀ Light" : "☾ Dark"}</button>
            <button aria-label="Menu" onClick={() => setOpen(!open)} className="rounded border border-slate-300 px-2 py-1 text-xs lg:hidden dark:border-slate-700">☰</button>
          </div>
        </div>
        {open && (
          <nav className="flex flex-col border-t border-slate-200 px-4 py-2 lg:hidden dark:border-slate-800">
            {NAV.map((n) => <Link key={n.href} href={n.href} className={`rounded px-2 py-2 text-sm ${active(n.href) ? "font-semibold" : ""}`}>{n.label}{badge(n.href)}</Link>)}
            <div className="mt-2 border-t border-slate-200 px-2 pt-2 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">Data</div>
            {DATA.map((n) => <Link key={n.href} href={n.href} className={`rounded px-2 py-2 text-sm ${active(n.href) ? "font-semibold" : ""}`}>{n.label}{badge(n.href)}</Link>)}
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-7xl px-3 py-4 sm:px-4">
        {imported === null && !path.startsWith("/import") ? (
          <div role="status" className="p-6 text-sm text-slate-500">Loading…</div>
        ) : imported === false && !path.startsWith("/import") ? (
          <div className="mx-auto max-w-xl space-y-4 py-10 text-center">
            <h1 className="text-2xl font-semibold">Nothing imported yet</h1>
            <p className="text-slate-600 dark:text-slate-300">Import your workbook&apos;s Live Portfolio tab first. The results pages fill in from it.
              (Each copy of the app has its own database: a fresh download starts empty.)</p>
            <Link href="/import" className="inline-block rounded bg-slate-900 px-3 py-1.5 text-sm text-white dark:bg-slate-100 dark:text-slate-900">Import workbook</Link>
          </div>
        ) : children}
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 pt-4 text-xs text-slate-500">
        Runs on your computer; your data stays in a local database. Reports what happened, not advice. Fees and dividends count once entered on the Data pages.
      </footer>
    </RangeProvider>
  );
}
