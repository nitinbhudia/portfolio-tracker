"use client";

import { ColorType, createChart, LineSeries, LineStyle, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { useTheme } from "./Shell";

/** Sector and benchmark rebased to 100, plus the sector ÷ benchmark ratio (relative performance), on one chart. */
export function RelativeChart({ dates, sector, benchmark, relative, sectorLabel, benchLabel }: {
  dates: string[]; sector: number[]; benchmark: number[]; relative: number[]; sectorLabel: string; benchLabel: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useTheme();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fg = dark ? "#cbd5e1" : "#334155";
    const grid = dark ? "#1e293b" : "#f1f5f9";
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: fg, fontSize: 11 },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
    });
    const pts = (v: number[]) => dates.map((d, i) => ({ time: d as Time, value: v[i] }));
    chart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 2, priceLineVisible: false, title: sectorLabel }).setData(pts(sector));
    chart.addSeries(LineSeries, { color: dark ? "#94a3b8" : "#64748b", lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, title: benchLabel })
      .setData(pts(benchmark));
    chart.addSeries(LineSeries, { color: "#d97706", lineWidth: 2, priceLineVisible: false, title: `${sectorLabel} ÷ ${benchLabel}` }).setData(pts(relative));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [dates, sector, benchmark, relative, sectorLabel, benchLabel, dark]);
  return <div ref={ref} className="h-64 w-full" role="img" aria-label={`${sectorLabel} and ${benchLabel} rebased to 100, with their ratio`} />;
}
