import type { SetupCatalogItem, SetupItem, SetupRule, SetupStatus } from "./api";

export const STATUS_LABEL: Record<SetupStatus, string> = {
  triggered: "Triggered",
  not_triggered: "Not triggered",
  insufficient_data: "Not enough history",
  not_applicable: "Not applicable",
};

/** Names of the triggered setups, in catalog order, joined so a text filter can match one. */
export function triggeredNames(triggered: string[], catalog: SetupCatalogItem[]): string {
  const byId = new Map(catalog.map((c) => [c.id, c.name]));
  return catalog.filter((c) => triggered.includes(c.id)).map((c) => byId.get(c.id)).join(" · ");
}

/** Count of rows per triggered setup id. */
export function countBySetup(rows: { triggered: string[] }[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of rows) for (const id of r.triggered) out[id] = (out[id] ?? 0) + 1;
  return out;
}

/** Rules that failed, so "why not?" can be answered in one line. */
export function failedRules(s: SetupItem): SetupRule[] {
  return s.rules.filter((r) => !r.result);
}

/** Format a rule operand: big numbers get thousands separators, small ones 4 significant digits. */
export function fmtOperand(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1000) return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
  return Number(v.toPrecision(4)).toString();
}
