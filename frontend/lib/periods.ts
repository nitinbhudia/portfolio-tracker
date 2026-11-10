import { inRange, resolve, spanMonths, type Range } from "./range";

type Month = { month: string; sales: number; gain_usd: number; wins: number };

/** Realised gain bars for a range: months when the range is up to 2 years, calendar years otherwise. */
export function gainBars(months: Month[], range: Range, end: string, firstMonth?: string) {
  const r = resolve(range, end);
  const start = r.start ?? (firstMonth ? `${firstMonth}-01` : months[0] ? `${months[0].month}-01` : end);
  const ms = months.filter((m) => inRange(`${m.month}-15`, { start: start.slice(0, 7) + "-01", end: r.end }));
  const monthly = spanMonths(start, r.end) <= 24;
  const buckets = new Map<string, { gain: number; sales: number; wins: number }>();
  if (monthly) {
    // every month in the range, including months without sales
    let y = Number(start.slice(0, 4)), m = Number(start.slice(5, 7));
    const ey = Number(r.end.slice(0, 4)), em = Number(r.end.slice(5, 7));
    while (y < ey || (y === ey && m <= em)) {
      buckets.set(`${y}-${String(m).padStart(2, "0")}`, { gain: 0, sales: 0, wins: 0 });
      m += 1;
      if (m > 12) { m = 1; y += 1; }
    }
  } else {
    for (let y = Number(start.slice(0, 4)); y <= Number(r.end.slice(0, 4)); y++) buckets.set(String(y), { gain: 0, sales: 0, wins: 0 });
  }
  for (const x of ms) {
    const k = monthly ? x.month : x.month.slice(0, 4);
    const b = buckets.get(k);
    if (b) { b.gain += x.gain_usd; b.sales += x.sales; b.wins += x.wins; }
  }
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return {
    monthly,
    bars: [...buckets.entries()].map(([k, b]) => ({
      key: k, value: b.gain, sales: b.sales, wins: b.wins,
      label: monthly ? `${MON[Number(k.slice(5, 7)) - 1]}${k.slice(5, 7) === "01" || buckets.size <= 12 ? ` ${k.slice(2, 4)}` : ""}` : k,
    })),
  };
}
