"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";

import { ALERTS_EVENT, apiFetch, SOURCE_EVENT } from "@/lib/research/api";

type Theme = "system" | "light" | "dark";
const ThemeCtx = createContext<{ theme: Theme; setTheme: (t: Theme) => void; dark: boolean }>({
  theme: "system",
  setTheme: () => {},
  dark: false,
});
/** Research charts read the theme from here; it follows Portfolio Tracker's Dark / Light button (the "dark" class on <html>). */
export const useTheme = () => useContext(ThemeCtx);

const NAV = [
  { href: "/research", label: "Overview" },
  { href: "/research/sectors", label: "Sector Rotation" },
  { href: "/research/scanner", label: "Scanner" },
  { href: "/research/watchlist", label: "Watchlist" },
  { href: "/research/analysis", label: "Market Analysis" },
  { href: "/research/alerts", label: "Alerts" },
  { href: "/research/backtest", label: "Backtesting" },
  { href: "/research/settings", label: "Settings" },
];

/** The Research section (formerly the Fibonacci AI app): its own sub-menu, data notice and disclaimer, inside Portfolio Tracker. */
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [dark, setDark] = useState(false);
  const [holdingsSource, setHoldingsSource] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    const el = document.documentElement;
    const read = () => setDark(el.classList.contains("dark"));
    read();
    const mo = new MutationObserver(read);
    mo.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);

  useEffect(() => {
    const load = () =>
      apiFetch<{ holdings_source: string }>("/api/health")
        .then((h) => setHoldingsSource(h.holdings_source))
        .catch(() => {});
    load();
    window.addEventListener(SOURCE_EVENT, load);
    return () => window.removeEventListener(SOURCE_EVENT, load);
  }, []);

  useEffect(() => {
    const load = () =>
      apiFetch<{ unread: number }>("/api/alerts/summary")
        .then((r) => setUnread(r.unread))
        .catch(() => {});
    load();
    window.addEventListener(ALERTS_EVENT, load);
    return () => window.removeEventListener(ALERTS_EVENT, load);
  }, [path]);

  const setTheme = (t: Theme) => {
    try { localStorage.setItem("theme", t); } catch { /* ignore */ }
    const d = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", d);
  };
  const isActive = (href: string) => (href === "/research" ? path === "/research" : path.startsWith(href));

  return (
    <ThemeCtx.Provider value={{ theme: dark ? "dark" : "light", setTheme, dark }}>
      <div className="mb-4 border-b border-slate-200 pb-2 dark:border-slate-800">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-sm font-semibold"><span className="text-amber-500">φ</span> Research</span>
          <nav aria-label="Research" className="flex flex-wrap gap-1">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href}
                className={`rounded px-2.5 py-1 text-sm ${isActive(n.href) ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
                {n.label}
                {n.href === "/research/alerts" && unread > 0 && (
                  <span className="ml-1 rounded-full bg-rose-600 px-1.5 text-[10px] font-bold text-white" aria-label={`${unread} unread alerts`}>{unread > 99 ? "99+" : unread}</span>
                )}
              </Link>
            ))}
          </nav>
        </div>
        {holdingsSource === "synthetic" && (
          <p className="mt-2 rounded bg-violet-700 px-3 py-1 text-xs font-semibold text-white">
            Look for the REAL / SYNTHETIC tag on every chart and table: synthetic demo data is generated, not real market data.
          </p>
        )}
      </div>
      {children}
      <div className="mt-8 text-xs text-slate-500">
        <p><b>Research tool, not investment advice.</b> It does not place trades or make recommendations. Fibonacci levels are analytical
          reference levels, not guaranteed support or resistance. No single indicator is a buy or sell signal.</p>
        <p className="mt-1">Charts by{" "}
          <a className="underline" href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a>.</p>
      </div>
    </ThemeCtx.Provider>
  );
}
