"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, type Status, STATUS_EVENT } from "@/lib/api";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/positions", label: "Positions" },
  { href: "/sales", label: "Sales" },
  { href: "/by-stock", label: "Per stock" },
  { href: "/years", label: "Per year" },
  { href: "/returns", label: "Returns" },
  { href: "/stats", label: "Statistics" },
  { href: "/review", label: "Review" },
  { href: "/stocks", label: "Names" },
  { href: "/check", label: "Check" },
  { href: "/import", label: "Import" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const load = () => apiFetch<Status>("/api/status").then((s) => setPending(s.imported ? s.review_pending : 0)).catch(() => {});
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
  useEffect(() => setOpen(false), [path]);

  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const badge = (href: string) => href === "/review" && pending > 0 && (
    <span className="ml-1 rounded-full bg-amber-500 px-1.5 text-[10px] font-bold text-white" aria-label={`${pending} rows to review`}>{pending}</span>
  );
  return (
    <>
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2">
          <Link href="/" className="font-semibold tracking-tight">Portfolio Tracker</Link>
          <nav className="hidden gap-0.5 xl:flex">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href}
                className={`rounded px-2.5 py-1.5 text-sm ${active(n.href) ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
                {n.label}{badge(n.href)}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button aria-label="Toggle dark mode" onClick={() => { localStorage.setItem("theme", dark ? "light" : "dark"); setDark(!dark); }}
              className="rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700">{dark ? "☀ Light" : "☾ Dark"}</button>
            <button aria-label="Menu" onClick={() => setOpen(!open)} className="rounded border border-slate-300 px-2 py-1 text-xs xl:hidden dark:border-slate-700">☰</button>
          </div>
        </div>
        {open && (
          <nav className="flex flex-col border-t border-slate-200 px-4 py-2 xl:hidden dark:border-slate-800">
            {NAV.map((n) => <Link key={n.href} href={n.href} className={`rounded px-2 py-2 text-sm ${active(n.href) ? "font-semibold" : ""}`}>{n.label}{badge(n.href)}</Link>)}
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-7xl px-3 py-4 sm:px-4">{children}</main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 pt-4 text-xs text-slate-500">
        Runs on your computer; your data stays in a local database. Reports what happened, not advice. Gains are before fees and dividends (not in the sheet).
      </footer>
    </>
  );
}
