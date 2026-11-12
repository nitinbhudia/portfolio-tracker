import type { Quadrant, RrgPoint } from "./api";

export const QUADRANT_LABEL: Record<Quadrant, string> = { leading: "Leading", weakening: "Weakening", lagging: "Lagging", improving: "Improving" };
export const QUADRANT_FILL: Record<Quadrant, string> = {
  leading: "rgba(16,185,129,0.10)", weakening: "rgba(234,179,8,0.12)", lagging: "rgba(244,63,94,0.10)", improving: "rgba(59,130,246,0.10)",
};
export const QUADRANT_TEXT: Record<Quadrant, string> = {
  leading: "text-emerald-700 dark:text-emerald-300", weakening: "text-amber-700 dark:text-amber-300",
  lagging: "text-rose-700 dark:text-rose-300", improving: "text-blue-700 dark:text-blue-300",
};
export const QUADRANT_BADGE: Record<Quadrant, string> = {
  leading: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200",
  weakening: "bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200",
  lagging: "bg-rose-100 text-rose-800 dark:bg-rose-900/60 dark:text-rose-200",
  improving: "bg-blue-100 text-blue-800 dark:bg-blue-900/60 dark:text-blue-200",
};

/** Symmetric axis range around 100 that fits every point, with a little padding and a minimum half-width. */
export function axisDomain(points: { ratio: number; momentum: number }[], minHalf = 2, pad = 0.12): { x: [number, number]; y: [number, number] } {
  let hx = minHalf, hy = minHalf;
  for (const p of points) {
    hx = Math.max(hx, Math.abs(p.ratio - 100));
    hy = Math.max(hy, Math.abs(p.momentum - 100));
  }
  hx *= 1 + pad;
  hy *= 1 + pad;
  return { x: [100 - hx, 100 + hx], y: [100 - hy, 100 + hy] };
}

/** Last `n` points of a trail (the trail from the API holds up to 20). */
export const lastN = (trail: RrgPoint[], n: number) => trail.slice(Math.max(0, trail.length - n));

/** Angle (degrees, SVG coordinates) of the final step of a trail, for the direction arrow. */
export function headingDeg(a: { x: number; y: number }, b: { x: number; y: number }): number | null {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (Math.abs(dx) < 1e-9 && Math.abs(dy) < 1e-9) return null;
  return (Math.atan2(dy, dx) * 180) / Math.PI;
}

/** Plain-language reading of the three separate measurements. */
export function describe(absTrend: string | null | undefined, rel20: number | null | undefined, q: Quadrant | undefined): string {
  const abs = absTrend === "up" ? "rising in absolute terms" : absTrend === "down" ? "falling in absolute terms" : "mixed in absolute terms";
  const rel = rel20 == null ? "relative performance unknown" : rel20 >= 0 ? "outperforming the benchmark over 20 days" : "underperforming the benchmark over 20 days";
  const mom = !q ? "" : q === "leading" || q === "improving" ? "relative momentum improving" : "relative momentum deteriorating";
  return [abs, rel, mom].filter(Boolean).join(", ");
}
