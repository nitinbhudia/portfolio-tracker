"use client";

import { useRef, useState } from "react";

import { gainFill, squarify } from "@/lib/treemap";

import { Tooltip, type Tip, useWidth } from "./charts";

export type TreeNode = { key: string; label: string; value: number; gainPct: number | null; sub?: string; lines: [string, string][]; drill: boolean };

/** Clickable treemap: area = value, colour = gain % (blue gain, red loss, grey ≈ 0). Tiles with `drill` open on click/Enter. */
export function Treemap({ nodes, onPick, label, height = 440 }: { nodes: TreeNode[]; onPick: (key: string) => void; label: string; height?: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const W = useWidth(wrap, 900);
  const H = W < 600 ? Math.min(height, 360) : height;
  const [tip, setTip] = useState<Tip>(null);
  const [hover, setHover] = useState<string | null>(null);
  const shown = nodes.filter((n) => n.value > 0);
  const rects = squarify(shown.map((n) => n.value), { x: 0, y: 0, w: W, h: H });
  return (
    <div ref={wrap} className="relative" onPointerLeave={() => { setTip(null); setHover(null); }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block" role="group" aria-label={label}>
        {shown.map((n, i) => {
          const r = rects[i];
          const { fill, strong } = gainFill(n.gainPct);
          const ink = strong ? "#ffffff" : "var(--viz-ink)";
          const show = () => { setHover(n.key); setTip({ x: r.x + r.w / 2, y: r.y + Math.min(24, r.h / 2), lines: [[n.label, ""], ...n.lines] }); };
          const fits = r.w > 56 && r.h > 22, more = r.w > 80 && r.h > 52;
          const maxChars = Math.floor((r.w - 12) / 6.6);
          const name = n.label.length > maxChars ? n.label.slice(0, Math.max(1, maxChars - 1)) + "…" : n.label;
          return (
            <g key={n.key} tabIndex={0} aria-label={`${n.label}. ${n.lines.map(([a, b]) => `${a} ${b}`).join(", ")}${n.drill ? ". Press Enter to open." : ""}`}
              role={n.drill ? "button" : "img"} style={{ cursor: n.drill ? "pointer" : "default" }}
              onPointerMove={show} onFocus={show} onBlur={() => setTip(null)}
              onClick={() => n.drill && onPick(n.key)}
              onKeyDown={(e) => { if (n.drill && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onPick(n.key); } }}>
              <rect x={r.x + 1} y={r.y + 1} width={Math.max(0, r.w - 2)} height={Math.max(0, r.h - 2)} rx={4} fill={fill}
                stroke={hover === n.key ? "var(--viz-ink)" : "none"} strokeWidth={hover === n.key ? 1.5 : 0} />
              <clipPath id={`tm-${i}`}><rect x={r.x + 1} y={r.y + 1} width={Math.max(0, r.w - 6)} height={Math.max(0, r.h - 2)} /></clipPath>
              {fits && <text clipPath={`url(#tm-${i})`} x={r.x + 7} y={r.y + 17} fontSize={12} fontWeight={600} fill={ink} pointerEvents="none">{name}</text>}
              {fits && more && n.sub && <text clipPath={`url(#tm-${i})`} x={r.x + 7} y={r.y + 33} fontSize={11} fill={ink} opacity={0.9} pointerEvents="none" className="num">{n.sub}</text>}
            </g>
          );
        })}
      </svg>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>Size = value today · colour = gain/loss %</span>
        <span className="flex items-center gap-1">−50%
          <span className="inline-block h-2.5 w-28 rounded-sm" style={{ background: "linear-gradient(90deg, color-mix(in oklab, var(--viz-neg) 85%, var(--viz-mid)), var(--viz-mid), color-mix(in oklab, var(--viz-1) 85%, var(--viz-mid)))" }} />
          +50%</span>
        <span>Click a tile to open it</span>
      </div>
      <Tooltip tip={tip} />
    </div>
  );
}

/** "All › Sector › Stock" — every crumb but the last takes you back up. */
export function Crumbs({ items, onGo }: { items: string[]; onGo: (depth: number) => void }) {
  return (
    <nav aria-label="Drill-down level" className="flex flex-wrap items-center gap-1 text-sm">
      {items.map((it, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <span className="text-slate-400">›</span>}
          {i < items.length - 1
            ? <button className="text-blue-700 underline dark:text-blue-300" onClick={() => onGo(i)}>{it}</button>
            : <b aria-current="page">{it}</b>}
        </span>
      ))}
    </nav>
  );
}
