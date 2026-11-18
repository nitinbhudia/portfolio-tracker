"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { apiFetch, jsonInit } from "@/lib/api";

type Fav = { href: string; label: string };
type FavResp = { items: Fav[]; is_default: boolean };

const OPEN_KEY = "pt-favorites-open";
const iconBtn = "rounded px-1 text-xs text-slate-500 hover:bg-slate-200 hover:text-slate-900 disabled:opacity-30 dark:hover:bg-slate-700 dark:hover:text-slate-100";

/** The current page's title for a new shortcut: its <h1> (first line only), else its address. */
function pageTitle(fallback: string): string {
  const h1 = document.querySelector("main h1");
  const first = h1 ? (h1.childNodes[0]?.textContent ?? h1.textContent ?? "") : "";
  const t = first.replace(/\s+/g, " ").trim();
  const research = window.location.pathname.startsWith("/research") && !/research/i.test(t) ? " (Research)" : "";
  return (t ? t + research : fallback).slice(0, 60);
}

function List({ items, current, onChange, onNavigate }: {
  items: Fav[]; current: string; onChange: (items: Fav[]) => void; onNavigate?: () => void;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [name, setName] = useState("");
  const move = (i: number, d: number) => { const a = [...items]; [a[i], a[i + d]] = [a[i + d], a[i]]; onChange(a); };
  const save = (i: number) => {
    if (name.trim()) onChange(items.map((x, j) => (j === i ? { ...x, label: name.trim() } : x)));
    setEditing(null);
  };
  if (!items.length) return <p className="px-2 text-xs text-slate-500">No shortcuts yet: open a page and press ☆ Add this page.</p>;
  return (
    <ul className="space-y-0.5">
      {items.map((f, i) => (
        <li key={f.href} className="group flex items-center gap-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800">
          {editing === i ? (
            <input autoFocus aria-label="Shortcut name" className="m-0.5 w-full rounded border border-slate-300 bg-transparent px-1.5 py-0.5 text-sm dark:border-slate-600"
              value={name} onChange={(e) => setName(e.target.value)} onBlur={() => save(i)}
              onKeyDown={(e) => { if (e.key === "Enter") save(i); if (e.key === "Escape") setEditing(null); }} />
          ) : (
            <Link href={f.href} onClick={onNavigate} title={f.href}
              className={`min-w-0 flex-1 truncate px-2 py-1 text-sm ${current === f.href ? "font-semibold text-slate-900 dark:text-white" : "text-slate-700 dark:text-slate-300"}`}>
              {f.label}
            </Link>
          )}
          {editing !== i && (
            <span className="hidden shrink-0 group-focus-within:flex group-hover:flex">
              <button className={iconBtn} aria-label={`Rename ${f.label}`} title="Rename" onClick={() => { setEditing(i); setName(f.label); }}>✎</button>
              <button className={iconBtn} aria-label={`Move ${f.label} up`} title="Move up" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
              <button className={iconBtn} aria-label={`Move ${f.label} down`} title="Move down" disabled={i === items.length - 1} onClick={() => move(i, 1)}>↓</button>
              <button className={iconBtn} aria-label={`Remove ${f.label}`} title="Remove" onClick={() => onChange(items.filter((_, j) => j !== i))}>✕</button>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Left-hand shortcuts panel: jump to pages you use often; add the current one with ☆. Saved in the app's database. */
export function Favorites() {
  const path = usePathname();
  const search = useSearchParams();
  const current = path + (search.toString() ? `?${search.toString()}` : "");
  const [items, setItems] = useState<Fav[] | null>(null);
  const [open, setOpen] = useState(true);
  const [drawer, setDrawer] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<FavResp>("/api/favorites").then((r) => setItems(r.items)).catch(() => setItems([]));
    try { setOpen(localStorage.getItem(OPEN_KEY) !== "0"); } catch { /* ignore */ }
  }, []);
  useEffect(() => setDrawer(false), [path]);

  const update = useCallback(async (next: Fav[]) => {
    const before = items;
    setItems(next);
    setErr(null);
    try {
      const r = await apiFetch<FavResp>("/api/favorites", jsonInit("PUT", { items: next }));
      setItems(r.items);
    } catch (e) {
      setItems(before);
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [items]);
  const toggle = () => {
    setOpen(!open);
    try { localStorage.setItem(OPEN_KEY, open ? "0" : "1"); } catch { /* ignore */ }
  };

  const here = items?.some((f) => f.href === current) ?? false;
  const add = () => items && !here && update([...items, { href: current, label: pageTitle(current) }]);
  const body = (onNavigate?: () => void) => (
    <>
      <button onClick={add} disabled={!items || here}
        className="mb-2 w-full rounded border border-amber-400 px-2 py-1 text-left text-xs text-amber-800 hover:bg-amber-50 disabled:border-slate-200 disabled:text-slate-500 disabled:hover:bg-transparent dark:border-amber-700 dark:text-amber-300 dark:hover:bg-amber-950 dark:disabled:border-slate-700">
        {here ? "★ This page is a shortcut" : "☆ Add this page"}</button>
      {items ? <List items={items} current={current} onChange={update} onNavigate={onNavigate} /> : <p className="px-2 text-xs text-slate-500">Loading…</p>}
      {err && <p className="mt-2 px-2 text-xs text-rose-700 dark:text-rose-400">{err}</p>}
    </>
  );

  return (
    <>
      {/* wide screens: a panel beside the page, collapsible to a slim rail */}
      <aside aria-label="Shortcuts" className={`sticky top-[59px] hidden h-[calc(100vh-59px)] shrink-0 overflow-y-auto border-r border-slate-200 bg-white/60 lg:block dark:border-slate-800 dark:bg-slate-900/40 ${open ? "w-56 p-3" : "w-10 py-3"}`}>
        {open ? (
          <>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Shortcuts</span>
              <button className={iconBtn} aria-label="Collapse the shortcuts panel" title="Collapse" onClick={toggle}>«</button>
            </div>
            {body()}
          </>
        ) : (
          <button className="mx-auto block rounded px-1.5 py-1 text-amber-500 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Open the shortcuts panel" title="Shortcuts" onClick={toggle}>★</button>
        )}
      </aside>
      {/* narrow screens: a button that opens the panel as a drawer */}
      <button className="fixed bottom-4 left-4 z-30 rounded-full border border-slate-300 bg-white px-3 py-2 text-sm shadow-md lg:hidden dark:border-slate-700 dark:bg-slate-900"
        aria-label="Shortcuts" onClick={() => setDrawer(true)}><span className="text-amber-500">★</span> Shortcuts</button>
      {drawer && (
        <div className="fixed inset-0 z-40 bg-black/30 lg:hidden" onClick={() => setDrawer(false)}>
          <div role="dialog" aria-modal="true" aria-label="Shortcuts" onClick={(e) => e.stopPropagation()}
            className="absolute inset-y-0 left-0 w-72 max-w-[85vw] overflow-y-auto bg-white p-3 shadow-xl dark:bg-slate-900">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Shortcuts</span>
              <button className={iconBtn} aria-label="Close" onClick={() => setDrawer(false)}>✕</button>
            </div>
            {body(() => setDrawer(false))}
          </div>
        </div>
      )}
    </>
  );
}
