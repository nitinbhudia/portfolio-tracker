export type RangeKey = "1M" | "3M" | "6M" | "YTD" | "1Y" | "2Y" | "All";

// Ranges are calendar months, so they work the same for daily, weekly and monthly bars.
const RANGE_MONTHS: Record<Exclude<RangeKey, "YTD" | "All">, number> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "2Y": 24 };

export function rangeFrom(dates: string[], r: RangeKey): number {
  if (r === "All") return 0;
  if (r === "YTD") {
    const y = dates[dates.length - 1].slice(0, 4);
    const i = dates.findIndex((d) => d.startsWith(y));
    return Math.max(0, i - 1);
  }
  const last = new Date(`${dates[dates.length - 1]}T00:00:00Z`);
  last.setUTCMonth(last.getUTCMonth() - RANGE_MONTHS[r]);
  const cutoff = last.toISOString().slice(0, 10);
  const i = dates.findIndex((d) => d > cutoff);
  return Math.max(0, Math.min(i === -1 ? 0 : i, dates.length - 3));
}
