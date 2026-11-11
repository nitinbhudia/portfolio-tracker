"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { axisLabel, niceTicks, useCompact } from "@/lib/chart";

export type Tip = { x: number; y: number; lines: [string, string][] } | null;

export function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div role="tooltip" className="pointer-events-none absolute z-10 min-w-36 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs shadow-md dark:border-slate-700 dark:bg-slate-900"
      style={{ left: tip.x, top: tip.y, transform: "translate(-50%, calc(-100% - 8px))" }}>
      {tip.lines.map(([label, value], i) => (
        <div key={i} className={i === 0 ? "mb-0.5 text-slate-500" : "flex justify-between gap-3"}>
          {i === 0 ? label : <><span className="text-slate-500">{label}</span><b className="num">{value}</b></>}
        </div>
      ))}
    </div>
  );
}

/** Real pixel width of the container, so text and marks keep their size at any width (no SVG scaling). */
export function useWidth(ref: React.RefObject<HTMLDivElement | null>, initial = 640): number {
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

const PAD = { l: 52, r: 12, t: 12, b: 26 };

/** Columns from a zero baseline; gains in blue, losses in red (polarity), 4px rounded data-end. */
export function Columns({ data, height = 220, fmt, label, onPick }: {
  data: { key: string; label: string; value: number; lines?: [string, string][] }[];
  height?: number; fmt: (v: number) => string; label: string;
  /** Makes each column a button (click or Enter) — for drill-down. */
  onPick?: (key: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const W = useWidth(wrap);
  const [tip, setTip] = useState<Tip>(null);
  const [hover, setHover] = useState<string | null>(null);
  const ticks = useMemo(() => niceTicks(Math.min(0, ...data.map((d) => d.value)), Math.max(0, ...data.map((d) => d.value))), [data]);
  const compact = useCompact(ticks);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const H = height, iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const y = (v: number) => PAD.t + ((hi - v) / (hi - lo || 1)) * ih;
  const band = iw / Math.max(1, data.length);
  const bw = Math.min(24, Math.max(2, band - 2));
  const every = Math.ceil(data.length / Math.floor(iw / 44));
  const show = (d: (typeof data)[number], i: number) => {
    setHover(d.key);
    setTip({ x: PAD.l + band * i + band / 2, y: Math.min(y(d.value), y(0)), lines: [[d.label, ""], ...(d.lines ?? [[label, fmt(d.value)]])] });
  };
  return (
    <div ref={wrap} className="relative" onPointerLeave={() => { setTip(null); setHover(null); }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block" role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--viz-axis)" : "var(--viz-grid)"} strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={10} fill="var(--viz-muted)" className="num">{axisLabel(t, compact)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = PAD.l + band * i + (band - bw) / 2;
          const y0 = y(0), y1 = y(d.value);
          const h = Math.abs(y1 - y0);
          const r = Math.min(4, h, bw / 2);
          const top = Math.min(y0, y1);
          const pos = d.value >= 0;
          // rounded at the data end only, square at the baseline
          const path = h < 0.5 ? "" : pos
            ? `M${x},${y0} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${y0} Z`
            : `M${x},${y0} V${top + h - r} Q${x},${top + h} ${x + r},${top + h} H${x + bw - r} Q${x + bw},${top + h} ${x + bw},${top + h - r} V${y0} Z`;
          return (
            <g key={d.key} tabIndex={0} aria-label={`${d.label}: ${fmt(d.value)}`} onPointerMove={() => show(d, i)} onFocus={() => show(d, i)} onBlur={() => setTip(null)}
              {...(onPick ? { role: "button", style: { cursor: "pointer" }, onClick: () => onPick(d.key),
                onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(d.key); } } } : {})}>
              <rect x={PAD.l + band * i} y={PAD.t} width={band} height={ih} fill="transparent" />
              {path && <path d={path} fill={pos ? "var(--viz-1)" : "var(--viz-neg)"} opacity={hover && hover !== d.key ? 0.55 : 1} />}
              {i % every === 0 && <text x={PAD.l + band * i + band / 2} y={H - 8} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">{d.label}</text>}
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "var(--viz-1)" }} />gain</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "var(--viz-neg)" }} />loss</span>
      </div>
      <Tooltip tip={tip} />
    </div>
  );
}

/** Lines over time, one shared USD axis; crosshair snaps to the nearest date and lists every series. */
export function Lines({ dates, series: allSeries, height = 240, fmt, label, hideable = false }: {
  dates: string[]; series: { name: string; color: string; values: (number | null)[] }[]; height?: number; fmt: (v: number) => string; label: string;
  /** Legend entries become buttons that hide/show their line. */
  hideable?: boolean;
}) {
  const [hidden, setHidden] = useState<string[]>([]);
  const series = allSeries.filter((s) => !hidden.includes(s.name));
  const wrap = useRef<HTMLDivElement>(null);
  const W = useWidth(wrap);
  const [idx, setIdx] = useState<number | null>(null);
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const ticks = useMemo(() => niceTicks(Math.min(0, ...all), Math.max(0, ...all)), [all]);
  const compact = useCompact(ticks);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const H = height, iw = W - PAD.l - PAD.r - 8, ih = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (dates.length > 1 ? (i / (dates.length - 1)) * iw : iw / 2);
  const y = (v: number) => PAD.t + ((hi - v) / (hi - lo || 1)) * ih;
  const firsts = dates.map((d, i) => [d.slice(0, 4), i] as const).filter(([yr], i, a) => i === 0 || a[i - 1][0] !== yr);
  const years: (readonly [string, number])[] = [];
  for (const f of firsts) {  // skip a year label that would overlap the previous one
    const prev = years[years.length - 1];
    if (!prev || (f[1] - prev[1]) / Math.max(1, dates.length - 1) * (W - PAD.l - PAD.r - 8) >= 34) years.push(f);
  }
  const onMove = (e: React.PointerEvent) => {
    const box = wrap.current!.getBoundingClientRect();
    const px = e.clientX - box.left;
    const i = Math.round(((px - PAD.l) / iw) * (dates.length - 1));
    setIdx(Math.max(0, Math.min(dates.length - 1, i)));
  };
  return (
    <div ref={wrap} className="relative" onPointerMove={onMove} onPointerLeave={() => setIdx(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block touch-pan-y" role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={PAD.l + iw} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--viz-axis)" : "var(--viz-grid)"} strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={10} fill="var(--viz-muted)" className="num">{axisLabel(t, compact)}</text>
          </g>
        ))}
        {years.map(([yr, i]) => <text key={yr} x={x(i)} y={H - 8} fontSize={10} fill="var(--viz-muted)">{yr}</text>)}
        {series.map((s) => {
          let d = "", pen = false;
          s.values.forEach((v, i) => {
            if (v === null) { pen = false; return; }
            d += `${pen ? "L" : "M"}${x(i)},${y(v)} `;
            pen = true;
          });
          const li = s.values.map((v, i) => (v === null ? -1 : i)).filter((i) => i >= 0).pop();
          return (
            <g key={s.name}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              {li !== undefined && <circle cx={x(li)} cy={y(s.values[li] as number)} r={4} fill={s.color} stroke="var(--viz-surface)" strokeWidth={2} />}
            </g>
          );
        })}
        {idx !== null && <line x1={x(idx)} x2={x(idx)} y1={PAD.t} y2={PAD.t + ih} stroke="var(--viz-axis)" strokeWidth={1} />}
        {idx !== null && series.map((s) => s.values[idx] === null ? null : <circle key={s.name} cx={x(idx)} cy={y(s.values[idx] as number)} r={4} fill={s.color} stroke="var(--viz-surface)" strokeWidth={2} />)}
      </svg>
      <div className="mt-1 flex flex-wrap gap-4 text-xs text-slate-600 dark:text-slate-300">
        {allSeries.map((s) => {
          const off = hidden.includes(s.name);
          const body = <><span className="inline-block h-0.5 w-4 rounded" style={{ background: off ? "var(--viz-axis)" : s.color }} />{s.name}:{" "}
            <b className="num">{(() => { const v = [...s.values].reverse().find((z) => z !== null); return v == null ? "—" : fmt(v); })()}</b></>;
          return hideable
            ? <button key={s.name} aria-pressed={!off} title={off ? "Show" : "Hide"} className={`flex items-center gap-1.5 ${off ? "opacity-50 line-through" : ""}`}
                onClick={() => setHidden(off ? hidden.filter((h) => h !== s.name) : [...hidden, s.name])}>{body}</button>
            : <span key={s.name} className="flex items-center gap-1.5">{body}</span>;
        })}
      </div>
      {idx !== null && (
        <Tooltip tip={{ x: Math.min(Math.max(x(idx), 80), W - 80), y: PAD.t + 16, lines: [[dates[idx], ""], ...series.map((s) => [s.name, s.values[idx] === null ? "—" : fmt(s.values[idx] as number)] as [string, string])] }} />
      )}
    </div>
  );
}

/** Ranked horizontal bars, one hue, value at the tip. */
export function RankedBars({ rows, fmt, max = 12 }: { rows: { label: string; value: number; pct?: number | null }[]; fmt: (v: number) => string; max?: number }) {
  const shown = rows.slice(0, max);
  const rest = rows.slice(max);
  const all = shown;
  const top = Math.max(...all.map((r) => r.value), 1);
  const restValue = rest.reduce((a, r) => a + r.value, 0);
  const restPct = rest.reduce((a, r) => a + (r.pct ?? 0), 0);
  return (
    <>
    <ul className="space-y-1.5 text-sm">
      {all.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(5rem,9rem)_1fr_auto] items-center gap-2" title={`${r.label}: ${fmt(r.value)}${r.pct != null ? ` (${r.pct.toFixed(1)}%)` : ""}`}>
          <span className="truncate text-slate-600 dark:text-slate-300">{r.label}</span>
          <span className="h-3"><span className="block h-3 rounded-r" style={{ width: `${Math.max(0.5, (r.value / top) * 100)}%`, background: "var(--viz-1)" }} /></span>
          <span className="num whitespace-nowrap text-right text-xs text-slate-700 dark:text-slate-200">{fmt(r.value)}{r.pct != null && <span className="text-slate-500"> · {r.pct.toFixed(1)}%</span>}</span>
        </li>
      ))}
    </ul>
    {rest.length > 0 && <p className="mt-2 text-xs text-slate-500">and {rest.length} more: {fmt(restValue)} · {restPct.toFixed(1)}%</p>}
    </>
  );
}


/** Overview strip under a time chart: the whole history, with a draggable window (the visible range).
 * Drag the window to pan, drag an edge to zoom; arrow keys move a focused edge or window. */
export function Navigator({ dates, values, start, end, onChange }: {
  dates: string[]; values: number[]; start: string | null; end: string; onChange: (start: string, end: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const W = useWidth(wrap);
  const H = 48, n = dates.length;
  const first = (d: string | null) => { if (!d) return 0; const i = dates.findIndex((x) => x >= d); return i < 0 ? n - 1 : i; };
  const last = (d: string) => { let i = n - 1; while (i > 0 && dates[i] > d) i--; return i; };
  const [drag, setDrag] = useState<{ kind: "a" | "b" | "w"; x0: number; a0: number; b0: number } | null>(null);
  const [win, setWin] = useState<[number, number] | null>(null);
  const a = win ? win[0] : first(start);
  const b = win ? win[1] : Math.max(a, last(end));
  if (n < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  const x = (i: number) => (i / (n - 1)) * W;
  const y = (v: number) => 4 + ((hi - v) / (hi - lo || 1)) * (H - 8);
  const step = Math.max(1, Math.floor(n / 400));
  let path = "";
  for (let i = 0; i < n; i += step) path += `${i ? "L" : "M"}${x(i).toFixed(1)},${y(values[i]).toFixed(1)} `;
  const toIdx = (px: number) => Math.round((px / W) * (n - 1));
  const commit = (lo2: number, hi2: number) => { setWin(null); onChange(dates[lo2], dates[hi2]); };
  const move = (e: React.PointerEvent) => {
    if (!drag) return;
    const delta = toIdx(e.clientX - drag.x0);
    let na = drag.a0, nb = drag.b0;
    if (drag.kind === "a") na = Math.min(Math.max(0, drag.a0 + delta), drag.b0 - 1);
    else if (drag.kind === "b") nb = Math.max(Math.min(n - 1, drag.b0 + delta), drag.a0 + 1);
    else { const w = drag.b0 - drag.a0; na = Math.min(Math.max(0, drag.a0 + delta), n - 1 - w); nb = na + w; }
    setWin([na, nb]);
  };
  const down = (kind: "a" | "b" | "w") => (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    setDrag({ kind, x0: e.clientX, a0: a, b0: b });
  };
  const up = () => { if (drag && win) commit(win[0], win[1]); setDrag(null); };
  const key = (kind: "a" | "b" | "w") => (e: React.KeyboardEvent) => {
    const s = Math.max(1, Math.round(n / 40)) * (e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0);
    if (!s) return;
    e.preventDefault();
    if (kind === "a") commit(Math.min(Math.max(0, a + s), b - 1), b);
    else if (kind === "b") commit(a, Math.max(Math.min(n - 1, b + s), a + 1));
    else { const w = b - a; const na = Math.min(Math.max(0, a + s), n - 1 - w); commit(na, na + w); }
  };
  const handle = "fill-white stroke-slate-400 dark:fill-slate-800 dark:stroke-slate-500";
  return (
    <div ref={wrap} className="relative mt-2 select-none" onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block touch-none" role="group" aria-label={`Range ${dates[a]} to ${dates[b]}; drag to change`}>
        <rect x={0} y={0} width={W} height={H} rx={4} fill="var(--viz-grid)" opacity={0.35} />
        <path d={path} fill="none" stroke="var(--viz-muted)" strokeWidth={1} />
        <rect x={0} y={0} width={x(a)} height={H} fill="var(--viz-surface)" opacity={0.6} />
        <rect x={x(b)} y={0} width={W - x(b)} height={H} fill="var(--viz-surface)" opacity={0.6} />
        <rect x={x(a)} y={1} width={Math.max(2, x(b) - x(a))} height={H - 2} fill="var(--viz-1)" fillOpacity={0.12} stroke="var(--viz-1)" strokeWidth={1}
          style={{ cursor: "grab" }} tabIndex={0} role="slider" aria-label="Visible window" aria-valuetext={`${dates[a]} to ${dates[b]}`}
          onPointerDown={down("w")} onKeyDown={key("w")} />
        {(["a", "b"] as const).map((k) => (
          <rect key={k} x={x(k === "a" ? a : b) - 5} y={H / 2 - 12} width={10} height={24} rx={3} className={handle} strokeWidth={1}
            style={{ cursor: "ew-resize" }} tabIndex={0} role="slider" aria-label={k === "a" ? "Start of range" : "End of range"}
            aria-valuetext={dates[k === "a" ? a : b]} onPointerDown={down(k)} onKeyDown={key(k)} />
        ))}
      </svg>
      <div className="mt-0.5 flex justify-between text-[10px] text-slate-500"><span>{dates[0]}</span><span>drag the window or its edges</span><span>{dates[n - 1]}</span></div>
    </div>
  );
}
