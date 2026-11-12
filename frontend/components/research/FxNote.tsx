import type { FxUsed } from "@/lib/research/api";

export function FxNote({ rates, base }: { rates: FxUsed[]; base: string }) {
  if (!rates.length) return <p className="text-xs text-slate-500">All amounts in {base}; no FX conversion needed.</p>;
  return (
    <p className="text-xs text-slate-500">
      Totals in <b>{base}</b> using FX:{" "}
      {rates.map((r, i) => (
        <span key={r.pair + r.date}>
          {i > 0 && " · "}
          {r.pair} {r.rate.toFixed(4)} ({r.date}
          {r.is_synthetic ? ", synthetic" : ""}, {r.source})
        </span>
      ))}
    </p>
  );
}
