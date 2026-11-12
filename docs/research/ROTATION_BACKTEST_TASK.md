# Rotation backtest: do the sector-rotation signals actually work?

> Read `PROJECT_BRIEF.md`, `PHASE_7_TASK.md` and `SECTOR_ROTATION_TASK.md` first; all rules still apply.
> Past performance does not guarantee future results.

## 0. Goal

Test the Sector Rotation module's own rules on stored history, as a **portfolio of sector ETFs**,
against two honest comparisons:
- **buy-and-hold of the benchmark** (SPY or EXSA)
- **equal weight in every sector ETF**, held throughout. This separates "picking sectors" from "being in sectors at all".

## 1. Strategies (reuse `engine/rrg.py` and `engine/rotation.py`, unchanged)

| Id | Rule at each close | Grid |
|---|---|---|
| `quadrant_hold` | Hold every sector whose RRG quadrant is in the chosen set, equal weight; hold cash (0%) when none qualifies. Sectors are bought when they enter the set and sold when they leave it. | set ∈ {Improving, Improving + Leading, Leading}; timeframe ∈ {1 month, 3 months} (6) |
| `top_score` | Every *k* sessions, hold the top *N* sectors by Rotation Signal Score (default weights), equal weight | N ∈ {2, 3, 5}; k ∈ {5, 10, 21}; timeframe ∈ {1 month, 3 months} (18) |

## 2. Mechanics (same rules as Phase 7)

- **Data:** daily bars aligned on common dates across the benchmark and all sector ETFs; the same
  real/synthetic choice as the module (never mixed).
- **Timing:** decisions at the close of bar *t* use only data up to *t*; rebalancing happens at the
  **next open**. Weights drift between rebalances.
- **Costs:** commission + slippage per side (default 5 + 10 bps) on the value traded at each rebalance.
  The comparisons pay the same costs on their entry and exit.
- **Warm-up:** max(200, bars the RRG needs for the timeframe) bars are never traded.
- **Trades:** each sector holding from entry to exit is one trade (with a return net of its share of costs).

## 3. Validation (same as Phase 7)

- Holdout: the last 10–40% of tradable bars (default 20%), never used for selection, evaluated once.
- Single mode: the user's parameters; 1 combination.
- Walk-forward: anchored folds (each block 60+ bars), selection by Sharpe-like ratio with at least 3
  trades; combinations tested = grid × (folds + 1), disclosed.

## 4. Report

The Phase 7 report (trades, win rate, average trade, total return, CAGR, max drawdown, Sharpe-like,
exposure, per year, equity curve) plus an **equal-weight sectors** column; the share of time in each
sector; and notes (synthetic data, one region, survivorship, few trades, "RRG approximation"). Stored in
`backtest_runs` (strategy `rotation:<id>`, listing = the benchmark) and listed with the other backtests.

## 5. Acceptance criteria

1. Engine tests on constructed series: entries and exits on quadrant changes, top-N selection and
   rebalancing cadence, costs on turnover, cash when nothing qualifies, comparisons by hand.
2. No look-ahead: results up to bar *T* are identical on full and truncated history.
3. Walk-forward never selects on holdout bars; the combination count is correct; runs are reproducible.
4. API with provenance and validation; works for the US and Europe on the synthetic demo; real-data path
   tested with a simulated provider.
5. UI on the Backtesting page; browser check at desktop and 390 px; docs updated.
