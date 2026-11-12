# Phase 4 Task: Opportunity scanner and watchlist

> Read `PROJECT_BRIEF.md` first; every rule in it still applies. Implement only this
> file. When every acceptance criterion in §8 passes, write the Phase 4 report and **stop**.

## 0. Goal

Scan the instruments the app actually has price data for. Detect a small set of
documented technical *setups*, rank the results by the existing transparent score,
and let the user keep a watchlist. Nothing here is a buy or sell signal.

**Out of scope:** new data providers, market-cap data, weekly/monthly timeframes
(Phase 2b), alerts (Phase 6), AI text (Phase 5), backtesting the setups (Phase 7).

## 1. Universe and coverage (honesty first)

- The universe is every listing in the database (synthetic demo + real Tiingo
  listings). The scanner never claims coverage of a whole exchange.
- Every scan reports: universe size, listings scanned, listings with enough history,
  listings without data (and why), counts per data source and exchange, the scan
  time (UTC), and the latest bar date used per listing.
- **Freshness:** a stored scan is *out of date* when any listing now has a newer bar
  than the one the scan used, or new listings exist. The UI says so and offers a re-scan.
- Synthetic and real rows are labelled as today (Synth / Real badge).

## 2. Setup detectors (`app/engine/setups.py`, `SETUPS_VERSION = "setups-v1"`)

Pure functions over arrays that end at the scan bar `t` (no look-ahead). Each
detector returns `status` (`triggered` | `not_triggered` | `insufficient_data` |
`not_applicable`), `direction` (`bullish` | `bearish`), and every rule with its
left/right values and result, so the UI can show exactly why. All thresholds live
in one `PARAMS` dict, which is hashed into `params_hash`.

| Id | Name | Rules (all must hold at bar *t*) |
|---|---|---|
| `bullish_reversal` | Potential bullish reversal | min RSI14 over bars *t-5..t-1* < 30; RSI14[t] ≥ 30; MACD hist[t] > MACD hist[t-3] |
| `bearish_reversal` | Potential bearish reversal | max RSI14 over *t-5..t-1* > 70; RSI14[t] ≤ 70; MACD hist[t] < MACD hist[t-3] |
| `fib_support` | Approaching Fibonacci support | up swing; nearest retracement level (0.236–0.786) is below price, within 1 ATR; close[t] < close[t-5] |
| `fib_resistance` | Approaching Fibonacci resistance | down swing; nearest retracement level (0.236–0.786) is above price, within 1 ATR; close[t] > close[t-5] |
| `breakout` | Potential breakout | close[t] > highest high of *t-20..t-1*; relvol20[t] ≥ 1.5 |
| `breakdown` | Potential breakdown | close[t] < lowest low of *t-20..t-1*; relvol20[t] ≥ 1.5 |
| `bullish_ma` | Bullish MA alignment | close > SMA20 > SMA50 > SMA200; SMA50[t] > SMA50[t-5] |
| `bearish_ma` | Bearish MA alignment | close < SMA20 < SMA50 < SMA200; SMA50[t] < SMA50[t-5] |
| `momentum_up` | Momentum acceleration (up) | MACD hist[t] > 0; hist rose on each of the last 3 bars |
| `momentum_down` | Momentum acceleration (down) | MACD hist[t] < 0; hist fell on each of the last 3 bars |
| `accumulation` | Potential accumulation | over *t-19..t*: up-day volume ÷ down-day volume ≥ 1.5; abs(close[t]/close[t-20] − 1) ≤ 5% |
| `distribution` | Potential distribution | over *t-19..t*: down-day volume ÷ up-day volume ≥ 1.5; abs(close[t]/close[t-20] − 1) ≤ 5% |

- Volume-based detectors return `not_applicable` for indices (no volume).
- Fibonacci detectors use the same confirmed-swing Fibonacci result as the analysis page.
- Missing warm-up values give `insufficient_data`, never a guess.

## 3. Ranking and filters

- Rank = the existing score v1 total for the chosen horizon (short / medium / long),
  descending; ties broken by ticker. The score breakdown stays one click away.
- Timeframe: daily only (weekly/monthly arrive with Phase 2b). Shown, not hidden.
- Filters (client-side, existing `DataTable`): data source, exchange, sector, asset
  class, currency, average 20-day volume, score, classification, setup, held, watchlist.
- Market cap: no provider supplies it yet, so there is no market-cap filter (rule 16).

## 4. Storage and reproducibility

- `scan_runs`: started/finished (UTC), sensitivity, setups version, params hash,
  universe/scanned counts, coverage JSON.
- `scan_results`: one row per (run, listing): bar date used, `input_hash`, scores,
  triggered setup ids, and the full detector output JSON.
- Re-running on unchanged bars gives identical results (tested).

## 5. Watchlist

- `GET /api/watchlist`, `POST /api/watchlist {listing_id, note}`, `PATCH /api/watchlist/{listing_id} {note}`,
  `DELETE /api/watchlist/{listing_id}` using the existing `watchlist_items` table.
- Watchlist page: each item with its latest close, scores, triggered setups and note.
- Star toggle on Scanner rows and on the analysis page.

## 6. API

- `POST /api/scanner/run {sensitivity?}` runs and stores a scan; returns it. The ranking horizon is chosen in the UI.
- `GET /api/scanner` returns the latest stored scan with freshness, or `status: "no_scan"`.
- Each listing's analysis response gains a `setups` block (same detector output).
- Every response carries `provenance`.

## 7. UI

- New nav items **Opportunity Scanner** and **Watchlist** (built sections only).
- Scanner: coverage panel, last-scan time + freshness, *Run scan*, horizon selector,
  results table with setup chips and presets per setup, and a details panel showing
  every rule of every detector for the selected row.
- Analysis page: a "Setups" section with the same rule breakdown.
- Text everywhere: setups are *conditions to research*, not recommendations.
- Empty, loading, error, stale and synthetic states on every new view.

## 8. Acceptance criteria

1. Each detector has unit tests for triggered, not triggered and insufficient data.
2. No look-ahead: detector output at bar *t* is identical on full and truncated history.
3. A scan stores a run and per-listing results; re-running on unchanged data is identical.
4. Coverage counts and freshness are correct (tested, including the out-of-date case).
5. Indices give `not_applicable` for volume detectors.
6. Watchlist add / note / remove works through the API and UI.
7. Every new endpoint returns `provenance`.
8. Backend tests, frontend lint, tests and build pass. Checked in a browser at desktop
   and 390 px width with no horizontal overflow.
9. Docs updated: README, ROADMAP, DEVELOPMENT (decisions), ARCHITECTURE.
