# Architecture (Phase 1)

```
Browser (Safari/Chrome/iPad/iPhone)
   │  only talks to Next.js; /api/* is proxied server-side
   ▼
Next.js 15 (React 19, TypeScript, Tailwind 4, Lightweight Charts 5)   :3000
   │  HTTP JSON
   ▼
FastAPI  app/api/routes.py                                            :8000
   │
   ├── services/analysis.py   load bars ≤ as_of → engine → provenance, data quality, hashes
   ├── services/portfolio.py  Decimal valuation, dated FX via USD pivot
   ├── services/overview.py   index strip, best/weakest, near-Fib, deteriorating momentum
   ├── services/scanner.py    scan runs (stored in scan_runs / scan_results), coverage, freshness, watchlist
   ├── services/alerts.py     closed-bar evaluation, dedup, cooldown, alerts / alert_state tables
   │
   ├── engine/  (pure NumPy, no I/O, fully unit-tested)
   │     indicators.py  SMA, EMA, RSI(Wilder), MACD, ATR(Wilder), relative volume, ROC
   │     swings.py      ATR ZigZag with confirmed_index (no look-ahead)
   │     fibonacci.py   retracements/extensions from last two confirmed swings
   │     scoring.py     score v1: weights, rules, renormalisation, classification
   │     setups.py      12 setup detectors (setups-v1), each returning every rule it checked
   │     alerts.py      9 alert transition rules (alerts-v1) and config validation
   │     backtest.py    event-driven daily backtester (backtest-v1): 5 strategies, walk-forward, holdout
   │     rrg.py         RRG-inspired RS-Ratio / RS-Momentum (z-scores around 100), quadrants, trails
   │     rotation.py    sector metrics, rotation transitions, Rotation Signal Score
   │     rotation_backtest.py  rotation rules as an equal-weight sector ETF portfolio (rotation-backtest-v1)
   │
   ├── engine/resample.py weekly/monthly bars from daily bars on the exchange calendar
   ├── market_data/       tiingo.py (US), eodhd.py + eu_service.py (Europe), ecb.py + fx.py (FX)
   ├── data/synthetic.py  deterministic regime-switching GBM (sha256 seed, fixed end date)
   └── db/ (SQLAlchemy 2.x, Alembic) ──► SQLite now, PostgreSQL later (URL change only)
```

## Key decisions

| Decision | Why |
|---|---|
| **Calculate on request; persist the latest result** | 600 daily bars × 15 listings calculates in milliseconds, so every response can be reproduced from the stored bars. The seed step also stores the latest indicators, swings, Fibonacci result and scores in their tables, with `params_hash` and `input_hash`. A test checks that recalculating gives the same values. |
| **Truncate history at `as_of` before calculating** | This is the simplest structural guarantee against look-ahead. Separate tests check that full-history calculations at *t* match truncated calculations at *t*. |
| **Indicators implemented directly** | Each convention is pinned down and documented. TA-Lib is an optional test-only cross-check, so there's no C-library dependency at runtime. |
| **Instrument (ISIN) separate from Listing (exchange + ticker + currency)** | Tickers aren't unique (e.g. VWRL trades on several exchanges). |
| **FX via a USD pivot** with the stored EURUSD and USDCHF rates | Two pairs are enough to convert USD, EUR and CHF in any direction. Each rate used is returned with its date. |
| **Next.js rewrites `/api/*` to the backend** | The browser never needs the backend URL or any credentials, and no CORS setup is needed in the browser. |
| **Client-side data fetching** | Phase 1 is a single-user local tool. Every view handles loading, error, empty, stale and synthetic states explicitly. |
| **Lightweight Charts v5 panes** | Price, volume, RSI and MACD share one time axis, so crosshair and zoom stay in sync. |

## Provenance contract

Every API response includes:
`provenance = {source, is_synthetic, as_of (UTC), exchange_timezone, is_delayed, delay_minutes, stale}`.
For synthetic data, `stale` is measured against `SYNTHETIC_END_DATE`. For real data
it will be measured against today.

## Moving to PostgreSQL

Set `DATABASE_URL=postgresql+psycopg://…`, add `psycopg[binary]` to the requirements,
then run `alembic upgrade head`. The models use portable types only.

## Scanner (Phase 4)

`POST /api/scanner/run` evaluates every listing with the same `compute_analysis` used by the
analysis page (setups are part of that response), and stores one `scan_results` row per
listing with its bar date and `input_hash`. `GET /api/scanner` reads the latest stored run
(fast) and compares each stored bar date with the newest bar now in the database to say
whether the scan is out of date. Ranks are computed at read time; held and watchlist flags
too, because they can change without new prices.

## Alerts (Phase 6)

Alerts are evaluated after every price refresh (`/api/refresh`, `/api/market-data/refresh`,
`/api/listings/{id}/refresh`) and on `POST /api/alerts/evaluate`. There is no background
scheduler. For each listing in scope, bars whose session hasn't finished are dropped
(exchange clock + 2 h). Then every closed bar after `alert_state.last_bar_date` (at most 10)
is compared with the bar before it. A failure in the alert check is reported in the
refresh response and never breaks the price refresh.

## Data sources (Phase 2b)

| Data | Source | Notes |
|---|---|---|
| US daily prices | Tiingo | adjusted OHLCV; NYSE calendar |
| European daily prices | EODHD | raw OHLC + adjusted close → adjusted OHLC by the day's factor; a factor change on overlapping bars triggers a full re-download |
| FX | ECB reference rates | `fx_rates` unique per (pair, date, source); demo portfolio reads synthetic rates only |
| Weekly / monthly | resampled from daily | `analysis?interval=1w|1mo`; `as_of` truncates the daily bars before resampling |

Every provider drops bars for sessions that haven't finished yet, using that exchange's clock.

## Backtesting (Phase 7)

`POST /api/backtest/run` loads the stored daily bars and builds a `backtest.Context`, which holds the
Phase 1 indicator arrays, ATR-ZigZag swings, and lazily evaluated Fibonacci and setups per bar. It then
runs a single or walk-forward test and stores the request and the full result in `backtest_runs`.
Signals at bar *t* use only data up to *t* (tested by truncation). Fills happen at *t + 1*'s open.
Selection never sees holdout bars (tested with a spy).

**Rotation backtest.** `POST /api/backtest/rotation/run` calls `sectors.aligned_history`, which loads the
benchmark and every sector ETF of the region in one namespace (real or synthetic, never mixed), leaves out
ETFs with too little history, and aligns the rest on common dates. `rotation_backtest.Universe` computes
RRG series, indicators and Rotation Signal Scores lazily per bar from data up to that bar. `simulate`
rebalances an equal-weight portfolio at the next open when the selection changes and charges costs on
the value traded. Results are stored in `backtest_runs` with `strategy = rotation:<id>` and the
benchmark's listing, so they appear with the other saved backtests.

## Sector Rotation

`data/sectors.py` defines regions (US now; European sector ETFs can be added as another region with
its own benchmark and provider). `services/sectors.py` loads stored daily bars for the benchmark and
the sector ETFs and aligns them on common dates. It then runs `engine/rrg.py` and `engine/rotation.py`,
reusing `indicators.compute_all`, `analysis.provenance` and `analysis.find_gaps`. The sector page reuses
the existing analysis endpoint (PriceChart, ScorePanel, Fibonacci). Holdings come from State Street's
daily `.xlsx`, parsed with zipfile + defusedxml (`market_data/holdings.py`) into `sector_holdings`.
Real (Tiingo) and synthetic data are chosen per view (`data=auto|real|synthetic`) and never mixed.
