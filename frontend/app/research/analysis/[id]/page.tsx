"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { type Column, DataTable } from "@/components/research/DataTable";
import { PriceChart } from "@/components/research/PriceChart";
import { RefreshOneButton } from "@/components/research/RefreshButtons";
import { ScorePanel } from "@/components/research/ScorePanel";
import { SetupBreakdown } from "@/components/research/Setups";
import { WatchStar } from "@/components/research/WatchStar";
import { ErrorBox, Loading, ProvenanceBadge, Section, Warn } from "@/components/research/ui";
import { type Analysis, type FibLevel, type IndicatorItem, type Settings, useApi, type WatchlistResp } from "@/lib/research/api";
import { num, pct, ratioLabel } from "@/lib/research/format";

const IND_ROWS: [string, string, number][] = [
  ["sma10", "SMA 10", 2], ["sma20", "SMA 20", 2], ["sma50", "SMA 50", 2], ["sma100", "SMA 100", 2], ["sma200", "SMA 200", 2],
  ["rsi14", "RSI 14", 2], ["macd_line", "MACD line", 4], ["macd_signal", "MACD signal", 4], ["macd_hist", "MACD histogram", 4],
  ["atr14", "ATR 14", 4], ["relvol20", "Relative volume (vs prior 20d)", 2], ["roc60", "60-day rate of change", 4],
];

const FIB_COLUMNS: Column<FibLevel>[] = [
  { key: "ratio", label: "Level", type: "number", firstDir: "asc", get: (lv) => lv.ratio,
    render: (lv) => <>{ratioLabel(lv.ratio)}{lv.is_nearest && " ◀ nearest"}</> },
  { key: "kind", label: "Type", type: "enum", get: (lv) => lv.kind },
  { key: "price", label: "Price", type: "number", align: "right", get: (lv) => lv.price, render: (lv) => num(lv.price) },
  { key: "dist", label: "Distance", type: "number", align: "right", get: (lv) => lv.distance_abs, render: (lv) => num(lv.distance_abs) },
  { key: "pct", label: "%", type: "number", align: "right", get: (lv) => lv.distance_pct, render: (lv) => pct(lv.distance_pct) },
  { key: "atr", label: "ATR", type: "number", align: "right", firstDir: "asc", get: (lv) => lv.distance_atr, render: (lv) => num(lv.distance_atr) },
  { key: "side", label: "Side", type: "enum", get: (lv) => (lv.distance_abs >= 0 ? "below price" : "above price"), defaultHidden: true },
];

const DQ_LABEL: Record<IndicatorItem["data_quality"], string> = {
  ok: "",
  insufficient_history: "insufficient history",
  gap_in_window: "data gap in window",
  not_applicable: "not applicable for indices",
};

export default function AnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const settings = useApi<Settings>("/api/settings");
  const [sens, setSens] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string>("");
  const [interval, setInterval_] = useState<"1d" | "1w" | "1mo">("1d");

  useEffect(() => {
    if (settings.data && sens === null) setSens(settings.data.settings.default_sensitivity);
  }, [settings.data, sens]);

  const qs = new URLSearchParams();
  if (sens) qs.set("sensitivity", sens);
  if (asOf) qs.set("as_of", asOf);
  if (interval !== "1d") qs.set("interval", interval);
  const { data: a, error, loading, reload } = useApi<Analysis>(sens ? `/api/listings/${id}/analysis?${qs}` : null);
  const { data: wl, reload: reloadWatch } = useApi<WatchlistResp>("/api/watchlist");
  const watched = !!wl?.rows.some((r) => r.listing.id === Number(id));

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!a) return <Loading label="Calculating analysis…" />;

  const L = a.listing;
  const controls = (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span className="inline-flex overflow-hidden rounded border border-slate-300 dark:border-slate-700" role="group" aria-label="Timeframe">
        {([["1d", "Daily"], ["1w", "Weekly"], ["1mo", "Monthly"]] as const).map(([v, l]) => (
          <button key={v} onClick={() => setInterval_(v)} aria-pressed={interval === v}
            className={`px-2 py-0.5 text-xs ${interval === v ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>{l}</button>
        ))}
      </span>
      <label className="flex items-center gap-1">
        Fibonacci sensitivity
        <select value={sens ?? ""} onChange={(e) => setSens(e.target.value)} className="rounded border border-slate-300 bg-transparent px-1 py-0.5 dark:border-slate-700">
          <option value="high">High (1.5 × ATR)</option>
          <option value="medium">Medium (2.5 × ATR)</option>
          <option value="low">Low (4.0 × ATR)</option>
        </select>
      </label>
      <label className="flex items-center gap-1">
        As of
        <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="rounded border border-slate-300 bg-transparent px-1 py-0.5 dark:border-slate-700" />
      </label>
      {asOf && <button onClick={() => setAsOf("")} className="text-xs underline">latest</button>}
      <RefreshOneButton listingId={Number(id)} real={a?.listing.namespace === "real"} onDone={reload} />
      <WatchStar listingId={Number(id)} on={watched} onChange={reloadWatch} label={watched ? "Watching" : "Watch"} />
      {loading && <span className="text-xs text-slate-500">recalculating…</span>}
    </div>
  );

  const header = (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h1 className="text-xl font-semibold">
          {L.ticker} <span className="text-sm font-normal text-slate-500">{L.name} · {L.exchange_name} ({L.exchange}) · {L.currency} · {L.asset_class}{L.tracks ? ` · tracks ${L.tracks}` : ""}</span>
        </h1>
        <ProvenanceBadge p={a.provenance} />
      </div>
      {controls}
    </div>
  );

  if (a.status !== "ok") {
    return (
      <div className="space-y-3">
        {header}
        {a.status === "no_price_history" ? (
          <Warn>
            No price history downloaded{asOf ? " up to the selected date" : ""}. Go to <Link className="underline" href="/research/analysis">Market Analysis</Link> and
            click <b>Update prices</b>.
          </Warn>
        ) : (
          <Warn>Insufficient history: only {a.bars_available} bar(s) available up to the selected date. No indicators are shown rather than partial values.</Warn>
        )}
      </div>
    );
  }

  const fib = a.fibonacci!;
  const ind = a.latest!.indicators;
  const close = a.latest!.close;
  const gaps = a.data_quality!.gaps;
  const insufficient = Object.entries(ind).filter(([, v]) => v.data_quality === "insufficient_history").map(([k]) => k);

  return (
    <div className="space-y-4">
      {header}
      {a.interval && a.interval !== "1d" && (
        <Warn>
          {a.interval === "1w" ? "Weekly" : "Monthly"} view: bars are built from daily prices on this exchange&apos;s trading calendar, and every
          indicator, swing, Fibonacci level and score below is calculated on {a.interval === "1w" ? "weekly" : "monthly"} bars (SMA 50 = 50{" "}
          {a.interval === "1w" ? "weeks" : "months"}).
          {a.timeframe?.last_bar_in_progress && <> The last bar is <b>in progress</b>: its {a.interval === "1w" ? "week" : "month"} hasn&apos;t ended yet.</>}
        </Warn>
      )}
      {asOf && <Warn>Historical view: everything below uses only data available up to {a.as_of} (no look-ahead).</Warn>}
      {gaps.length > 0 && (
        <Warn>
          <b>Missing data:</b>{" "}
          {gaps.map((g) => `${g.missing_business_days} business day(s) between ${g.after} and ${g.before}`).join("; ")}. Gaps are not filled.
          {Object.entries(ind).some(([, v]) => v.data_quality === "gap_in_window") && " Some indicator windows include a gap (marked below)."}
        </Warn>
      )}
      {insufficient.length > 0 && <Warn>Insufficient history for: {insufficient.join(", ")}. These are shown as “—”.</Warn>}

      <Section title={`Price · last close ${num(close)} ${L.currency} on ${a.as_of}`}>
        <PriceChart a={a} />
      </Section>

      {a.setups && (
        <Section title={`Setups · ${a.setups.triggered.length} of ${a.setups.setups.length} triggered`}
          right={<span className="text-xs text-slate-500">Conditions to research, not signals.</span>}>
          <SetupBreakdown setups={a.setups} />
        </Section>
      )}

      <Section title="Technical scores" right={<span className="text-xs text-slate-500">Deterministic, version {a.scores!.short.score_version}. Not a buy or sell signal.</span>}>
        <ScorePanel scores={a.scores!} />
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Fibonacci levels" right={<span className="text-xs text-slate-500">ATR ZigZag k = {a.atr_multiple}</span>}>
          {fib.status !== "ok" ? (
            <Warn>Not enough confirmed swings ({fib.swings_available}) to draw Fibonacci levels at this sensitivity.</Warn>
          ) : (
            <>
              <p className="mb-2 text-xs text-slate-600 dark:text-slate-300">
                {fib.direction === "up" ? "Up" : "Down"} swing from {fib.direction === "up" ? "low" : "high"}{" "}
                <b>{num(fib.direction === "up" ? fib.swing_low.price : fib.swing_high.price)}</b> ({fib.direction === "up" ? fib.swing_low.date : fib.swing_high.date}) to{" "}
                {fib.direction === "up" ? "high" : "low"} <b>{num(fib.direction === "up" ? fib.swing_high.price : fib.swing_low.price)}</b> (
                {fib.direction === "up" ? fib.swing_high.date : fib.swing_low.date}, confirmed {fib.direction === "up" ? fib.swing_high.confirmed_date : fib.swing_low.confirmed_date}).
                Retracement depth <b>{num(fib.retracement_depth * 100, 1)}%</b>
                {fib.beyond_swing && <span className="text-amber-600"> (price is beyond the swing range)</span>}.
              </p>
              <DataTable
                id="fib-levels"
                compact
                rows={fib.levels}
                rowKey={(lv) => lv.kind + lv.ratio}
                rowClassName={(lv) => (lv.is_nearest ? "bg-yellow-100 font-semibold dark:bg-yellow-900/40" : "")}
                columns={FIB_COLUMNS}
              />
              {fib.dropped_levels.length > 0 && (
                <p className="mt-1 text-xs text-slate-500">Dropped: {fib.dropped_levels.map((d) => `${ratioLabel(d.ratio)} (${d.reason})`).join(", ")}</p>
              )}
              <p className="mt-2 text-xs text-slate-500">
                Fibonacci levels are analytical reference levels, not guaranteed support or resistance. Distance = close − level. Hash {fib.input_hash.slice(0, 12)}…
              </p>
            </>
          )}
        </Section>

        <Section title="Indicators">
          <div className="overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <tbody>
              <tr><td>Close</td><td className="text-right">{num(close)}</td><td /></tr>
              {IND_ROWS.map(([k, label, d]) => {
                const it = ind[k];
                const v = k === "roc60" && it.value !== null ? pct(it.value * 100) : num(it.value, d);
                return (
                  <tr key={k}>
                    <td>{label}</td>
                    <td className="text-right">{v}</td>
                    <td className="text-right text-xs text-amber-600">{DQ_LABEL[it.data_quality]}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            RSI and ATR use Wilder smoothing; EMAs are SMA-seeded (TA-Lib conventions). Relative volume excludes today&apos;s bar from the average.
          </p>
        </Section>
      </div>
    </div>
  );
}
