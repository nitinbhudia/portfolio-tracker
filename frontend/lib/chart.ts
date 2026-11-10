/** Round axis ticks: 0 included, 3–6 steps of 1/2/2.5/5 × 10^n covering [min, max]. */
export function niceTicks(min: number, max: number, target = 5): number[] {
  const lo = Math.min(0, min), hi = Math.max(0, max);
  if (hi === lo) return [0];
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  if (out[out.length - 1] < hi) out.push(out[out.length - 1] + step);
  return out;
}

/** Axis label: in full under 10,000, compact (12K, 1.5M) from there; one style per axis. */
export function axisLabel(v: number, compact: boolean): string {
  if (!compact) return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function useCompact(ticks: number[]): boolean {
  return Math.max(...ticks.map(Math.abs)) >= 10_000;
}
