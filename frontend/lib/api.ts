"use client";

import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("network", "Can't reach the app's backend. Is ./scripts/dev.sh running?", 0);
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* not JSON */
  }
  if (!res.ok) {
    const b = body as { error?: string; message?: string; detail?: unknown } | null;
    const msg = b?.message ?? (typeof b?.detail === "string" ? b.detail : null) ?? (res.status >= 500 ? "The backend isn't responding (is it running on port 8001?)." : `HTTP ${res.status}`);
    throw new ApiError(b?.error ?? `http_${res.status}`, msg, res.status);
  }
  return body as T;
}

export const jsonInit = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!path) return;
    let live = true;
    setError(null);
    apiFetch<T>(path).then((d) => live && setData(d)).catch((e) => live && setError(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0)));
    return () => { live = false; };
  }, [path, n]);
  const reload = useCallback(() => setN((x) => x + 1), []);
  return { data, error, reload, setData };
}

export const STATUS_EVENT = "pt-status-changed";
export const notifyStatus = () => window.dispatchEvent(new Event(STATUS_EVENT));

// ---------------------------------------------------------------- types

export type Accounting = {
  position_rows: number; open_buys: number; closed_buys: number; sales: number; excluded: number; not_classified: number;
  rows_pending: number; review_pending: number; sales_log_rows: number; sales_log_linked: number; sales_log_unlinked: number;
};
export type Status = { imported: false } | {
  imported: true; filename: string; uploaded_at: string; saved_at: string | null; as_of: string; sheet: string; sha256: string;
  position_rows: [number, number]; sales_rows: [number, number] | null; accounting: Accounting; review_pending: number;
  review_by_kind: Record<string, number>; trades: number; stale_decisions: string[];
  fx: { status: string; message?: string; latest?: string; at?: string } | null; fx_latest: string | null;
};
export type ReviewItem = {
  key: string; kind: string; row: number; title: string; detail: string; status: "pending" | "resolved";
  decision: Record<string, unknown> | null; actions: string[];
  data: {
    date?: string; name?: string; shares?: number; price?: number; sell_price?: number | null; live_price?: number | null;
    currency?: string; broker?: string; status?: string; sheet_cost?: number | null; sheet_pl?: number | null; sales_log_rows?: number[];
    stock?: string; sheet_pl_pct?: number | null; sheet_pl_usd?: number | null; formula?: string | null;
    missing_shares?: number; leftover_shares?: number;
  };
};
export type ReviewResp = { items: ReviewItem[]; kinds: Record<string, string>; counts: { pending: Record<string, number>; resolved: Record<string, number> } };
export type Match = {
  buy_id: string; buy_row: number; buy_date: string; broker: string; shares: number; buy_price: number; cost_local: number;
  cost_usd: number | null; buy_rate: number | null; buy_rate_date: string | null; days_held: number;
};
export type Sale = {
  id: string; row: number; sale_row: number | null; date: string; stock: string; stock_key: string; currency: string; broker: string;
  shares: number; price: number; proceeds_local: number; proceeds_usd: number | null; sell_rate: number | null; sell_rate_date: string | null;
  matches: Match[]; cost_local: number; cost_usd: number | null; gain_local: number | null; gain_usd: number | null; gain_pct: number | null;
  price_effect_usd: number | null; fx_effect_usd: number | null; days_held: number | null; sheet_pl: number | null;
  unmatched_shares: number; problems: string[];
};
export type SalesYear = { year: number; sales: number; gain_usd: number; wins: number; losses: number; not_computed: number; sheet_pl: number };
export type SalesResp = {
  sales: Sale[]; by_year: SalesYear[]; as_of: string; method: string;
  totals: { sales: number; gain_usd: number; not_computed: number; proceeds_usd: number; cost_usd: number };
};
export type Lot = { buy_id: string; row: number; date: string; broker: string; shares: number; price: number; cost_local: number; cost_usd: number | null; days_held: number };
export type Position = {
  stock: string; stock_key: string; currency: string; lots: Lot[]; shares: number; cost_local: number; cost_usd: number | null;
  avg_cost: number | null; price: number | null; price_from_row: number | null; price_date: string | null; price_source: string | null;
  pool: string; pence: boolean; value_local: number | null; value_usd: number | null;
  rate: number | null; rate_date: string | null; unrealised_usd: number | null; unrealised_pct: number | null; days_held: number | null;
  weight_pct: number | null;
};
export type PositionsResp = { positions: Position[]; as_of: string; sheet_as_of: string; price_note: string;
  totals: { value_usd: number; cost_usd: number; unrealised_usd: number; not_computed: number } };
export type CheckLine = { row: number; date: string; stock: string; sheet: number | null; app: number; difference: number; match: boolean; position_rows: number[]; causes: string[] };
export type CheckResp = {
  sales_log: { total_sheet: number; total_app: number; difference: number; lines: number; lines_matching: number;
    by_year: { year: number; sheet: number; app: number; sales: number; matched: number; difference: number }[]; differences: CheckLine[] };
  open_positions: { stocks: number; stocks_matching: number; sheet_cost: number; app_cost: number; sheet_pl: number; app_pl: number;
    rows: { stock: string; currency: string; rows: number[]; sheet_cost: number; app_cost: number; sheet_pl: number; app_pl: number; not_imported: number[]; match: boolean }[] };
  accounting: Accounting; note: string;
};
export type StockGroup = { group_key: string; display_name: string; ticker: string | null; names: { name_key: string; as_written: string[]; rows: number }[];
  rows: number; open_rows: number; currencies: string[] };
export type StocksResp = { stocks: StockGroup[]; suggestions: { name_key: string; group_key: string; as_written: string[] }[][] };

// ---------------------------------------------------------------- phase 2: analysis

export type BriefSale = { id: string; date: string; stock: string; gain_usd: number; gain_pct: number | null; days_held: number | null; currency: string };
export type Statistics = {
  sales: number; not_computed: number; wins: number; losses: number; breakeven: number; win_rate_pct: number | null;
  gross_wins_usd: number; gross_losses_usd: number; net_usd: number; avg_win_usd: number | null; avg_loss_usd: number | null;
  avg_win_pct: number | null; avg_loss_pct: number | null; profit_factor: number | null; expectancy_usd: number | null;
  avg_days_winners: number | null; avg_days_losers: number | null; fx_effect_usd: number;
  by_holding_period: { label: string; sales: number; gain_usd: number; win_rate_pct: number | null; cost_usd: number; return_pct: number | null }[];
  best_sales: BriefSale[]; worst_sales: BriefSale[];
};
export type YearRow = {
  year: number; sales: number; not_computed: number; gain_usd: number; wins: number; losses: number; cost_usd: number; proceeds_usd: number;
  avg_invested_usd: number | null; return_on_invested_pct: number | null; win_rate_pct: number | null;
  capital_start_usd?: number; capital_added_usd?: number; return_on_capital_pct?: number | null; dividends_usd: number; income_usd: number;
};
export type Alloc = { label: string; value_usd: number; pct: number | null };
export type Analysis = {
  as_of: string; statistics: Statistics; months: { month: string; sales: number; gain_usd: number; wins: number; proceeds_usd: number }[];
  years: YearRow[]; timeline: { date: string; invested_usd: number; realised_cum_usd: number }[];
  returns: {
    realised_usd: number; unrealised_usd: number | null; dividends_usd: number; total_gain_usd: number;
    money_in_shares: { xirr_pct: number | null; cost_of_shares_sold_usd: number; return_on_cost_sold_pct: number | null; explain: string };
    capital: null | { deposits_usd: number; withdrawals_usd: number; net_usd: number; end_value_usd: number; simple_return_pct: number | null; xirr_pct: number | null; explain: string };
  };
  allocation: { by_broker: Alloc[]; by_currency: Alloc[]; by_stock: Alloc[] };
  open: { value_usd: number; cost_usd: number; unrealised_usd: number; positions: number };
  capital_entries: number; capital_problems: string[]; review_pending: number; limits: string;
  dividends: { total_usd: number; count: number };
};
export type StockRow = {
  pool: string; stock: string; stock_key: string; currency: string; buys: number; sells: number; shares_bought: number; shares_sold: number;
  bought_usd: number; realised_usd: number; realised_not_computed: number; open_shares: number; value_usd: number | null; unrealised_usd: number | null;
  first: string | null; last: string | null; avg_buy_price: number | null; avg_sell_price: number | null; total_usd: number; total_return_pct: number | null;
  status: "open" | "closed"; dividends_usd: number;
};
export type StockDetail = {
  pool: string; summary: StockRow | null; position: Position | null; as_of: string;
  trades: { kind: "buy" | "sell"; date: string; shares: number; price: number; row: number; broker: string; value_usd: number | null;
    gain_usd: number | null; gain_pct?: number | null; days_held?: number | null; id: string; matches?: Match[] }[];
};
export type CapitalFlowRow = { id: number; date: string; amount: number; currency: string; account: string | null; note: string | null; usd: number | null; rate: number | null };
export type CashBlock = { header_row: number; title: string | null; rows: { row: number; label: string | null; original: number | null; usd: number | null }[]; totals: { row: number; label: string; usd: number }[] };
export type CapitalResp = { flows: CapitalFlowRow[]; problems: string[]; sheet_cash: CashBlock[]; sheet_cash_note: string };

// ---------------------------------------------------------------- phase 3: trades, dividends, prices

export type TradeRow = {
  id: string; kind: "buy" | "sell"; date: string; stock: string; stock_key: string; pool: string; shares: number; price: number;
  currency: string; pence: boolean; broker: string; fee: number; source: "sheet" | "app"; row: number | null; sale_row: number | null;
  note: string | null; gain_usd: number | null; editable: boolean; correctable: boolean; fee_stored: number | null;
};
export type TradesResp = { trades: TradeRow[]; stocks: string[]; stale_fees: string[]; currencies: string[]; as_of: string };
export type DividendRow = { id: number; date: string; name: string; stock_key: string; amount: number; tax: number; currency: string; usd: number | null; note: string | null };
export type DividendsResp = { dividends: DividendRow[]; problems: string[]; total_usd: number; by_year: { year: number; usd: number }[]; by_stock: { name: string; usd: number }[] };
export type PriceRow = { pool: string; stock: string; currency: string; pence: boolean; shares: number; price: number | null; price_date: string | null;
  price_source: string | null; value_usd: number | null; history: { id: number; price: number; date: string; source: string }[] };
export type PricesResp = { prices: PriceRow[]; sheet_as_of: string; as_of: string; updated?: number; workbook_saved?: string; not_held?: string[]; no_price_in_workbook?: string[] };

// ---------------------------------------------------------------- index comparison

export type IndexStatus = { id: string; name: string; symbol: string; currency: string; points: number; first: string | null; last: string | null };
export type IndexCompare = {
  realised: { sales: number; compared: number; cost_usd: number; gain_usd: number; index_gain_usd: number; beat: number; not_compared: number };
  open: null | { lots: number; compared: number; cost_usd: number; index_gain_usd: number; not_compared: number };
};
export type IndexRow = {
  id: string; name: string; currency: string; available: boolean; change_pct?: number | null; change_usd_pct?: number | null;
  from?: string | null; to?: string | null; compare?: IndexCompare;
  same_money?: null | { index_end_value_usd: number | null; your_end_value_usd: number | null; index_xirr_pct: number | null; your_xirr_pct: number | null;
    trades_not_priced: number; ran_out: string | null };
};
export type BenchmarksResp = {
  period: { start: string; end: string; all_time: boolean; first_trade: string; valuation: string };
  indexes: IndexRow[]; status: IndexStatus[];
  index_chart: { dates: string[]; lines: Record<string, (number | null)[]> };
  cumulative: { dates: string[]; yours: number[]; index: Record<string, number[]> };
  open: null | { unrealised_usd: number; value_usd: number };
  note: string; review_pending: number;
};
export type RefreshResp = { results: { id: string; ok: boolean; points?: number; last?: string; message?: string }[]; indexes: IndexStatus[] };
