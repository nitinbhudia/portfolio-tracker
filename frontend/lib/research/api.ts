"use client";

import { useCallback, useEffect, useState } from "react";

export type Provenance = {
  source: string | null;
  is_synthetic: boolean | null;
  as_of: string | null;
  oldest_as_of?: string;
  exchange_timezone: string | null;
  is_delayed: boolean | null;
  delay_minutes: number | null;
  data_type?: string;
  mixed_sources?: boolean;
  stale: boolean;
  latest_bar_date?: string | null;
  price_adjustment?: string;
};

export type ListingInfo = {
  id: number;
  namespace?: "synthetic" | "real";
  ticker: string;
  exchange: string;
  exchange_name: string;
  currency: string;
  name: string;
  isin: string | null;
  asset_class: "stock" | "etf" | "index";
  sector: string | null;
  tracks: string | null;
  is_holdable: boolean;
  is_benchmark: boolean;
};

export type Classification = "bullish" | "neutral" | "bearish" | null;
export type Horizon = "short" | "medium" | "long";

export type Nearest = {
  ratio: number;
  kind: string;
  price: number;
  distance_abs: number;
  distance_pct: number;
  distance_atr: number | null;
  price_above_level: boolean;
};

export type FibLevel = {
  ratio: number;
  kind: "retracement" | "extension";
  price: number;
  distance_abs: number;
  distance_pct: number;
  distance_atr: number | null;
  is_nearest: boolean;
};

export type SwingOut = { kind: "high" | "low"; date: string; confirmed_date: string; price: number };

export type Fibonacci =
  | { status: "insufficient_swings"; swings_available: number; atr_multiple: number }
  | {
      status: "ok";
      direction: "up" | "down";
      swing_high: SwingOut;
      swing_low: SwingOut;
      levels: FibLevel[];
      dropped_levels: { ratio: number; reason: string }[];
      nearest: Nearest;
      retracement_depth: number;
      beyond_swing: boolean;
      atr_multiple: number;
      calc_version: string;
      params_hash: string;
      input_hash: string;
    };

export type Rule = { rule: string; left?: number | null; right?: number | null; result?: boolean | null; points: number; [k: string]: unknown };
export type Component = { points: number; rules: Rule[]; weight: number; effective_weight: number; contribution: number; status?: string };

export type Score = {
  horizon: Horizon;
  status: "ok" | "insufficient_data";
  total: number | null;
  classification: Classification;
  components: Record<string, Component>;
  weights: Record<string, number>;
  excluded_components: string[];
  inputs: Record<string, number | null>;
  score_version: string;
  params_hash: string;
  input_hash: string;
};

export type IndicatorItem = { value: number | null; data_quality: "ok" | "insufficient_history" | "gap_in_window" | "not_applicable" };

export type Analysis = {
  status: "ok" | "insufficient_history" | "no_price_history";
  listing: ListingInfo;
  provenance: Provenance;
  bars_available: number;
  as_of?: string;
  sensitivity?: string;
  atr_multiple?: number;
  params_hash?: string;
  input_hash?: string;
  data_quality?: { calendar?: string; gaps: { after: string; before: string; missing_business_days: number }[]; volume_available: boolean; gap_threshold_business_days: number };
  latest?: { close: number; prev_close: number | null; indicators: Record<string, IndicatorItem> };
  swings?: SwingOut[];
  fibonacci?: Fibonacci;
  scores?: Record<Horizon, Score>;
  setups?: Setups;
  interval?: "1d" | "1w" | "1mo";
  timeframe?: { interval: string; last_bar_in_progress: boolean; last_period_start?: string; last_period_trading_days?: number };
  series?: Record<string, (number | null)[]> & { dates: string[] };
};

export type HoldingRow = {
  holding_id: number | string;
  status: string;
  account?: string;
  analysis_available?: boolean;
  analysis_note?: string | null;
  listing: Omit<ListingInfo, "id"> & { id: number | null };
  as_of: string;
  quantity: number;
  avg_cost: number;
  price: number;
  market_value_local: number;
  cost_basis_local: number;
  unrealised_pl_local: number;
  market_value_base: number;
  cost_basis_base: number;
  unrealised_pl_base: number;
  return_pct: number | null;
  nearest_fibonacci: Nearest | null;
  fibonacci_status: string;
  fibonacci_direction: "up" | "down" | null;
  classification: Record<Horizon, Classification>;
  scores: Record<Horizon, number | null>;
  short_score_change?: number;
  provenance: Provenance;
  data_gaps: unknown[];
  spark?: import("@/components/research/Sparkline").Spark;
};

export type FxUsed = { pair: string; rate: number; date: string; source: string; is_synthetic: boolean };
export type Totals = { market_value: number; cost_basis: number; unrealised_pl: number; return_pct: number | null };

export type HoldingsSource = "tracker" | "synthetic" | "ibkr_flex";

export type Portfolio = {
  base_currency: string;
  requested_base_currency?: string;
  holdings_source: HoldingsSource;
  status: "ok" | "not_synced";
  sync?: { report_date: string | null; finished_at: string | null; accounts: Record<string, string> };
  totals: Totals;
  holdings: HoldingRow[];
  fx_rates_used: FxUsed[];
  warnings: string[];
  provenance: Provenance;
};

export type IndexRow = {
  listing: ListingInfo;
  proxy_for?: string | null;
  spark?: import("@/components/research/Sparkline").Spark;
  status: string;
  as_of: string;
  close: number;
  change_1d_pct: number | null;
  change_1m_pct: number | null;
  change_ytd_pct: number | null;
  classification: Record<Horizon, Classification>;
  scores: Record<Horizon, number | null>;
  provenance: Provenance;
};

export type Overview = {
  base_currency: string;
  holdings_source: HoldingsSource;
  portfolio_provenance: Provenance;
  indices_provenance: Provenance;
  totals: Totals;
  best: HoldingRow[];
  weakest: HoldingRow[];
  near_fibonacci: HoldingRow[];
  deteriorating_momentum: HoldingRow[];
  deterioration_rule: string;
  indices: IndexRow[];
  fx_rates_used: FxUsed[];
  warnings: string[];
  provenance: Provenance;
};

export type SetupStatus = "triggered" | "not_triggered" | "insufficient_data" | "not_applicable";
export type SetupRule = { rule: string; left: number | null; right: number | null; result: boolean; value?: string; note?: string };
export type SetupItem = { id: string; name: string; direction: "bullish" | "bearish"; status: SetupStatus; rules: SetupRule[]; reason?: string };
export type Setups = { version: string; params_hash: string; input_hash: string; params: Record<string, unknown>; setups: SetupItem[]; triggered: string[] };
export type SetupCatalogItem = { id: string; name: string; direction: "bullish" | "bearish"; needs_volume: boolean };

export type ScanRow = {
  listing: ListingInfo;
  namespace: "real" | "synthetic";
  status: string;
  provenance: Provenance;
  bars_available: number;
  as_of?: string;
  input_hash?: string;
  close?: number;
  change_1d_pct?: number | null;
  change_1m_pct?: number | null;
  avg_volume20?: number | null;
  score_short?: number | null;
  score_medium?: number | null;
  score_long?: number | null;
  class_short?: Classification;
  class_medium?: Classification;
  class_long?: Classification;
  rank_short?: number;
  rank_medium?: number;
  rank_long?: number;
  rsi14?: number | null;
  relvol20?: number | null;
  triggered: string[];
  setups: Setups | null;
  held: boolean;
  watchlisted: boolean;
  note?: string | null;
  added_at?: string;
};

export type ScanRun = {
  id: number;
  started_at: string;
  finished_at: string | null;
  sensitivity: string;
  atr_multiple: number;
  setups_version: string;
  score_version: string;
  params_hash: string;
  universe_size: number;
  scanned: number;
  coverage: {
    by_source: Record<string, number>;
    by_exchange: Record<string, { name: string; total: number; scanned: number }>;
    not_scanned: { ticker: string; exchange: string; namespace: string; reason: string; bars_available: number }[];
    timeframe: string;
    note: string;
  };
};

export type ScanResp =
  | { status: "no_scan"; rows: ScanRow[]; setup_catalog: SetupCatalogItem[]; provenance: Provenance }
  | {
      status: "ok";
      run: ScanRun;
      rows: ScanRow[];
      setup_catalog: SetupCatalogItem[];
      freshness: { out_of_date: boolean; newer_bars: string[]; new_listings: number; removed_listings: number };
      provenance: Provenance;
    };

export type WatchlistResp = { rows: ScanRow[]; sensitivity: string; provenance: Provenance };

export type Settings = {
  settings: { base_currency: string; default_sensitivity: string; theme: "system" | "light" | "dark"; holdings_source: HoldingsSource };
  options: Record<string, string[]>;
};

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    // Research's API lives under /research/api/… in Portfolio Tracker's backend.
    res = await fetch(path.startsWith("/api/") ? `/research${path}` : path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("network", "Can't reach the app's backend. Is Portfolio Tracker running?", 0);
  }
  if (!res.ok) {
    let body: { error_code?: string; message?: string } = {};
    try {
      body = await res.json();
    } catch {}
    throw new ApiError(body.error_code ?? `http_${res.status}`,
      body.message ?? (res.status >= 500 ? "Backend unavailable. Is it running on port 8000?" : `Request failed (${res.status})`),
      res.status);
  }
  return res.json() as Promise<T>;
}

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    setError(null);
    apiFetch<T>(path)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

export type SyncRun = {
  id: number;
  source: string;
  status: "running" | "success" | "failed";
  error_code: string | null;
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
  report_date: string | null;
  accounts: Record<string, string> | null;
  positions_count: number;
  skipped: { symbol: string; asset_category: string; reason: string }[];
  warnings: string[];
};

export type IbkrStatus = {
  configured: boolean;
  query_id_masked: string | null;
  holdings_source: HoldingsSource;
  cooldown_seconds: number;
  runs: SyncRun[];
};

/** Notifies listeners (e.g. the banner) that the holdings source changed. */
export const SOURCE_EVENT = "fibonacci:holdings-source";

/** Notifies listeners (the nav badge) that alerts may have changed. */
export const ALERTS_EVENT = "fibonacci:alerts";
export const notifyAlerts = () => {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(ALERTS_EVENT));
};

export type AlertRow = {
  id: number;
  listing: ListingInfo;
  namespace: "real" | "synthetic";
  type: string;
  type_label: string;
  key: string;
  direction: "bullish" | "bearish" | "neutral";
  bar_date: string;
  created_at: string;
  title: string;
  details: Record<string, unknown>;
  read: boolean;
  read_at: string | null;
  source: string;
  is_synthetic: boolean;
  config_hash: string;
  input_hash: string;
};

export type AlertEval = {
  at: string;
  scope: "holdings_and_watchlist" | "all";
  listings: number;
  evaluated_listings: number;
  bars_evaluated: number;
  created: number;
  duplicates: number;
  suppressed_cooldown: number;
  skipped_unclosed_bars: number;
  skipped_backfill_bars: number;
  insufficient_history: string[];
  rotation?: { enabled: boolean; created: number; sectors: number; data?: string; benchmark?: string; timeframe?: string; status?: string };
  version: string;
};

export type AlertsResp = { alerts: AlertRow[]; unread: number; last_evaluation: AlertEval | null; labels: Record<string, string>; provenance: Provenance };

export type AlertConfig = {
  scope: "holdings_and_watchlist" | "all";
  cooldown_bars: number;
  rules: {
    fib_cross: { enabled: boolean };
    fib_approach: { enabled: boolean; atr: number };
    sma_cross: { enabled: boolean; periods: number[] };
    golden_death_cross: { enabled: boolean };
    rsi: { enabled: boolean; overbought: number; oversold: number };
    macd_cross: { enabled: boolean };
    relvol_spike: { enabled: boolean; min: number };
    score_change: { enabled: boolean; points: number; lookback: number };
    setup_new: { enabled: boolean };
    sector_rotation: { enabled: boolean; timeframe: string; benchmark: string; categories: string[]; regions: string[] };
  };
};

export type AlertConfigResp = {
  config: AlertConfig; defaults: AlertConfig; labels: Record<string, string>; sma_choices: number[];
  rotation_options: { timeframes: Record<string, string>; benchmarks: string[]; categories: Record<string, string>; regions: Record<string, string> };
  provenance: Provenance;
};

// ---------------------------------------------------------------- backtesting (Phase 7)

export type BtParamSpec = { choices: (number | string | boolean)[]; default: number | string | boolean; label: string; labels?: Record<string, string> };
export type BtStrategy = { id: string; name: string; description: string; params: Record<string, BtParamSpec>; grid_size: number };
export type BtStrategiesResp = {
  strategies: BtStrategy[];
  defaults: { commission_bps: number; slippage_bps: number; holdout_pct: number; folds: number; mode: string };
  warmup_bars: number;
  version: string;
  disclaimer: string;
};
export type BtMetrics = {
  bars: number; trades: number; win_rate_pct: number | null; avg_trade_pct: number | null; best_trade_pct: number | null;
  worst_trade_pct: number | null; avg_bars_held: number | null; total_return_pct: number | null; cagr_pct: number | null;
  max_drawdown_pct: number | null; sharpe_like: number | null; exposure_pct: number | null; fallback?: boolean;
};
export type BtTrade = {
  entry_date: string; entry_price: number; exit_date: string; exit_price: number; bars_held: number;
  return_pct: number; exit_reason: string; entry_note: string; open_at_end?: boolean;
};
export type BtSegment = {
  label: string; start_date: string; end_date: string; params: Record<string, unknown> | null;
  metrics: BtMetrics; buy_hold: BtMetrics; equal_weight?: BtMetrics;
  by_year: { year: number; strategy_pct: number; buy_hold_pct: number; equal_weight_pct?: number; trades_closed: number }[];
  trades: (BtTrade & { ticker?: string; sector?: string })[]; few_trades: boolean;
  curve: { dates: string[]; strategy: number[]; buy_hold: number[]; equal_weight?: number[] };
  time_in_sector_pct?: Record<string, number>;
};
export type BtFold = {
  fold: number; train: [string, string]; test: [string, string]; params: Record<string, unknown>;
  train_metrics: BtMetrics; test_metrics: BtMetrics; selection_fallback: boolean;
};
export type BtResult = {
  version: string; strategy: string; strategy_name: string; description: string; mode: "single" | "walk_forward";
  costs: { commission_bps: number; slippage_bps: number }; holdout_pct: number; warmup_bars: number; disclaimer: string;
  periods: { tradable_from: string; holdout_from: string; until: string };
  final_params: Record<string, unknown>; combinations_tested: number; folds?: BtFold[];
  main: BtSegment; holdout: BtSegment; notes: string[]; provenance: Provenance;
  kind?: "rotation"; benchmark?: string; sectors?: { ticker: string; sector: string }[]; region?: { id: string; name: string };
  namespace?: string; excluded_sectors?: { ticker: string; sector: string; bars_available: number }[]; aligned_bars?: number;
};
export type BtRun = { id: number; created_at: string; listing: ListingInfo; request: Record<string, unknown>; result: BtResult;
  version: string; params_hash: string; input_hash: string; provenance: Provenance };
export type BtRunSummary = {
  id: number; created_at: string; ticker: string; listing_id: number; namespace: string; strategy: string; strategy_name: string;
  mode: string; final_params: Record<string, unknown>; combinations_tested: number; main_return_pct: number | null;
  main_buy_hold_pct: number | null; holdout_return_pct: number | null; holdout_buy_hold_pct: number | null; is_synthetic: boolean;
  kind: "single" | "rotation"; main_equal_weight_pct: number | null; holdout_equal_weight_pct: number | null;
};
export type RotBtStrategiesResp = {
  strategies: BtStrategy[];
  regions: { id: string; name: string; benchmarks: string[]; default_benchmark: string; sectors: number }[];
  defaults: { commission_bps: number; slippage_bps: number; holdout_pct: number; folds: number; mode: string; region: string; data: string };
  version: string; disclaimer: string;
};
export type BtRunsResp = { runs: BtRunSummary[]; disclaimer: string; provenance: Provenance };

// ---------------------------------------------------------------- sector rotation

export type Quadrant = "leading" | "weakening" | "lagging" | "improving";
export type RrgPoint = { date: string; ratio: number; momentum: number; quadrant: Quadrant };
export type ScoreComponent = { points: number; input: number | string; rule: string; weight?: number; effective_weight?: number; contribution?: number; checks?: boolean[] };
export type RotationScore = { total: number | null; components: Record<string, ScoreComponent>; weights: Record<string, number>; status: string; excluded?: string[] };
export type SectorMetrics = {
  close: number | null; change_10d_pct: number | null; change_20d_pct: number | null; change_50d_pct: number | null;
  benchmark_change_20d_pct: number | null; relative_20d_pct: number | null; rsi14: number | null;
  sma10: number | null; sma20: number | null; sma50: number | null; sma200: number | null;
  above_sma10: boolean | null; above_sma20: boolean | null; above_sma50: boolean | null; above_sma200: boolean | null;
  volume_trend: number | null; volume_trend_label: "rising" | "falling" | "flat" | null; absolute_trend: "up" | "down" | "mixed" | null;
};
export type RotationEvent = {
  date: string; sessions_ago: number; ratio: number; momentum: number; kind: "quadrant" | "momentum_cross" | "ma_cross";
  from?: Quadrant; to?: Quadrant; category: string; label: string; ticker?: string; sector?: string;
};
export type SectorRow = {
  ticker: string; sector: string; etf_name: string; listing_id: number | null; bars_available: number; held?: boolean;
  status: "ok" | "no_price_history" | "insufficient_history" | "rrg_unavailable"; reason?: string;
  provenance?: Provenance; data_gaps?: { after: string; before: string; missing_business_days: number }[];
  ratio?: number; momentum?: number; quadrant?: Quadrant; trail?: RrgPoint[]; metrics?: SectorMetrics;
  events?: RotationEvent[]; score?: RotationScore; rank?: number; dates_dropped_by_alignment?: number;
};
export type SectorsResp = {
  status: string; region: { id: string; name: string; classification: string; currency: string; price_provider: string };
  regions: { id: string; name: string }[]; data: "real" | "synthetic"; data_requested: string;
  real_data_availability: { benchmark_bars: number; sectors_with_history: number; usable: boolean };
  benchmark: string; benchmarks: string[];
  benchmark_info: { ticker: string; name: string; listing_id: number; close: number | null; change_20d_pct: number | null;
    change_50d_pct: number | null; absolute_trend: string | null; above_sma50: boolean | null; above_sma200: boolean | null;
    classification: Record<string, Classification>; provenance: Provenance } | null;
  timeframe: string; timeframes: Record<string, string>; trails: number[]; bars_needed: number; aligned_bars: number; as_of: string | null;
  rows: SectorRow[]; quadrant_counts: Record<Quadrant, number>;
  highlights: Record<"most_attractive" | "strongest_improving" | "weakest" | "strongest_rs" | "weakest_rs", SectorRow | null>;
  events: RotationEvent[]; event_categories: Record<string, string>;
  score: { weights: Record<string, number>; labels: Record<string, string>; defaults: Record<string, number> };
  last_refresh: { at: string; session?: string } | null;
  method: { version: string; rotation_version: string; windows: { label: string; window: number; momentum_lag: number; smoothing: number } };
  notes: string[]; provenance: Provenance;
};
export type Constituent = {
  listing_id: number; ticker: string; name: string; namespace: string; held: boolean; watchlisted: boolean; bars_available: number;
  status: string; close?: number; change_20d_pct?: number | null; relative_to_sector_20d_pct?: number | null; as_of?: string;
  rs_ratio_vs_sector?: number | null; rs_momentum_vs_sector?: number | null; quadrant_vs_sector?: Quadrant | null;
  beats_sector?: boolean | null; rrg_note?: string; provenance?: Provenance;
};
export type SectorDetail = {
  ticker: string; sector: string; etf_name: string; data: "real" | "synthetic"; benchmark: string; timeframe: string;
  timeframes: Record<string, string>; benchmarks: string[]; row: SectorRow; listing_id: number | null; notes: string[];
  provenance: Provenance; event_categories: Record<string, string>; score_labels: Record<string, string>;
  trail?: RrgPoint[]; relative_chart?: { dates: string[]; sector: number[]; benchmark: number[]; relative: number[] };
  holdings: { source: string; as_of: string | null; fetched_at: string | null; count: number; top10_weight_pct: number | null;
    top10: { rank: number; name: string; ticker: string | null; weight_pct: number; exchange?: string | null; price_supported?: boolean;
      analysis?: Constituent | null }[];
    missing_prices: string[]; unsupported_exchanges?: string[] };
  region?: { id: string; name: string; classification: string; currency: string; price_provider: string };
  constituents_in_app: Constituent[]; strongest: Constituent[]; weakest: Constituent[]; beating_sector: Constituent[];
};
