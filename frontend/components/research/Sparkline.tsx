import { pct } from "@/lib/research/format";

type Props = {
  values: number[] | undefined | null;
  change?: number | null;
  label: string;
  start?: string | null;
  width?: number;
  height?: number;
  showChange?: boolean;
};

/** Tiny inline price chart. Green if the period ended higher, red if lower; dashed line = starting price. */
export function Sparkline({ values, change, label, start, width = 84, height = 24, showChange = true }: Props) {
  if (!values || values.length < 2) return <span className="text-xs text-slate-400">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 2;
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - pad * 2);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  const color = up ? "#10b981" : "#f43f5e";
  const desc = `${label}${start ? ` since ${start}` : ""}: ${pct(change ?? null)} (from ${values[0].toFixed(2)} to ${values[values.length - 1].toFixed(2)})`;
  return (
    <span className="inline-flex items-center gap-1 align-middle" title={desc}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={desc}>
        <line x1={pad} x2={width - pad} y1={y(values[0])} y2={y(values[0])} stroke="#94a3b8" strokeWidth="0.75" strokeDasharray="2 2" />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="1.8" fill={color} />
      </svg>
      {showChange && <span className={`text-[11px] ${up ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>{pct(change ?? null, 1)}</span>}
    </span>
  );
}

export type Spark = {
  m3: number[];
  ytd: number[];
  m3_change_pct: number | null;
  ytd_change_pct: number | null;
  m3_start: string | null;
  ytd_start: string | null;
};
