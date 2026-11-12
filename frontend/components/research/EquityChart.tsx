"use client";

import { ColorType, createChart, createSeriesMarkers, LineSeries, LineStyle, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { BtSegment } from "@/lib/research/api";
import { chainSegments } from "@/lib/research/backtest";

import { useTheme } from "./Shell";

export function EquityChart({ main, holdout, benchmarkLabel = "Buy & hold" }: { main: BtSegment; holdout: BtSegment; benchmarkLabel?: string }) {
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
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    });
    const c = chainSegments(main, holdout);
    const pts = (vals: number[]) => c.dates.map((d, i) => ({ time: d as Time, value: vals[i] }));
    const strat = chart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 2, priceLineVisible: false, title: "Strategy" });
    strat.setData(pts(c.strategy));
    chart.addSeries(LineSeries, { color: dark ? "#94a3b8" : "#64748b", lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, title: benchmarkLabel })
      .setData(pts(c.buyHold));
    if (c.equalWeight) {
      chart.addSeries(LineSeries, { color: "#059669", lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false, title: "Equal-weight sectors" })
        .setData(pts(c.equalWeight));
    }
    createSeriesMarkers(strat, [{ time: c.holdoutStart as Time, position: "aboveBar", color: "#d97706", shape: "arrowDown", text: "Holdout starts" }]);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [main, holdout, dark, benchmarkLabel]);
  return <div ref={ref} className="h-72 w-full" aria-label="Equity curve: strategy versus buy and hold" role="img" />;
}
