# Phase 7 Task: Backtesting

> Read `PROJECT_BRIEF.md` first; every rule in it still applies. Implement only this file.
> When every acceptance criterion in §7 passes, write the report and **stop**.

## 0. Goal

Let the user test simple Fibonacci, moving-average, RSI, MACD and setup strategies on one
instrument's stored daily history, honestly: closed bars only, data as known at the time,
realistic costs, walk-forward validation, an untouched holdout period, and a disclosure of how
many parameter combinations were tried. Every report says **"Past performance does not
guarantee future results."** This is research, not a trading system: nothing is executed.

**Out of scope:** portfolios of several instruments, short selling, leverage, position sizing
other than "all in / all out", intraday data, weekly/monthly strategies, optimisation beyond the
fixed parameter grids below.

## 1. Engine (`app/engine/backtest.py`, `BACKTEST_VERSION = "backtest-v1"`)

- **Event-driven, daily, long only.** At each bar's close the strategy looks only at data up to
  that bar (the Phase 1 indicator arrays, and swings *confirmed* by that bar) and decides. Orders
  fill at the **next bar's open**.
- **Stops and targets** (Fibonacci strategy) are checked on each bar's high/low from the entry bar
  on. A gap through the level fills at the open. If stop and target are both touched in one bar,
  the **stop** is assumed (conservative).
- **Costs per side:** commission 5 bps and slippage 10 bps by default (30 bps per round trip),
  configurable from 0 to 200 bps each. Slippage worsens every fill.
- **Warm-up:** the first 200 bars are never traded (SMA 200 must exist), for every strategy, so
  results are comparable.
- A position still open at the end of a window is closed at the last close (with costs) and marked.

### Strategies and parameter grids

| Id | Rule | Grid |
|---|---|---|
| `ma_cross` | Enter when SMA fast crosses above SMA slow; exit when it crosses below | fast ∈ {10, 20, 50}, slow ∈ {50, 100, 200}, fast < slow (8) |
| `rsi_reversion` | Enter when RSI 14 closes below *entry*; exit when it closes above *exit* or after 20 bars | entry ∈ {25, 30, 35}, exit ∈ {50, 60, 70} (9) |
| `macd_cross` | Enter when the MACD line crosses above its signal; exit on the cross below. Optional filter: close above SMA 200 | filter ∈ {off, on} (2) |
| `fib_pullback` | In a confirmed up swing, a bar's low comes within *tolerance* ATR of the *level* retracement and closes above it, as an up bar. Stop = swing low (100%), target = swing high (0%) | level ∈ {0.5, 0.618}, tolerance ∈ {0.25, 0.5, 1.0} ATR (6) |
| `setup_hold` | Enter when a Phase 4 bullish setup newly triggers; exit after *hold* bars | setup ∈ {6 bullish setups}, hold ∈ {5, 10, 20} (18) |

## 2. Validation

- **Holdout:** the last *holdout %* (default 20%) of tradable bars is never used for choosing
  parameters. It is evaluated exactly once, with the final parameters, and reported separately.
- **Single mode:** the user's parameters, reported on the in-sample period and the holdout.
  Combinations tested: 1.
- **Walk-forward mode:** the pre-holdout period is split into *folds + 1* equal blocks (each at
  least 60 bars). A position still open at the end of a test block is closed there. For fold
  *i*, every grid combination is run on blocks 0..i−1 (anchored training). The best by Sharpe-like
  ratio (at least 3 trades, ties go to the first in grid order) is run on block *i* (out of sample).
  The out-of-sample blocks are stitched into one result. Final parameters = best on the whole
  pre-holdout period, then run once on the holdout.
- **Disclosure:** combinations tested = grid size × (folds + 1), shown on every walk-forward report.

## 3. Report

For each evaluated period (in-sample or out-of-sample, holdout): number of trades, win rate,
average trade return, total return, CAGR, max drawdown, Sharpe-like ratio (daily, rf = 0,
√252), exposure (% of bars invested), buy-and-hold over the same bars with the same costs,
results per calendar year, the trade list, and the equity curve. Plus provenance (synthetic or
real, source, adjusted prices), costs, parameters, `params_hash`, `input_hash` and version.

## 4. Storage and API

- `backtest_runs`: created_at, listing, strategy, mode, request JSON, result JSON, version,
  params_hash, input_hash. Re-running the same request on the same bars gives an identical result.
- `GET /api/backtest/strategies`, `POST /api/backtest/run`, `GET /api/backtest/runs`,
  `GET /api/backtest/runs/{id}`, `DELETE /api/backtest/runs/{id}`. Every response carries provenance.

## 5. UI

A **Backtesting** page: choose instrument, strategy, mode, parameters (single mode), costs,
holdout %, folds. The result shows a summary against buy-and-hold, an equity chart (strategy vs
buy-and-hold, holdout shaded), walk-forward folds, per-year results, trades, the disclosure box and
the past-performance warning. Saved runs are listed.

## 6. Honesty notes shown in the UI

Synthetic data is labelled. Real data uses dividend-adjusted prices, which suits returns but not
absolute price levels. The instrument list is what's stored in the app (survivorship bias). One
instrument and a short history make results fragile, and the UI says so when there are fewer than
10 trades.

## 7. Acceptance criteria

1. Each strategy has tests for its entry/exit rules on constructed data.
2. No look-ahead: trades up to bar *T* are identical on full history and on history truncated at *T*.
3. Fills: next-bar open, costs on both sides, gap-through stops, stop-first when both are touched.
4. Metrics checked against hand calculations (drawdown, CAGR, win rate, exposure, buy-and-hold).
5. Walk-forward never uses holdout bars for selection (tested), and the combination count is correct.
6. A run is stored and reproducible; every endpoint returns provenance; validation rejects bad input.
7. Backend and frontend tests, lint and build pass; browser check at desktop and 390 px.
8. Docs updated (README, ROADMAP, DEVELOPMENT decisions, ARCHITECTURE).
