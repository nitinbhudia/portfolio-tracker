"use client";

import { useMemo, useRef, useState } from "react";

import type { Quadrant, RrgPoint, SectorRow } from "@/lib/research/api";
import { num } from "@/lib/research/format";
import { axisDomain, headingDeg, lastN, QUADRANT_FILL, QUADRANT_LABEL } from "@/lib/research/rrg";

import { useTheme } from "./Shell";

// 20 distinguishable colours (Europe has 19 sectors)
const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#db2777", "#4f46e5", "#65a30d",
  "#0d9488", "#b45309", "#7c3aed", "#be123c", "#0369a1", "#4d7c0f", "#a21caf", "#c2410c", "#0f766e", "#6d28d9"];
export const sectorColor = (i: number) => PALETTE[i % PALETTE.length];

type Props = {
  rows: SectorRow[];
  trail: number;
  hidden?: Set<string>;
  onSelect?: (ticker: string) => void;
  colors?: Record<string, string>;
  height?: number;
  benchmark?: string;
};

const W = 800;
const M = { l: 48, r: 16, t: 16, b: 40 };

function ticks(lo: number, hi: number): number[] {
  const span = hi - lo;
  const step = span > 16 ? 4 : span > 8 ? 2 : span > 4 ? 1 : 0.5;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}

/** Relative Rotation Graph (RRG-inspired approximation): RS-Ratio on x, RS-Momentum on y, 100/100 = benchmark. */
export function RrgChart({ rows, trail, hidden, onSelect, colors, height = 560, benchmark = "SPY" }: Props) {
  const { dark } = useTheme();
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ ticker: string; x: number; y: number } | null>(null);
  const H = height;
  const visible = rows.filter((r) => r.status === "ok" && r.trail && !hidden?.has(r.ticker));
  const pts = useMemo(() => visible.flatMap((r) => lastN(r.trail ?? [], trail)), [visible, trail]);
  const dom = axisDomain(pts);
  const sx = (v: number) => M.l + ((v - dom.x[0]) / (dom.x[1] - dom.x[0])) * (W - M.l - M.r);
  const sy = (v: number) => M.t + ((dom.y[1] - v) / (dom.y[1] - dom.y[0])) * (H - M.t - M.b);
  const cx = sx(100), cy = sy(100);
  const fg = dark ? "#cbd5e1" : "#334155";
  const grid = dark ? "#1e293b" : "#e2e8f0";
  const quads: [Quadrant, number, number, number, number][] = [
    ["improving", M.l, M.t, cx, cy], ["leading", cx, M.t, W - M.r, cy],
    ["lagging", M.l, cy, cx, H - M.b], ["weakening", cx, cy, W - M.r, H - M.b],
  ];
  const corner: Record<Quadrant, [number, number, "start" | "end"]> = {
    improving: [M.l + 8, M.t + 18, "start"], leading: [W - M.r - 8, M.t + 18, "end"],
    lagging: [M.l + 8, H - M.b - 8, "start"], weakening: [W - M.r - 8, H - M.b - 8, "end"],
  };
  const hovered = hover ? rows.find((r) => r.ticker === hover.ticker) : null;

  const show = (r: SectorRow, p: RrgPoint) => {
    const box = wrap.current?.getBoundingClientRect();
    const scale = box ? box.width / W : 1;
    setHover({ ticker: r.ticker, x: sx(p.ratio) * scale, y: sy(p.momentum) * scale });
  };

  return (
    <div ref={wrap} className="relative w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full select-none" role="img"
        aria-label={`Relative Rotation Graph against ${benchmark}: RS-Ratio horizontally, RS-Momentum vertically, ${visible.length} sectors`}>
        {quads.map(([q, x0, y0, x1, y1]) => (
          <rect key={q} x={x0} y={y0} width={Math.max(0, x1 - x0)} height={Math.max(0, y1 - y0)} fill={QUADRANT_FILL[q]} />
        ))}
        {ticks(dom.x[0], dom.x[1]).map((v) => (
          <g key={`x${v}`}>
            <line x1={sx(v)} x2={sx(v)} y1={M.t} y2={H - M.b} stroke={grid} strokeWidth={v === 100 ? 0 : 1} />
            <text x={sx(v)} y={H - M.b + 16} fontSize={11} textAnchor="middle" fill={fg}>{v}</text>
          </g>
        ))}
        {ticks(dom.y[0], dom.y[1]).map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} stroke={grid} strokeWidth={v === 100 ? 0 : 1} />
            <text x={M.l - 6} y={sy(v) + 4} fontSize={11} textAnchor="end" fill={fg}>{v}</text>
          </g>
        ))}
        <line x1={cx} x2={cx} y1={M.t} y2={H - M.b} stroke={fg} strokeWidth={1.2} />
        <line x1={M.l} x2={W - M.r} y1={cy} y2={cy} stroke={fg} strokeWidth={1.2} />
        {(Object.keys(corner) as Quadrant[]).map((q) => (
          <text key={q} x={corner[q][0]} y={corner[q][1]} textAnchor={corner[q][2]} fontSize={14} fontWeight={700} fill={fg} opacity={0.55}>
            {QUADRANT_LABEL[q].toUpperCase()}
          </text>
        ))}
        <text x={(M.l + W - M.r) / 2} y={H - 6} fontSize={12} textAnchor="middle" fill={fg}>RS-Ratio (relative strength vs {benchmark}) →</text>
        <text x={14} y={(M.t + H - M.b) / 2} fontSize={12} textAnchor="middle" fill={fg} transform={`rotate(-90 14 ${(M.t + H - M.b) / 2})`}>
          RS-Momentum →
        </text>
        <circle cx={cx} cy={cy} r={3} fill={fg}><title>{benchmark} (100, 100)</title></circle>
        {visible.map((r) => {
          const tr = lastN(r.trail ?? [], trail);
          if (!tr.length) return null;
          const color = colors?.[r.ticker] ?? "#2563eb";
          const last = tr[tr.length - 1];
          const prev = tr.length > 1 ? tr[tr.length - 2] : null;
          const ang = prev ? headingDeg({ x: sx(prev.ratio), y: sy(prev.momentum) }, { x: sx(last.ratio), y: sy(last.momentum) }) : null;
          const active = hover?.ticker === r.ticker;
          const label = `${r.ticker} ${r.sector}: ${QUADRANT_LABEL[last.quadrant]}, RS-Ratio ${num(last.ratio, 2)}, RS-Momentum ${num(last.momentum, 2)}`;
          return (
            <g key={r.ticker} role="button" tabIndex={0} aria-label={label} className="cursor-pointer focus:outline-none"
              opacity={hover && !active ? 0.35 : 1}
              onMouseEnter={() => show(r, last)} onMouseLeave={() => setHover(null)} onFocus={() => show(r, last)} onBlur={() => setHover(null)}
              onClick={() => onSelect?.(r.ticker)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect?.(r.ticker)}>
              <polyline points={tr.map((p) => `${sx(p.ratio)},${sy(p.momentum)}`).join(" ")} fill="none" stroke={color}
                strokeWidth={active ? 2.5 : 1.6} strokeLinejoin="round" />
              {tr.slice(0, -1).map((p, i) => (
                <circle key={p.date} cx={sx(p.ratio)} cy={sy(p.momentum)} r={2} fill={color} opacity={0.3 + (0.6 * i) / tr.length} />
              ))}
              {ang !== null && (
                <polygon points="0,-5 10,0 0,5" fill={color} transform={`translate(${sx(last.ratio)},${sy(last.momentum)}) rotate(${ang}) translate(2,0)`} />
              )}
              <circle cx={sx(last.ratio)} cy={sy(last.momentum)} r={active ? 7 : 5.5} fill={color} stroke={dark ? "#0f172a" : "#fff"} strokeWidth={1.5} />
              <text x={sx(last.ratio) + 9} y={sy(last.momentum) - 8} fontSize={12} fontWeight={700} fill={color}>{r.ticker}</text>
              <circle cx={sx(last.ratio)} cy={sy(last.momentum)} r={14} fill="transparent" />
            </g>
          );
        })}
      </svg>
      {hovered && hover && hovered.trail && (
        <div className="pointer-events-none absolute z-10 w-56 rounded-md border border-slate-200 bg-white p-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900"
          style={{ left: Math.min(hover.x + 12, (wrap.current?.clientWidth ?? 400) - 230), top: Math.max(0, hover.y - 10) }}>
          <div className="font-semibold">{hovered.sector} · {hovered.ticker}</div>
          <div className="text-slate-500">{hovered.etf_name}</div>
          {(() => {
            const p = hovered.trail[hovered.trail.length - 1];
            return (
              <div className="mt-1 grid grid-cols-2 gap-x-2">
                <span>Quadrant</span><b>{QUADRANT_LABEL[p.quadrant]}</b>
                <span>RS-Ratio</span><b className="num">{num(p.ratio, 2)}</b>
                <span>RS-Momentum</span><b className="num">{num(p.momentum, 2)}</b>
                <span>Score</span><b className="num">{num(hovered.score?.total, 1)}</b>
                <span>As of</span><span>{p.date}</span>
              </div>
            );
          })()}
          <div className="mt-1 text-slate-500">Click for sector details</div>
        </div>
      )}
    </div>
  );
}
