export function money(v: number | null | undefined, ccy: string, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: ccy, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
}

export function pct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function ratioLabel(r: number): string {
  return `${(r * 100).toFixed(1).replace(/\.0$/, "")}%`;
}

export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "";
  return v > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

export function fmtTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}
