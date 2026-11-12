"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";

import {
  applyFilters,
  type ColumnSpec,
  distinctValues,
  type Filter,
  type Filters,
  isActive,
  moveBefore,
  resolveOrder,
  shift,
  sortRows,
  type SortKey,
  toCsv,
  toggleSort,
  ZOOM_LEVELS,
} from "@/lib/research/table";

export type Column<T> = ColumnSpec<T> & {
  render?: (row: T) => ReactNode;
  align?: "left" | "right";
  defaultHidden?: boolean;
  /** Direction applied on the first click (numbers usually want "desc"). */
  firstDir?: "asc" | "desc";
  title?: string;
};

export type Preset = { label: string; filters?: Filters; sort?: SortKey[]; search?: string };

type State = { filters: Filters; sort: SortKey[]; search: string; hidden: string[]; order?: string[]; zoom?: number };

type Props<T> = {
  id: string;
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  initialSort?: SortKey[];
  presets?: Preset[];
  /** Footer row(s). `cols` = keys of visible columns, so cells can be aligned. */
  footer?: (ctx: { rows: T[]; all: T[]; filtered: boolean; cols: string[] }) => ReactNode;
  rowClassName?: (row: T) => string;
  empty?: ReactNode;
  compact?: boolean;
  exportName?: string;
};

const inputCls = "rounded border border-slate-300 bg-transparent px-1.5 py-0.5 text-xs dark:border-slate-700";

function FilterInput<T>({ col, rows, value, onChange }: { col: Column<T>; rows: T[]; value?: Filter; onChange: (f: Filter | undefined) => void }) {
  const lbl = `Filter ${col.label}`;
  switch (col.type) {
    case "text": {
      const v = value?.kind === "text" ? value.contains : "";
      return <input aria-label={lbl} className={`${inputCls} w-full min-w-16`} placeholder="contains…" value={v}
        onChange={(e) => onChange({ kind: "text", contains: e.target.value })} />;
    }
    case "number": {
      const v = value?.kind === "number" ? value : { kind: "number" as const, min: null, max: null };
      const set = (k: "min" | "max", s: string) => onChange({ ...v, [k]: s === "" ? null : Number(s) });
      return (
        <div className="flex gap-0.5">
          <input aria-label={`${lbl} minimum`} type="number" step="any" className={`${inputCls} w-14`} placeholder="min" value={v.min ?? ""} onChange={(e) => set("min", e.target.value)} />
          <input aria-label={`${lbl} maximum`} type="number" step="any" className={`${inputCls} w-14`} placeholder="max" value={v.max ?? ""} onChange={(e) => set("max", e.target.value)} />
        </div>
      );
    }
    case "bool": {
      const v = value?.kind === "bool" ? value.is : null;
      return (
        <select aria-label={lbl} className={inputCls} value={v === null ? "" : String(v)}
          onChange={(e) => onChange({ kind: "bool", is: e.target.value === "" ? null : e.target.value === "true" })}>
          <option value="">all</option>
          <option value="true">{col.labels?.true ?? "yes"}</option>
          <option value="false">{col.labels?.false ?? "no"}</option>
        </select>
      );
    }
    case "date": {
      const v = value?.kind === "date" ? value : { kind: "date" as const, from: null, to: null };
      return (
        <div className="flex flex-col gap-0.5">
          <input aria-label={`${lbl} from`} type="date" className={inputCls} value={v.from ?? ""} onChange={(e) => onChange({ ...v, from: e.target.value || null })} />
          <input aria-label={`${lbl} to`} type="date" className={inputCls} value={v.to ?? ""} onChange={(e) => onChange({ ...v, to: e.target.value || null })} />
        </div>
      );
    }
    case "enum": {
      const sel = value?.kind === "enum" ? value.in : [];
      const opts = distinctValues(rows, col);
      const toggle = (o: string) => onChange({ kind: "enum", in: sel.includes(o) ? sel.filter((x) => x !== o) : [...sel, o] });
      return (
        <details className="relative">
          <summary className={`${inputCls} cursor-pointer list-none whitespace-nowrap`} aria-label={lbl}>
            {sel.length ? `${sel.length} selected` : "all"} ▾
          </summary>
          <div className="absolute z-30 mt-1 max-h-60 min-w-36 overflow-auto rounded border border-slate-300 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
            {opts.map((o) => (
              <label key={o} className="flex cursor-pointer items-center gap-1 whitespace-nowrap px-1 py-0.5 text-xs hover:bg-slate-100 dark:hover:bg-slate-800">
                <input type="checkbox" checked={sel.includes(o)} onChange={() => toggle(o)} />
                {col.labels?.[o] ?? (o === "—" ? "(none)" : o)}
              </label>
            ))}
            {sel.length > 0 && (
              <button className="mt-1 w-full text-left text-xs text-blue-600 underline" onClick={() => onChange(undefined)}>clear</button>
            )}
          </div>
        </details>
      );
    }
  }
}

export function DataTable<T>({ id, rows, columns, rowKey, initialSort = [], presets, footer, rowClassName, empty, compact, exportName }: Props<T>) {
  const defaults: State = useMemo(
    () => ({ filters: {}, sort: initialSort, search: "", hidden: columns.filter((c) => c.defaultHidden).map((c) => c.key) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id],
  );
  const [st, setSt] = useState<State>(defaults);
  const [showFilters, setShowFilters] = useState(false);
  const [showCols, setShowCols] = useState(false);
  const storeKey = `table:${id}`;

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storeKey);
      if (raw) setSt({ ...defaults, ...JSON.parse(raw) });
    } catch {}
  }, [storeKey, defaults]);

  const update = (patch: Partial<State>) =>
    setSt((s) => {
      const n = { ...s, ...patch };
      try {
        localStorage.setItem(storeKey, JSON.stringify(n));
      } catch {}
      return n;
    });

  const [dragKey, setDragKey] = useState<string | null>(null);
  const [overKey, setOverKey] = useState<string | null>(null);
  const order = resolveOrder(columns.map((c) => c.key), st.order);
  const byKey = new Map(columns.map((c) => [c.key, c]));
  const orderedCols = order.map((k) => byKey.get(k)!).filter(Boolean);
  const visibleCols = orderedCols.filter((c) => !st.hidden.includes(c.key));
  const zoom = st.zoom ?? 1;
  const zi = ZOOM_LEVELS.indexOf(zoom) === -1 ? ZOOM_LEVELS.indexOf(1) : ZOOM_LEVELS.indexOf(zoom);
  const filtered = useMemo(() => applyFilters(rows, columns, st.filters, st.search), [rows, columns, st.filters, st.search]);
  const sorted = useMemo(() => sortRows(filtered, columns, st.sort), [filtered, columns, st.sort]);
  const nActive = Object.values(st.filters).filter(isActive).length + (st.search.trim() ? 1 : 0);
  const isFiltered = nActive > 0;

  const setFilter = (key: string, f: Filter | undefined) => {
    const next = { ...st.filters };
    if (f && isActive(f)) next[key] = f;
    else delete next[key];
    update({ filters: next });
  };

  const exportCsv = () => {
    const blob = new Blob([toCsv(sorted, visibleCols)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${exportName ?? id}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const btn = "rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800";
  const activePreset = (p: Preset) => JSON.stringify(p.filters ?? {}) === JSON.stringify(st.filters) && (p.search ?? "") === st.search;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {!compact && (
          <input aria-label="Search table" className={`${inputCls} w-40 py-1 text-sm`} placeholder="Search…" value={st.search}
            onChange={(e) => update({ search: e.target.value })} />
        )}
        <button className={`${btn} ${showFilters ? "bg-slate-200 dark:bg-slate-700" : ""}`} onClick={() => setShowFilters((x) => !x)} aria-expanded={showFilters}>
          Filters{nActive ? ` (${nActive})` : ""}
        </button>
        <div className="relative">
          <button className={btn} onClick={() => setShowCols((x) => !x)} aria-expanded={showCols}>Columns</button>
          {showCols && (
            <div className="absolute z-30 mt-1 max-h-80 w-60 overflow-auto rounded border border-slate-300 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
              <div className="px-1 pb-1 text-[10px] text-slate-500">Tick to show. Use ↑↓ (or drag a header) to reorder.</div>
              {orderedCols.map((c, i) => (
                <div key={c.key} className="flex items-center gap-1 px-1 py-0.5 text-xs hover:bg-slate-100 dark:hover:bg-slate-800">
                  <label className="flex flex-1 cursor-pointer items-center gap-1">
                    <input type="checkbox" checked={!st.hidden.includes(c.key)}
                      onChange={() => update({ hidden: st.hidden.includes(c.key) ? st.hidden.filter((k) => k !== c.key) : [...st.hidden, c.key] })} />
                    {c.label || c.key}
                  </label>
                  <button aria-label={`Move ${c.label} earlier`} disabled={i === 0} className="px-1 disabled:opacity-30"
                    onClick={() => update({ order: shift(order, c.key, -1) })}>↑</button>
                  <button aria-label={`Move ${c.label} later`} disabled={i === orderedCols.length - 1} className="px-1 disabled:opacity-30"
                    onClick={() => update({ order: shift(order, c.key, 1) })}>↓</button>
                </div>
              ))}
              <button className="mt-1 w-full border-t border-slate-200 px-1 pt-1 text-left text-xs text-blue-600 underline dark:border-slate-700"
                onClick={() => update({ order: undefined, hidden: defaults.hidden })}>Reset column layout</button>
            </div>
          )}
        </div>
        {(isFiltered || st.sort.length > 0) && (
          <button className={btn} onClick={() => update({ filters: {}, search: "", sort: initialSort })}>Reset</button>
        )}
        {!compact && <button className={btn} onClick={exportCsv}>Export CSV</button>}
        <span className="inline-flex items-center rounded border border-slate-300 text-xs dark:border-slate-700" role="group" aria-label="Table zoom">
          <button className="px-1.5 py-0.5 disabled:opacity-30" aria-label="Zoom out table" disabled={zi <= 0}
            onClick={() => update({ zoom: ZOOM_LEVELS[Math.max(0, zi - 1)] })}>A−</button>
          <button className="border-x border-slate-300 px-1.5 py-0.5 dark:border-slate-700" title="Reset zoom" onClick={() => update({ zoom: 1 })}>
            {Math.round(zoom * 100)}%
          </button>
          <button className="px-1.5 py-0.5 disabled:opacity-30" aria-label="Zoom in table" disabled={zi >= ZOOM_LEVELS.length - 1}
            onClick={() => update({ zoom: ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, zi + 1)] })}>A+</button>
        </span>
        {presets?.map((p) => (
          <button key={p.label} onClick={() => update({ filters: p.filters ?? {}, search: p.search ?? "", sort: p.sort ?? st.sort })}
            className={`rounded-full border px-2 py-0.5 text-xs ${activePreset(p) && isFiltered ? "border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300" : "border-slate-300 dark:border-slate-700"}`}>
            {p.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-500" aria-live="polite">
          {sorted.length === rows.length ? `${rows.length} rows` : `${sorted.length} of ${rows.length} rows`}
          {st.sort.length > 1 && " · multi-sort"}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="tbl num w-full" style={{ fontSize: `${0.875 * zoom}rem` }}>
          <thead>
            <tr>
              {visibleCols.map((c) => {
                const si = st.sort.findIndex((s) => s.key === c.key);
                const s = si >= 0 ? st.sort[si] : null;
                const sortable = c.sortable !== false;
                return (
                  <th key={c.key} title={c.title ?? "Drag to move this column"}
                    className={`${c.align === "right" ? "text-right" : ""} cursor-grab select-none ${dragKey === c.key ? "opacity-40" : ""} ${overKey === c.key && dragKey && dragKey !== c.key ? "border-l-2 border-blue-500" : ""}`}
                    aria-sort={s ? (s.dir === "asc" ? "ascending" : "descending") : "none"}
                    draggable
                    onDragStart={(e) => { setDragKey(c.key); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", c.key); }}
                    onDragOver={(e) => { if (dragKey) { e.preventDefault(); setOverKey(c.key); } }}
                    onDragLeave={() => setOverKey((k) => (k === c.key ? null : k))}
                    onDrop={(e) => { e.preventDefault(); if (dragKey) update({ order: moveBefore(order, dragKey, c.key) }); setDragKey(null); setOverKey(null); }}
                    onDragEnd={() => { setDragKey(null); setOverKey(null); }}>
                    {sortable ? (
                      <button className={`inline-flex items-center gap-0.5 uppercase hover:text-slate-900 dark:hover:text-white ${s ? "text-slate-900 dark:text-white" : ""}`}
                        onClick={(e) => update({ sort: toggleSort(st.sort, c.key, e.shiftKey, c.firstDir ?? (c.type === "number" ? "desc" : "asc")) })}
                        title="Click to sort; Shift-click to add a secondary sort">
                        {c.label}
                        <span aria-hidden className="text-[10px]">
                          {s ? (s.dir === "asc" ? "▲" : "▼") : "↕"}
                          {s && st.sort.length > 1 ? si + 1 : ""}
                        </span>
                      </button>
                    ) : c.label}
                  </th>
                );
              })}
            </tr>
            {showFilters && (
              <tr className="bg-slate-50 dark:bg-slate-800/40">
                {visibleCols.map((c) => (
                  <th key={c.key} className="align-top normal-case">
                    {c.filterable !== false && (
                      <FilterInput col={c} rows={rows} value={st.filters[c.key]} onChange={(f) => setFilter(c.key, f)} />
                    )}
                  </th>
                ))}
              </tr>
            )}
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={visibleCols.length} className="py-4 text-center text-sm text-slate-500">
                  {rows.length === 0 ? (empty ?? "No data.") : "No rows match the current filters."}
                </td>
              </tr>
            ) : (
              sorted.map((r) => (
                <tr key={rowKey(r)} className={`hover:bg-slate-50 dark:hover:bg-slate-800/50 ${rowClassName?.(r) ?? ""}`}>
                  {visibleCols.map((c) => (
                    <td key={c.key} className={c.align === "right" ? "text-right" : ""}>
                      {c.render ? c.render(r) : String(c.get(r) ?? "—")}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
          {footer && sorted.length > 0 && <tfoot>{footer({ rows: sorted, all: rows, filtered: isFiltered, cols: visibleCols.map((c) => c.key) })}</tfoot>}
        </table>
      </div>
    </div>
  );
}
