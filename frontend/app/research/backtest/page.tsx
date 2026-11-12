"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import { type Column, DataTable } from "@/components/research/DataTable";
import { EquityChart } from "@/components/research/EquityChart";
import { Empty, ErrorBox, Loading, ProvenanceBadge, Section, Warn } from "@/components/research/ui";
import {
  apiFetch, ApiError, type BtMetrics, type BtRun, type BtRunsResp, type BtSegment, type BtStrategiesResp, type BtTrade,
  type ListingInfo, type Provenance, type RotBtStrategiesResp, useApi,
} from "@/lib/research/api";
import { fmtTimestamp, num, pct, signClass } from "@/lib/research/format";

type ListingsResp = { listings: (ListingInfo & { provenance: Provenance })[] };
type Mode = "single" | "walk_forward";

const inputCls = "rounded border border-slate-300 bg-transparent px-1.5 py-1 text-sm dark:border-slate-700";
const fmtParams = (p: Record<string, unknown> | null | undefined) =>
  p ? Object.entries(p).map(([k, v]) => `${k.replaceAll("_", " ")} ${String(v).replaceAll("_", " + ")}`).join(", ") : "—";

function Pct({ v, signed = true }: { v: number | null | undefined; signed?: boolean }) {
  return <span className={signed ? signClass(v) : ""}>{pct(v, 1, signed)}</span>;
}

const ROWS: [string, (m: BtMetrics) => React.ReactNode][] = [
  ["Total return", (m) => <Pct v={m.total_return_pct} />],
  ["CAGR", (m) => <Pct v={m.cagr_pct} />],
  ["Max drawdown", (m) => <Pct v={m.max_drawdown_pct == null ? null : -m.max_drawdown_pct} />],
  ["Sharpe-like (rf 0)", (m) => num(m.sharpe_like, 2)],
  ["Trades", (m) => m.trades],
  ["Win rate", (m) => <Pct v={m.win_rate_pct} signed={false} />],
  ["Avg trade", (m) => <Pct v={m.avg_trade_pct} />],
  ["Exposure", (m) => <Pct v={m.exposure_pct} signed={false} />],
  ["Bars", (m) => m.bars],
];

function Summary({ main, holdout, bh = "Buy & hold" }: { main: BtSegment; holdout: BtSegment; bh?: string }) {
  const ew = !!main.equal_weight && !!holdout.equal_weight;
  const span = ew ? 3 : 2;
  return (
    <div className="overflow-x-auto">
      <table className="tbl num w-full text-sm">
        <thead>
          <tr>
            <th></th>
            <th className="text-right" colSpan={span}>{main.label}<div className="text-[10px] font-normal">{main.start_date} → {main.end_date}</div></th>
            <th className="text-right" colSpan={span}>{holdout.label}<div className="text-[10px] font-normal">{holdout.start_date} → {holdout.end_date}</div></th>
          </tr>
          <tr><th></th>{[0, 1].map((i) => (
            <Fragment key={i}><th className="text-right">Strategy</th><th className="text-right">{bh}</th>{ew && <th className="text-right">Equal-weight sectors</th>}</Fragment>
          ))}</tr>
        </thead>
        <tbody>
          {ROWS.map(([label, f]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="text-right font-medium">{f(main.metrics)}</td>
              <td className="text-right">{f(main.buy_hold)}</td>
              {ew && <td className="text-right">{f(main.equal_weight!)}</td>}
              <td className="text-right font-medium">{f(holdout.metrics)}</td>
              <td className="text-right">{f(holdout.buy_hold)}</td>
              {ew && <td className="text-right">{f(holdout.equal_weight!)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type TradeRow = BtTrade & { period: string; ticker?: string; sector?: string };
const tradeCols: Column<TradeRow>[] = [
  { key: "period", label: "Period", type: "enum", get: (t) => t.period },
  { key: "entry", label: "Entry", type: "date", get: (t) => t.entry_date },
  { key: "exit", label: "Exit", type: "date", get: (t) => t.exit_date },
  { key: "in", label: "Entry price", type: "number", align: "right", get: (t) => t.entry_price, render: (t) => num(t.entry_price) },
  { key: "out", label: "Exit price", type: "number", align: "right", get: (t) => t.exit_price, render: (t) => num(t.exit_price) },
  { key: "ret", label: "Return", type: "number", align: "right", get: (t) => t.return_pct, render: (t) => <Pct v={t.return_pct} /> },
  { key: "bars", label: "Bars", type: "number", align: "right", get: (t) => t.bars_held },
  { key: "reason", label: "Exit reason", type: "enum", get: (t) => t.exit_reason },
  { key: "note", label: "Entry signal", type: "text", get: (t) => t.entry_note },
];
const rotationTradeCols: Column<TradeRow>[] = [
  tradeCols[0],
  { key: "sector", label: "Sector", type: "enum", get: (t) => t.sector ?? null, render: (t) => <>{t.sector} <span className="text-slate-500">{t.ticker}</span></> },
  ...tradeCols.slice(1, 8),
];

function Result({ run }: { run: BtRun }) {
  const r = run.result;
  const rot = r.kind === "rotation";
  const bh = rot ? `${r.benchmark} buy & hold` : "Buy & hold";
  const trades = useMemo<TradeRow[]>(() => [
    ...r.main.trades.map((t) => ({ ...t, period: r.mode === "single" ? "in-sample" : "out-of-sample" })),
    ...r.holdout.trades.map((t) => ({ ...t, period: "holdout" })),
  ], [r]);
  return (
    <div className="space-y-4">
      <Section title={`${rot ? `${r.region?.name} sectors vs ${r.benchmark}` : run.listing.ticker} · ${r.strategy_name} · ${r.mode === "single" ? "single run" : "walk-forward"}`}
        right={<ProvenanceBadge p={run.provenance} compact />}>
        <div className="space-y-3">
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-950">
            <div><b>Parameter combinations tested: {r.combinations_tested}</b>{r.mode === "walk_forward" && <> (grid × {(r.folds?.length ?? 0) + 1} selections)</>}.
              {" "}Final parameters: <b>{fmtParams(r.final_params)}</b>.</div>
            <div className="mt-1">The holdout ({r.periods.holdout_from} → {r.periods.until}) was not used to choose anything; it was evaluated once, here.
              Costs: {r.costs.commission_bps} bps commission + {r.costs.slippage_bps} bps slippage per side. The first {r.warmup_bars} bars are warm-up.</div>
            <div className="mt-1 font-semibold">{r.disclaimer}</div>
          </div>
          {r.notes.length > 0 && <ul className="list-disc pl-5 text-xs text-slate-600 dark:text-slate-300">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          <p className="text-xs text-slate-500">{r.description}</p>
          <Summary main={r.main} holdout={r.holdout} bh={bh} />
        </div>
      </Section>
      <Section title={rot ? `Growth of 1 (strategy vs ${r.benchmark} and equal-weight sectors)` : "Growth of 1 (strategy vs buy & hold)"}>
        <EquityChart main={r.main} holdout={r.holdout} benchmarkLabel={bh} />
        <p className="mt-1 text-xs text-slate-500">For display, the holdout line continues from the end of the earlier period. The metrics above treat each period separately.</p>
      </Section>
      {r.folds && (
        <Section title="Walk-forward folds">
          <div className="overflow-x-auto">
            <table className="tbl num w-full text-xs">
              <thead><tr><th>Fold</th><th>Trained on</th><th>Tested on</th><th>Chosen parameters</th><th className="text-right">Train Sharpe-like</th><th className="text-right">Test return</th><th className="text-right">Test trades</th></tr></thead>
              <tbody>
                {r.folds.map((f) => (
                  <tr key={f.fold}>
                    <td>{f.fold}</td><td>{f.train[0]} → {f.train[1]}</td><td>{f.test[0]} → {f.test[1]}</td>
                    <td>{fmtParams(f.params)}{f.selection_fallback && <span className="text-amber-600" title="No combination had 3+ trades in training"> (fallback)</span>}</td>
                    <td className="text-right">{num(f.train_metrics.sharpe_like, 2)}</td>
                    <td className="text-right"><Pct v={f.test_metrics.total_return_pct} /></td>
                    <td className="text-right">{f.test_metrics.trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-xs text-slate-500">Each fold picks the best combination on all earlier data (by Sharpe-like ratio, 3+ trades), then tests it on the next block.
            Positions open at the end of a block are closed there. &quot;Fallback&quot; means no combination had enough trades, so the first one was used.</p>
        </Section>
      )}
      {rot && r.sectors && <TimeInSector r={r} />}
      <Section title="Results per calendar year">
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-xs">
            <thead><tr><th>Period</th><th>Year</th><th className="text-right">Strategy</th><th className="text-right">{bh}</th>{rot && <th className="text-right">Equal-weight sectors</th>}<th className="text-right">Trades closed</th></tr></thead>
            <tbody>
              {[["main", r.main], ["holdout", r.holdout]].flatMap(([k, s]) => (s as BtSegment).by_year.map((y) => (
                <tr key={`${k}${y.year}`}><td>{k === "main" ? (s as BtSegment).label : "Holdout"}</td><td>{y.year}</td>
                  <td className="text-right"><Pct v={y.strategy_pct} /></td><td className="text-right"><Pct v={y.buy_hold_pct} /></td>{rot && <td className="text-right"><Pct v={y.equal_weight_pct} /></td>}<td className="text-right">{y.trades_closed}</td></tr>
              )))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Trades">
        <DataTable id={rot ? "bt-rot-trades" : "bt-trades"} rows={trades} columns={rot ? rotationTradeCols : tradeCols}
          rowKey={(t) => `${t.period}${t.ticker ?? ""}${t.entry_date}`} initialSort={[{ key: "entry", dir: "asc" }]}
          empty={<Empty>{rot ? "No trades: no sector was ever selected in these periods." : "No trades: the entry rule never fired in these periods."}</Empty>} />
      </Section>
      <p className="text-xs text-slate-500">Run #{run.id} · {fmtTimestamp(run.created_at)} · {run.version} · request {run.params_hash.slice(0, 10)} · input {run.input_hash.slice(0, 10)}</p>
    </div>
  );
}

function TimeInSector({ r }: { r: BtRun["result"] }) {
  const rows = (r.sectors ?? []).map((x) => ({ ...x, main: r.main.time_in_sector_pct?.[x.ticker] ?? 0, hold: r.holdout.time_in_sector_pct?.[x.ticker] ?? 0 }))
    .sort((a, b) => b.main - a.main || a.ticker.localeCompare(b.ticker));
  return (
    <Section title="Share of time in each sector">
      <div className="overflow-x-auto">
        <table className="tbl num w-full text-xs">
          <thead><tr><th>Sector</th><th className="text-right">{r.main.label}</th><th className="text-right">Holdout</th></tr></thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.ticker}><td>{x.sector} <span className="text-slate-500">{x.ticker}</span></td>
                <td className="text-right">{pct(x.main, 0, false)}</td><td className="text-right">{pct(x.hold, 0, false)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-slate-500">Share of sessions each sector was held. Several sectors can be held at once, so the column can add up to more than 100%.
        {r.excluded_sectors && r.excluded_sectors.length > 0 && <> Left out for too little history: {r.excluded_sectors.map((x) => x.ticker).join(", ")}.</>}</p>
    </Section>
  );
}

export default function BacktestPage() {
  const strategies = useApi<BtStrategiesResp>("/api/backtest/strategies");
  const listings = useApi<ListingsResp>("/api/listings");
  const runs = useApi<BtRunsResp>("/api/backtest/runs");
  const rotStrategies = useApi<RotBtStrategiesResp>("/api/backtest/rotation/strategies");
  const [kind, setKind] = useState<"single" | "rotation">("single");
  const [region, setRegion] = useState("us");
  const [bench, setBench] = useState("SPY");
  const [data, setData] = useState("auto");
  const [rotSid, setRotSid] = useState("quadrant_hold");
  const [listingId, setListingId] = useState<number | null>(null);
  const [sid, setSid] = useState("ma_cross");
  const [mode, setMode] = useState<Mode>("single");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [comm, setComm] = useState(5);
  const [slip, setSlip] = useState(10);
  const [holdout, setHoldout] = useState(0.2);
  const [folds, setFolds] = useState(3);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [run, setRun] = useState<BtRun | null>(null);

  const strat = kind === "rotation" ? rotStrategies.data?.strategies.find((s) => s.id === rotSid) : strategies.data?.strategies.find((s) => s.id === sid);
  useEffect(() => {
    if (strat) setParams(Object.fromEntries(Object.entries(strat.params).map(([k, v]) => [k, v.default])));
  }, [strat]);
  useEffect(() => setFolds(kind === "rotation" ? 2 : 3), [kind]);
  const reg = rotStrategies.data?.regions.find((r) => r.id === region);
  const tradable = (listings.data?.listings ?? []).filter((l) => l.provenance.latest_bar_date);
  useEffect(() => {
    if (listingId === null && tradable.length) setListingId(tradable[0].id);
  }, [tradable, listingId]);

  const submit = async () => {
    if (kind === "single" && listingId === null) return;
    setBusy(true);
    setErr(null);
    try {
      const common = { mode, params: mode === "single" ? params : null, commission_bps: comm, slippage_bps: slip, holdout_pct: holdout, folds };
      const [url, body] = kind === "rotation"
        ? ["/api/backtest/rotation/run", { ...common, region, benchmark: bench, data, strategy: rotSid }]
        : ["/api/backtest/run", { ...common, listing_id: listingId, strategy: sid }];
      setRun(await apiFetch<BtRun>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
      runs.reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(false);
    }
  };
  const open = async (id: number) => {
    setErr(null);
    try {
      setRun(await apiFetch<BtRun>(`/api/backtest/runs/${id}`));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    }
  };
  const remove = async (id: number) => {
    await apiFetch(`/api/backtest/runs/${id}`, { method: "DELETE" }).catch(() => {});
    if (run?.id === id) setRun(null);
    runs.reload();
  };

  if (strategies.error) return <ErrorBox error={strategies.error} onRetry={strategies.reload} />;
  if (!strategies.data || !listings.data) return <Loading label="Loading strategies…" />;
  const d = strategies.data;

  const runCols: Column<BtRunsResp["runs"][number]>[] = [
    { key: "id", label: "#", type: "number", get: (x) => x.id, render: (x) => <button className="text-blue-600 underline dark:text-blue-400" onClick={() => open(x.id)}>{x.id}</button> },
    { key: "when", label: "When", type: "date", get: (x) => x.created_at.slice(0, 10), render: (x) => fmtTimestamp(x.created_at) },
    { key: "sym", label: "Symbol", type: "text", get: (x) => x.ticker,
      render: (x) => <>{x.ticker} {x.is_synthetic && <span className="rounded bg-violet-600 px-1 text-[10px] font-bold uppercase text-white">Synth</span>}</> },
    { key: "strat", label: "Strategy", type: "enum", get: (x) => x.strategy_name },
    { key: "mode", label: "Mode", type: "enum", get: (x) => x.mode },
    { key: "n", label: "Combos", type: "number", align: "right", get: (x) => x.combinations_tested },
    { key: "main", label: "Main", type: "number", align: "right", get: (x) => x.main_return_pct, render: (x) => <Pct v={x.main_return_pct} /> },
    { key: "mainbh", label: "B&H", type: "number", align: "right", get: (x) => x.main_buy_hold_pct, render: (x) => <Pct v={x.main_buy_hold_pct} /> },
    { key: "hold", label: "Holdout", type: "number", align: "right", get: (x) => x.holdout_return_pct, render: (x) => <Pct v={x.holdout_return_pct} /> },
    { key: "holdbh", label: "B&H", type: "number", align: "right", get: (x) => x.holdout_buy_hold_pct, render: (x) => <Pct v={x.holdout_buy_hold_pct} /> },
    { key: "holdew", label: "Eq-wt", type: "number", align: "right", get: (x) => x.holdout_equal_weight_pct,
      render: (x) => (x.kind === "rotation" ? <Pct v={x.holdout_equal_weight_pct} /> : <span className="text-slate-400">—</span>) },
    { key: "del", label: "", type: "text", sortable: false, filterable: false, get: () => null,
      render: (x) => <button className="text-xs text-rose-600 underline" onClick={() => remove(x.id)} aria-label={`Delete backtest ${x.id}`}>delete</button> },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Backtesting</h1>
      <Warn><b>{d.disclaimer}</b> Backtests describe what simple rules would have done on stored prices, after costs. They are research, not a forecast or a recommendation.</Warn>
      <Section title="Set up a backtest">
        <div role="tablist" aria-label="Backtest type" className="mb-3 inline-flex rounded border border-slate-300 text-sm dark:border-slate-700">
          {([["single", "Single instrument"], ["rotation", "Sector rotation"]] as const).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
              className={`px-3 py-1 ${kind === k ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : ""}`}>{label}</button>
          ))}
        </div>
        <div className="grid gap-3 text-sm md:grid-cols-2">
          {kind === "rotation" ? (
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1">Region
                <select aria-label="Region" className={inputCls} value={region} onChange={(e) => {
                  setRegion(e.target.value);
                  setBench(rotStrategies.data?.regions.find((r) => r.id === e.target.value)?.default_benchmark ?? "");
                }}>
                  {rotStrategies.data?.regions.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.sectors} sectors)</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1">Benchmark
                <select aria-label="Benchmark" className={inputCls} value={bench} onChange={(e) => setBench(e.target.value)}>
                  {reg?.benchmarks.map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1">Data
                <select aria-label="Data" className={inputCls} value={data} onChange={(e) => setData(e.target.value)}>
                  <option value="auto">real if available</option><option value="real">real only</option><option value="synthetic">synthetic demo</option>
                </select>
              </label>
            </div>
          ) : (
          <label className="flex flex-col gap-1">Instrument
            <select aria-label="Instrument" className={inputCls} value={listingId ?? ""} onChange={(e) => setListingId(Number(e.target.value))}>
              {tradable.map((l) => <option key={l.id} value={l.id}>{l.ticker} · {l.exchange} · {l.namespace === "real" ? "real" : "synthetic"}</option>)}
            </select>
          </label>
          )}
          <label className="flex flex-col gap-1">Strategy
            <select aria-label="Strategy" className={inputCls} value={kind === "rotation" ? rotSid : sid}
              onChange={(e) => (kind === "rotation" ? setRotSid : setSid)(e.target.value)}>
              {(kind === "rotation" ? rotStrategies.data?.strategies ?? [] : d.strategies).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            {strat && <span className="text-xs text-slate-500">{strat.description}</span>}
          </label>
          <fieldset className="flex flex-col gap-1">
            <legend className="mb-1">Mode</legend>
            <label className="flex items-center gap-2"><input type="radio" name="mode" checked={mode === "single"} onChange={() => setMode("single")} />
              Single run with my parameters (1 combination)</label>
            <label className="flex items-center gap-2"><input type="radio" name="mode" checked={mode === "walk_forward"} onChange={() => setMode("walk_forward")} />
              Walk-forward: let it choose ({strat ? strat.grid_size * (folds + 1) : "?"} combinations tested)</label>
          </fieldset>
          <div className="flex flex-wrap items-end gap-3">
            {mode === "single" && strat && Object.entries(strat.params).map(([k, spec]) => (
              <label key={k} className="flex flex-col gap-1">{spec.label}
                <select aria-label={spec.label} className={inputCls} value={String(params[k] ?? spec.default)}
                  onChange={(e) => setParams({ ...params, [k]: spec.choices.find((c) => String(c) === e.target.value) })}>
                  {spec.choices.map((c) => <option key={String(c)} value={String(c)}>{spec.labels?.[String(c)] ?? (typeof c === "boolean" ? (c ? "yes" : "no") : String(c).replaceAll("_", " "))}</option>)}
                </select>
              </label>
            ))}
            {mode === "walk_forward" && (
              <label className="flex flex-col gap-1">Folds
                <select aria-label="Folds" className={inputCls} value={folds} onChange={(e) => setFolds(Number(e.target.value))}>
                  {[2, 3, 4, 5, 6].map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </label>
            )}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">Commission (bps/side)
              <input aria-label="Commission bps" type="number" min={0} max={200} step={1} className={`${inputCls} w-24`} value={comm} onChange={(e) => setComm(Number(e.target.value))} />
            </label>
            <label className="flex flex-col gap-1">Slippage (bps/side)
              <input aria-label="Slippage bps" type="number" min={0} max={200} step={1} className={`${inputCls} w-24`} value={slip} onChange={(e) => setSlip(Number(e.target.value))} />
            </label>
            <label className="flex flex-col gap-1">Holdout
              <select aria-label="Holdout" className={inputCls} value={holdout} onChange={(e) => setHoldout(Number(e.target.value))}>
                {[0.1, 0.2, 0.3, 0.4].map((h) => <option key={h} value={h}>last {h * 100}%</option>)}
              </select>
            </label>
          </div>
          <div className="flex items-end">
            <button onClick={submit} disabled={busy || (kind === "single" && listingId === null) || (kind === "rotation" && !rotStrategies.data)}
              className="rounded bg-slate-900 px-4 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">
              {busy ? "Running…" : "Run backtest"}
            </button>
          </div>
        </div>
        {kind === "rotation" ? (
          <p className="mt-2 text-xs text-slate-500">Tests the Sector Rotation module&apos;s own rules as an equal-weight portfolio of sector ETFs, on daily bars aligned
            across the benchmark and every sector. Decisions at the close, rebalancing at the next open, costs on the value traded. Compared with buying and
            holding the benchmark and with holding every sector in equal weight. Uses the RRG approximation and the default score weights.</p>
        ) : (
          <p className="mt-2 text-xs text-slate-500">Daily bars, long only, all in / all out. Signals at the close, orders at the next open. Default costs are
            5 bps commission + 10 bps slippage per side (0.3% per round trip). 1 bp = 0.01%.</p>
        )}
      </Section>
      <ErrorBox error={err} />
      {busy && <Loading label="Running the backtest (walk-forward tries every combination on each fold)…" />}
      {run && !busy && <Result run={run} />}
      <Section title="Saved backtests" right={runs.data ? <ProvenanceBadge p={runs.data.provenance} compact /> : null}>
        {runs.error ? <ErrorBox error={runs.error} onRetry={runs.reload} /> : !runs.data ? <Loading /> : (
          <DataTable id="bt-runs" rows={runs.data.runs} columns={runCols} rowKey={(x) => x.id} initialSort={[{ key: "id", dir: "desc" }]}
            empty={<Empty>No backtests yet.</Empty>} />
        )}
      </Section>
    </div>
  );
}
