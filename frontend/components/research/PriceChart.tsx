"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { Analysis } from "@/lib/research/api";
import { ratioLabel } from "@/lib/research/format";

import { useTheme } from "./Shell";
import { type RangeKey, rangeFrom } from "@/lib/research/range";

const SMA_COLORS: Record<string, string> = {
  sma10: "#f59e0b",
  sma20: "#ec4899",
  sma50: "#3b82f6",
  sma100: "#14b8a6",
  sma200: "#a855f7",
};

type Props = { a: Analysis };

export function PriceChart({ a }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const smaRefs = useRef<Record<string, ISeriesApi<SeriesType>>>({});
  const [visible, setVisible] = useState<Record<string, boolean>>({ sma10: false, sma20: true, sma50: true, sma100: false, sma200: true });
  const [showFib, setShowFib] = useState(true);
  const [range, setRange] = useState<RangeKey>("1Y");
  const { dark } = useTheme();

  useEffect(() => {
    const el = ref.current;
    const s = a.series;
    if (!el || !s) return;
    const fg = dark ? "#cbd5e1" : "#334155";
    const grid = dark ? "#1e293b" : "#f1f5f9";
    const narrow = el.clientWidth < 640;
    const subPanes = a.data_quality?.volume_available ? 3 : 2;
    const dims = narrow ? { price: 300, sub: 90 } : { price: 420, sub: 110 };
    el.style.height = `${dims.price + dims.sub * subPanes + 30}px`;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: fg, fontSize: 11, panes: { separatorColor: grid } },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;
    const t = (i: number) => s.dates[i] as Time;
    const line = (key: string) => (s[key] as (number | null)[]).map((v, i) => (v === null ? { time: t(i) } : { time: t(i), value: v }));

    // Pane 0: price
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981", downColor: "#f43f5e", wickUpColor: "#10b981", wickDownColor: "#f43f5e", borderVisible: false,
    });
    candles.setData(s.dates.map((d, i) => ({ time: d as Time, open: s.open[i]!, high: s.high[i]!, low: s.low[i]!, close: s.close[i]! })));
    smaRefs.current = {};
    for (const k of Object.keys(SMA_COLORS)) {
      const ser = chart.addSeries(LineSeries, { color: SMA_COLORS[k], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: visible[k], title: k.toUpperCase() });
      ser.setData(line(k));
      smaRefs.current[k] = ser;
    }
    const fib = a.fibonacci;
    if (showFib && fib && fib.status === "ok") {
      for (const lv of fib.levels) {
        candles.createPriceLine({
          price: lv.price,
          color: lv.is_nearest ? "#eab308" : lv.kind === "retracement" ? (dark ? "#94a3b8" : "#64748b") : "#38bdf8",
          lineWidth: lv.is_nearest ? 2 : 1,
          lineStyle: lv.kind === "retracement" ? LineStyle.Dashed : LineStyle.Dotted,
          axisLabelVisible: true,
          title: `Fib ${ratioLabel(lv.ratio)}`,
        });
      }
      const markers = [fib.swing_low, fib.swing_high]
        .sort((x, y) => x.date.localeCompare(y.date))
        .map((sw) => ({
          time: sw.date as Time,
          position: sw.kind === "high" ? ("aboveBar" as const) : ("belowBar" as const),
          color: "#eab308",
          shape: sw.kind === "high" ? ("arrowDown" as const) : ("arrowUp" as const),
          text: `Swing ${sw.kind} (confirmed ${sw.confirmed_date})`,
        }));
      createSeriesMarkers(candles, markers);
    }

    let pane = 1;
    // Pane: volume (not for indices)
    if (a.data_quality?.volume_available) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false, title: "Volume" }, pane);
      vol.setData(s.dates.map((d, i) => ({ time: d as Time, value: s.volume[i] ?? 0, color: (s.close[i]! >= (s.open[i] ?? 0)) ? "#10b98188" : "#f43f5e88" })));
      pane++;
    }
    // Pane: RSI
    const rsi = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, title: "RSI 14" }, pane);
    rsi.setData(line("rsi14"));
    for (const lvl of [30, 70]) rsi.createPriceLine({ price: lvl, color: "#94a3b8", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
    pane++;
    // Pane: MACD
    const hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, title: "Hist" }, pane);
    hist.setData((s.macd_hist as (number | null)[]).map((v, i) => (v === null ? { time: t(i) } : { time: t(i), value: v, color: v >= 0 ? "#10b98199" : "#f43f5e99" })));
    chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceLineVisible: false, title: "MACD" }, pane).setData(line("macd_line"));
    chart.addSeries(LineSeries, { color: "#f97316", lineWidth: 1, priceLineVisible: false, title: "Signal" }, pane).setData(line("macd_signal"));

    const panes = chart.panes();
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? dims.price : dims.sub));
    chart.timeScale().setVisibleLogicalRange({ from: rangeFrom(s.dates, range), to: s.dates.length + 2 });

    return () => {
      chart.remove();
      chartRef.current = null;
    };
    // `visible` is intentionally excluded: toggles are applied below without rebuilding.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a, dark, showFib]);

  useEffect(() => {
    const s = a.series;
    if (chartRef.current && s) chartRef.current.timeScale().setVisibleLogicalRange({ from: rangeFrom(s.dates, range), to: s.dates.length + 2 });
  }, [range, a.series]);

  const zoomBy = (factor: number) => {
    const ts = chartRef.current?.timeScale();
    const r = ts?.getVisibleLogicalRange();
    const n = a.series?.dates.length ?? 0;
    if (!ts || !r) return;
    const width = Math.max(10, (r.to - r.from) * factor);
    const to = Math.min(r.to, n + 2);
    ts.setVisibleLogicalRange({ from: Math.max(-2, to - width), to });
  };

  useEffect(() => {
    for (const [k, ser] of Object.entries(smaRefs.current)) ser.applyOptions({ visible: visible[k] });
  }, [visible]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1 text-xs">
        {Object.keys(SMA_COLORS).map((k) => (
          <button key={k} onClick={() => setVisible((v) => ({ ...v, [k]: !v[k] }))}
            className={`rounded border px-2 py-0.5 ${visible[k] ? "border-transparent text-white" : "border-slate-300 text-slate-500 dark:border-slate-700"}`}
            style={visible[k] ? { background: SMA_COLORS[k] } : undefined} aria-pressed={visible[k]}>
            {k.toUpperCase()}
          </button>
        ))}
        <button onClick={() => setShowFib((x) => !x)} aria-pressed={showFib}
          className={`rounded border px-2 py-0.5 ${showFib ? "border-transparent bg-yellow-500 text-white" : "border-slate-300 text-slate-500 dark:border-slate-700"}`}>
          Fibonacci
        </button>
        <span className="ml-2 inline-flex flex-wrap items-center gap-1" role="group" aria-label="Chart range and zoom">
          {(["1M", "3M", "6M", "YTD", "1Y", "2Y", "All"] as RangeKey[]).map((r) => (
            <button key={r} onClick={() => setRange(r)} aria-pressed={range === r}
              className={`rounded border px-1.5 py-0.5 ${range === r ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900" : "border-slate-300 dark:border-slate-700"}`}>
              {r}
            </button>
          ))}
          <button onClick={() => zoomBy(0.7)} aria-label="Zoom in chart" className="rounded border border-slate-300 px-1.5 py-0.5 dark:border-slate-700">＋</button>
          <button onClick={() => zoomBy(1.4)} aria-label="Zoom out chart" className="rounded border border-slate-300 px-1.5 py-0.5 dark:border-slate-700">－</button>
          <button onClick={() => chartRef.current?.timeScale().fitContent()} title="Show all data" className="rounded border border-slate-300 px-1.5 py-0.5 dark:border-slate-700">Fit</button>
        </span>
        <span className="ml-auto text-slate-500" title="Scroll or pinch on the chart to zoom; drag to pan">
          Panes: price{a.data_quality?.volume_available ? " · volume" : ""} · RSI 14 (30/70) · MACD 12/26/9
        </span>
      </div>
      <div ref={ref} className="w-full" style={{ height: 760 }} role="img" aria-label="Candlestick chart with moving averages, Fibonacci levels, volume, RSI and MACD" />
    </div>
  );
}
