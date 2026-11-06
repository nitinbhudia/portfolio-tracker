/**
 * Pure filtering/sorting logic for DataTable (unit-tested in lib/table.test.ts).
 * Nulls/missing values always sort last, in both directions.
 */

export type ColType = "text" | "number" | "enum" | "bool" | "date";
export type Cell = string | number | boolean | null | undefined;

export type ColumnSpec<T> = {
  key: string;
  label: string;
  type: ColType;
  get: (row: T) => Cell;
  /** Display labels for enum/bool values (e.g. { true: "Yes" }). */
  labels?: Record<string, string>;
  filterable?: boolean;
  sortable?: boolean;
};

export type Filter =
  | { kind: "text"; contains: string }
  | { kind: "number"; min?: number | null; max?: number | null }
  | { kind: "enum"; in: string[] }
  | { kind: "bool"; is: boolean | null }
  | { kind: "date"; from?: string | null; to?: string | null };

export type Filters = Record<string, Filter>;
export type SortKey = { key: string; dir: "asc" | "desc" };

const isMissing = (v: Cell) => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v)) || v === "";

export function enumKey(v: Cell): string {
  return isMissing(v) ? "—" : String(v);
}

export function isActive(f: Filter | undefined): boolean {
  if (!f) return false;
  switch (f.kind) {
    case "text": return f.contains.trim() !== "";
    case "number": return (f.min ?? null) !== null || (f.max ?? null) !== null;
    case "enum": return f.in.length > 0;
    case "bool": return f.is !== null;
    case "date": return !!f.from || !!f.to;
  }
}

export function matches(v: Cell, f: Filter): boolean {
  if (!isActive(f)) return true;
  switch (f.kind) {
    case "text":
      return !isMissing(v) && String(v).toLowerCase().includes(f.contains.trim().toLowerCase());
    case "number": {
      if (isMissing(v) || typeof v !== "number") return false;
      if (f.min !== null && f.min !== undefined && v < f.min) return false;
      if (f.max !== null && f.max !== undefined && v > f.max) return false;
      return true;
    }
    case "enum":
      return f.in.includes(enumKey(v));
    case "bool":
      return v === f.is;
    case "date": {
      if (isMissing(v)) return false;
      const s = String(v).slice(0, 10);
      if (f.from && s < f.from) return false;
      if (f.to && s > f.to) return false;
      return true;
    }
  }
}

export function applyFilters<T>(rows: T[], cols: ColumnSpec<T>[], filters: Filters, search = ""): T[] {
  const q = search.trim().toLowerCase();
  const active = cols.filter((c) => isActive(filters[c.key]));
  return rows.filter((r) => {
    for (const c of active) if (!matches(c.get(r), filters[c.key])) return false;
    if (!q) return true;
    return cols.some((c) => {
      if (c.type !== "text" && c.type !== "enum") return false;
      const v = c.get(r);
      if (isMissing(v)) return false;
      const shown = c.labels?.[String(v)] ?? String(v);
      return shown.toLowerCase().includes(q) || String(v).toLowerCase().includes(q);
    });
  });
}

function compare(a: Cell, b: Cell, type: ColType): number {
  if (type === "number") return (a as number) - (b as number);
  if (type === "bool") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function sortRows<T>(rows: T[], cols: ColumnSpec<T>[], sort: SortKey[]): T[] {
  if (!sort.length) return rows;
  const byKey = new Map(cols.map((c) => [c.key, c]));
  const keys = sort.filter((s) => byKey.has(s.key));
  // Stable: decorate with original index.
  return rows
    .map((r, i) => ({ r, i }))
    .sort((x, y) => {
      for (const s of keys) {
        const c = byKey.get(s.key)!;
        const a = c.get(x.r), b = c.get(y.r);
        const ma = isMissing(a), mb = isMissing(b);
        if (ma && mb) continue;
        if (ma) return 1; // missing last regardless of direction
        if (mb) return -1;
        const d = compare(a, b, c.type);
        if (d !== 0) return s.dir === "asc" ? d : -d;
      }
      return x.i - y.i;
    })
    .map((x) => x.r);
}

/** Click: cycle asc -> desc -> off on that column (single sort). Shift-click: add/cycle within a multi-sort. */
export function toggleSort(sort: SortKey[], key: string, multi: boolean, firstDir: "asc" | "desc" = "asc"): SortKey[] {
  const cur = sort.find((s) => s.key === key);
  const second = firstDir === "asc" ? "desc" : "asc";
  const next: SortKey | null = !cur ? { key, dir: firstDir } : cur.dir === firstDir ? { key, dir: second } : null;
  if (!multi) return next ? [next] : [];
  const rest = sort.filter((s) => s.key !== key);
  if (!next) return rest;
  return cur ? sort.map((s) => (s.key === key ? next : s)) : [...rest, next];
}

export function distinctValues<T>(rows: T[], col: ColumnSpec<T>): string[] {
  const set = new Set(rows.map((r) => enumKey(col.get(r))));
  return [...set].sort((a, b) => (a === "—" ? 1 : b === "—" ? -1 : a.localeCompare(b, undefined, { numeric: true })));
}

export function toCsv<T>(rows: T[], cols: ColumnSpec<T>[]): string {
  const esc = (v: Cell) => {
    if (isMissing(v)) return "";
    const s = String(v);
    const safe = /^[=+\-@]/.test(s) && Number.isNaN(Number(s)) ? `'${s}` : s; // guard against spreadsheet formula injection
    return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };
  return [cols.map((c) => esc(c.label)).join(","), ...rows.map((r) => cols.map((c) => esc(c.get(r))).join(","))].join("\n");
}

/** Resolve the display order: saved order first (dropping unknown keys), then any new columns in their default position. */
export function resolveOrder(defaultKeys: string[], saved: string[] | undefined): string[] {
  if (!saved?.length) return defaultKeys;
  const known = saved.filter((k) => defaultKeys.includes(k));
  const missing = defaultKeys.filter((k) => !known.includes(k));
  const out = [...known];
  for (const k of missing) {
    const i = defaultKeys.indexOf(k);
    const prev = defaultKeys.slice(0, i).reverse().find((p) => out.includes(p));
    out.splice(prev ? out.indexOf(prev) + 1 : 0, 0, k);
  }
  return out;
}

/** Move `key` so it sits at the position currently held by `target` (drag-and-drop semantics). */
export function moveBefore(order: string[], key: string, target: string): string[] {
  if (key === target || !order.includes(key) || !order.includes(target)) return order;
  const from = order.indexOf(key);
  const to = order.indexOf(target);
  const out = order.filter((k) => k !== key);
  out.splice(to, 0, key);
  return from === to ? order : out;
}

/** Move `key` one step left (-1) or right (+1). */
export function shift(order: string[], key: string, delta: -1 | 1): string[] {
  const i = order.indexOf(key);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= order.length) return order;
  const out = [...order];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

export const ZOOM_LEVELS = [0.75, 0.85, 1, 1.15, 1.3, 1.5];
