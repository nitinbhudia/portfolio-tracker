/** Time ranges for every chart. Presets end on the latest date the app has (the valuation date). */
export type RangeKey = "1M" | "3M" | "6M" | "YTD" | "1Y" | "3Y" | "5Y" | "ALL" | "CUSTOM";
export type Range = { key: RangeKey; from?: string; to?: string };
export const PRESETS: RangeKey[] = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "ALL"];

const iso = (d: Date) => d.toISOString().slice(0, 10);

function minusMonths(end: string, months: number): string {
  const d = new Date(`${end}T00:00:00Z`);
  const day = d.getUTCDate();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - months);
  const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
  d.setUTCDate(Math.min(day, last));
  return iso(d);
}

/** [start, end] as YYYY-MM-DD; start null = from the beginning. */
export function resolve(r: Range, end: string): { start: string | null; end: string } {
  const to = r.key === "CUSTOM" && r.to ? r.to : end;
  switch (r.key) {
    case "1M": return { start: minusMonths(to, 1), end: to };
    case "3M": return { start: minusMonths(to, 3), end: to };
    case "6M": return { start: minusMonths(to, 6), end: to };
    case "YTD": return { start: `${to.slice(0, 4)}-01-01`, end: to };
    case "1Y": return { start: minusMonths(to, 12), end: to };
    case "3Y": return { start: minusMonths(to, 36), end: to };
    case "5Y": return { start: minusMonths(to, 60), end: to };
    case "CUSTOM": return { start: r.from || null, end: to };
    default: return { start: null, end: to };
  }
}

export function inRange(date: string, r: { start: string | null; end: string }): boolean {
  return (!r.start || date >= r.start) && date <= r.end;
}

/** Months between two dates (for choosing monthly vs yearly bars). */
export function spanMonths(start: string, end: string): number {
  return (Number(end.slice(0, 4)) - Number(start.slice(0, 4))) * 12 + Number(end.slice(5, 7)) - Number(start.slice(5, 7)) + 1;
}

export function label(r: Range): string {
  if (r.key === "ALL") return "all time";
  if (r.key === "YTD") return "this year";
  if (r.key === "CUSTOM") return `${r.from ?? "start"} → ${r.to ?? "latest"}`;
  return `last ${r.key.replace("M", " months").replace("Y", " years").replace(/^1 months$/, "1 month").replace(/^1 years$/, "1 year")}`;
}
