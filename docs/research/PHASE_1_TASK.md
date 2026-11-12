# Phase 1 Task — Local MVP (synthetic data)

> Read `PROJECT_BRIEF.md` first. Implement **only** this file. When every
> acceptance criterion in §10 passes, write the Phase 1 report (§12) and **stop**.
> Do not start Phase 2.

## 0. Goal

A locally runnable app that shows **one portfolio** of 8 seeded holdings, plus 4 US market benchmarks, on
deterministic **synthetic daily data**. It must have correct, tested indicators, a
reproducible Fibonacci engine, a transparent score, and charts the user can check
by hand.

**Out of scope for Phase 1:** real market data, broker integration, weekly/monthly
timeframes, the scanner, the watchlist UI, AI analysis, alerts, backtesting, Docker,
PostgreSQL, authentication and corporate-action processing (synthetic data has none;
the schema only needs to allow it later).

## 1. Step 0 — Environment check and plan (keep short)

1. Report the versions of Python, Node.js, npm/pnpm and Git. If Python < 3.11 or
   Node < 20, stop and tell the user how to install them (Homebrew).
2. Write `docs/ARCHITECTURE.md` (one page maximum): components, data flow, and the
   decisions you made where this file leaves room.
3. Do **not** research or write about IBKR, data providers or costs in Phase 1.
   That is Phase 2/3 work. Instead, add one line to `ROADMAP.md`: "External services:
   none required for Phase 1."
4. Then build.

## 2. Project layout

```
fibonacci-ai/
  backend/
    app/
      api/            # FastAPI routers
      core/           # config (pydantic-settings), provenance, hashing
      db/             # SQLAlchemy models, session, Alembic
      engine/
        indicators.py # SMA, EMA, RSI, MACD, ATR, relative volume
        swings.py     # ZigZag swing detection
        fibonacci.py
        scoring.py
      data/
        synthetic.py  # deterministic OHLCV + FX generator
        seed.py
      services/       # portfolio valuation, analysis assembly
    tests/
      fixtures/       # golden CSV/JSON fixtures
    alembic/
    requirements.txt
    requirements-dev.txt
  frontend/           # Next.js app
  docs/ARCHITECTURE.md
  scripts/dev.sh      # one command: install, migrate, seed, start both servers
  .env.example
  .gitignore
  README.md  DEVELOPMENT.md  ROADMAP.md
```

## 3. Data model (SQLAlchemy 2.x, portable to PostgreSQL)

Use plain SQLAlchemy types only (no SQLite-specific features). Monetary values use
`Numeric(20, 6)` and Python `Decimal` in the portfolio service. Indicator maths uses
float64. Timestamps are stored in UTC. Bar dates are stored as the exchange-local
trading date.

| Table | Key fields |
|---|---|
| `exchanges` | `mic` (PK, e.g. XNAS, XNYS, ARCX, XAMS, XETR, XSWX; plus pseudo-MIC `INDX` for indices), name, timezone, currency |
| `instruments` | id, `isin` (unique, nullable for indices), name, asset_class (stock/etf/**index**), sector, `is_holdable` (false for indices) |
| `listings` | id, instrument_id, exchange_mic, ticker, currency, **unique(exchange_mic, ticker)** |
| `price_bars` | listing_id, `interval` ('1d'), `date`, open, high, low, close, adj_close, volume, source, is_synthetic, ingested_at; **unique(listing_id, interval, date)** |
| `fx_rates` | base, quote, date, rate, source, is_synthetic; unique(base, quote, date) |
| `holdings` | id, listing_id, quantity, avg_cost (listing currency), opened_at |
| `indicator_results` | listing_id, interval, date, name, params_json, value(s) JSON, calc_version, params_hash, input_hash |
| `swing_points` | listing_id, interval, sensitivity, date, price, kind (high/low), **confirmed_date** |
| `fibonacci_results` | listing_id, interval, as_of_date, swing_high_id, swing_low_id, direction, levels JSON, nearest_level, distance_pct, distance_atr, retracement_depth, calc_version, params_hash, input_hash |
| `technical_scores` | listing_id, as_of_date, horizon (short/medium/long), total, classification, components JSON, weights JSON, inputs JSON, score_version, params_hash, input_hash |
| `watchlist_items` | listing_id, added_at, note *(model only; no UI in Phase 1)* |
| `app_settings` | key, value_json (base currency, Fibonacci sensitivity, theme) |

Use Alembic for the initial migration so PostgreSQL can be added later with only a
URL change.

## 4. Synthetic data

**Universe** (fictional ISINs are allowed but must start with `XX` so they can never
collide with real ones):

| Ticker | Exchange (MIC) | Currency | Type |
|---|---|---|---|
| AAPL | XNAS | USD | stock |
| MSFT | XNAS | USD | stock |
| NVDA | XNAS | USD | stock |
| VOO | ARCX | USD | etf |
| ASML | XAMS | EUR | stock |
| SAP | XETR | EUR | stock |
| NESN | XSWX | CHF | stock |
| VWRL | XAMS | EUR | etf |

**US market benchmarks** (analysis and Overview only; not holdable):

| Symbol | Exchange (MIC) | Currency | Type | Tracks |
|---|---|---|---|---|
| SPX | INDX | USD | index | S&P 500 |
| NDX | INDX | USD | index | Nasdaq-100 |
| DJI | INDX | USD | index | Dow Jones Industrial Average |
| RUT | INDX | USD | index | Russell 2000 |
| QQQ | XNAS | USD | etf | Nasdaq-100 |
| DIA | ARCX | USD | etf | Dow Jones Industrial Average |
| IWM | ARCX | USD | etf | Russell 2000 |

(VOO already covers the S&P 500 as an ETF.) The ETFs are full analysable listings
and may be added to the seed portfolio. **Indices have no volume:** store
`volume = null`, so the volume component is excluded and the score weights
renormalised (this exercises the §7 rule), and the volume pane shows
"not applicable for indices". Index symbols must never appear in the holdings table.

**Generator rules**
- Deterministic: the seed is derived from `sha256(ticker + exchange)`, with no
  dependence on the clock. The same code gives byte-identical data.
- **Fixed anchor end date** from settings (default `SYNTHETIC_END_DATE=2025-12-31`).
  Generate **600 trading days** (Mon–Fri; holidays are not modelled, and this is
  documented as a known simplification) ending on the anchor date, so SMA 200 has
  400 valid days.
- Regime-switching geometric Brownian motion: alternate trending and ranging regimes
  so that real swings exist for the Fibonacci engine. Build OHLC from the close with a
  bounded intraday range, and enforce `low ≤ open, close ≤ high`. Volume is lognormal,
  with spikes correlated to large moves.
- Include **one deliberate 3-day gap** in NESN's history so the missing-data UI path
  is exercised.
- Synthetic daily FX for EURUSD and USDCHF over the same dates, labelled synthetic. These are enough to convert EUR and CHF holdings into the **USD base currency**.
- Start prices should be plausible in magnitude, but the README and UI must say the
  prices are **not real**.

**Seed portfolio** in `backend/app/data/seed_portfolio.csv` (ticker, mic, quantity,
avg_cost). It holds the 8 core listings (it may also include QQQ/DIA/IWM, never indices) with a mix of gains and losses. The user can edit
this file and run `scripts/dev.sh --reseed`.

## 5. Indicator specifications (exact conventions; tests depend on these)

All indicators work on `close` (or OHLC where stated) of daily bars, ordered by date.
Values before the warm-up period are `null`, never 0 and never partial.

| Indicator | Definition | First valid index |
|---|---|---|
| SMA(n), n ∈ {10, 20, 50, 100, 200} | Arithmetic mean of the last n closes | n−1 |
| EMA(n) | α = 2/(n+1); **seeded with SMA(n)** of the first n values (TA-Lib convention) | n−1 |
| RSI(14) | **Wilder**: first avg gain/loss = simple mean of the first 14 changes, then `avg = (prev·13 + current)/14`. RSI = 100 − 100/(1+RS). If avg_loss = 0 then RSI = 100. | 14 |
| MACD(12,26,9) | line = EMA12 − EMA26; signal = EMA9 of the line (seeded from the first 9 valid line values); hist = line − signal | line: 25, signal: 33 |
| ATR(14) | TR = max(H−L, \|H−Cprev\|, \|L−Cprev\|), used from bar 1 (needs a previous close). ATR[14] = mean(TR[1..14]), then Wilder smoothing (TA-Lib convention). | 14 |
| Relative volume | `volume_t / mean(volume_{t−20 … t−1})` (**excludes** today) | 20 |

**Gaps:** indicators are calculated over the bars that exist (no interpolation). Any
calculation whose window spans a gap longer than 2 calendar business days returns
`data_quality: "gap_in_window"` alongside the value.

## 6. Swing detection and Fibonacci engine

### 6.1 Swing detection — ATR ZigZag (no look-ahead)
- Parameters: `atr_multiple` k. Sensitivity presets: `high` = 1.5, **`medium` = 2.5
  (default)**, `low` = 4.0. A custom k between 0.5 and 10 is allowed.
- Walk forward bar by bar. Track the running extreme of the current leg. A swing
  high is **confirmed** on the first bar whose low ≤ extreme_high − k·ATR14
  (where ATR is the value at the confirming bar). Swing lows mirror this.
- Store both `date` (when the extreme occurred) and `confirmed_date`. Any calculation
  as of date D may only use swings with `confirmed_date ≤ D`.
- Tie-break: if equal extremes occur, use the **earliest** bar.
- The engine starts after ATR warm-up. The first leg direction is set by whichever
  threshold is crossed first.

### 6.2 Fibonacci from swings
- Anchor = the **last two confirmed swings** as of D (one high H, one low L).
- Direction: if the low came before the high, the swing is **up** (retracements are
  measured down from H). Otherwise it is **down**.
- Retracements r ∈ {0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0}:
  - up: `H − r·(H−L)`; down: `L + r·(H−L)`.
- Extensions e ∈ {1.272, 1.618, 2.0, 2.618}, projected in the swing direction:
  - up: `L + e·(H−L)`; down: `H − e·(H−L)`. Negative prices are dropped and the
    reason is recorded.
- Nearest level = the level with the minimum |close_D − level|, with ties going to
  the lower ratio. Report `distance_abs`, `distance_pct` (relative to close) and
  `distance_atr` (relative to ATR14).
- Retracement depth: up = `(H − close)/(H−L)`; down = `(close − L)/(H−L)`. The value
  may be < 0 or > 1, which means price is beyond the swing. Flag this as
  `beyond_swing: true`.
- If fewer than two confirmed swings exist, return `status: "insufficient_swings"`.
  Do not return a guess.
- The output includes both swing points (dates, prices, confirmed dates), k,
  calc_version, params_hash and input_hash.

## 7. Technical score v1 (deterministic; formula shown in UI)

Each horizon uses daily bars with different inputs. Each component scores 0–100.
`total = Σ weight·component`, rounded to 1 decimal place.

| Component | Weight | Short | Medium | Long |
|---|---|---|---|---|
| **Trend / MA alignment** | 0.40 | close vs SMA10, SMA20; SMA10 vs SMA20 | close vs SMA50; SMA20 vs SMA50; SMA50 vs SMA100 | close vs SMA200; SMA50 vs SMA200; SMA100 vs SMA200 |
| **Momentum** | 0.30 | RSI14, MACD hist sign | MACD line vs signal, MACD line sign | 60-day rate of change sign; RSI14 above or below 50 |
| **Fibonacci proximity** | 0.15 | (same rule, all horizons; see below) | | |
| **Volume** | 0.15 | (same rule, all horizons; see below) | | |

- **Trend:** each of the 3 comparisons is bullish = 100 (strictly greater) or bearish = 0.
  The component score is the mean.
- **Momentum (short):** RSI points = 100 if 50 < RSI ≤ 70; 50 if RSI > 70 (stretched)
  or 30 ≤ RSI ≤ 50; 0 if RSI < 30. The component score is the mean of RSI points and
  the MACD-hist points (100 if > 0, else 0). Medium and long use the binary mean of
  their two conditions. *(An oversold reading never adds bullish points. This is rule 3
  of the brief.)*
- **Fibonacci proximity:** if `distance_atr ≤ 1` and price is **above** the nearest
  level in an up swing (support nearby) → 70. If it is **below** the nearest level in a
  down swing (resistance overhead) → 30. Otherwise → 50. If there are insufficient
  swings → 50, with `status` recorded.
- **Volume:** relative volume ≥ 1.5 on an up day → 80; on a down day → 20; otherwise 50.
- **Classification:** total ≥ 60 → bullish; ≤ 40 → bearish; otherwise neutral.
- If any required input is `null`, that component is excluded, the remaining weights
  are renormalised, and the response lists `excluded_components`. If more than half
  the weight is excluded, return `status: "insufficient_data"` and no score.
- Store `score_version="v1"`, the components, weights and raw inputs. The UI's
  "How was this calculated?" panel renders exactly these stored fields.

## 8. API (FastAPI, all JSON)

Every response includes a `provenance` object:
`{source, is_synthetic, as_of, exchange_timezone, is_delayed, delay_minutes, stale}`.
`stale` is true if the latest bar is older than 3 business days before the anchor
date or before now.

- `GET /api/health`
- `GET /api/portfolio`: holdings plus totals in base currency (default **USD**), FX
  rates used (pair, rate, date), per-holding nearest Fibonacci level and short-term
  classification.
- `GET /api/listings` and `GET /api/listings/{id}`
- `GET /api/listings/{id}/bars?from&to`
- `GET /api/listings/{id}/analysis?as_of=YYYY-MM-DD&sensitivity=medium`: indicators,
  swings, Fibonacci result and 3 scores. `as_of` defaults to the last bar. Historical
  `as_of` must honour no-look-ahead.
- `GET/PUT /api/settings`
- Errors use `{error_code, message}` and never include stack traces or secrets.

## 9. Frontend (Next.js + Tailwind + Lightweight Charts)

Navigation in Phase 1: **Overview · My Portfolio · Market Analysis · Settings.**
Other sections are not shown.

- **Global:** a persistent **SYNTHETIC DATA** banner, a data-freshness badge (source,
  as-of date, timezone), the disclaimer footer, dark/light toggle, and TradingView
  attribution.
- **Overview:** a **US market strip** at the top showing SPX, NDX, DJI and RUT (last close, 1-day/1-month/YTD % change, short/medium/long classification, synthetic label; each links to its analysis page); portfolio value and P/L in USD, best and weakest 3 holdings by
  % return, holdings within 1 ATR of a Fibonacci level, holdings whose short-term
  score dropped ≥ 10 points over 5 bars ("deteriorating momentum"), and data freshness.
  *(Do not add an "opportunities" panel; that belongs to the Phase 4 scanner.)*
- **My Portfolio:** compact table with ticker, exchange, currency, quantity, average
  cost, current price, market value (listing currency and USD), unrealised P/L (amount
  and %), nearest Fibonacci level, distance %, and short/medium/long classification.
  Totals row. FX rates are shown under the table.
- **Analysis page `/analysis/[listingId]`:**
  - Candlestick chart with SMA 10/20/50/100/200 (each toggleable), Fibonacci level
    lines with labels, and markers on the two anchor swings.
  - Separate synced panes for volume, RSI (30/70 guides) and MACD (line, signal, hist).
  - Fibonacci table: ratio, price, distance (abs, %, ATR), nearest highlighted.
  - Indicator summary: SMA values, RSI, MACD, ATR, relative volume.
  - Score panel: 3 horizons → total, classification, and an expandable breakdown of
    each component (inputs → points → weight → contribution).
  - Sensitivity selector (high/medium/low) that recalculates via the API.
  - Visible states for loading, error, insufficient history, insufficient swings and
    data gaps (NESN must show its gap warning).
- **Settings:** base currency (**USD** default; EUR/CHF selectable), default Fibonacci sensitivity, theme.
- Responsive: the portfolio table scrolls horizontally on iPhone, and charts stack
  vertically on narrow screens. Check in Safari and Chrome.

## 10. Acceptance criteria (Phase 1 is done only when all pass)

1. On a clean Mac with only Python 3.11+ and Node 20+, `./scripts/dev.sh` installs,
   migrates, seeds and starts both servers. README documents this plus the manual steps.
2. The dashboard opens at `http://localhost:3000` in Safari and Chrome.
3. The portfolio shows 8 holdings, total value, cost basis, P/L and % in USD, with the
   FX rates and dates shown.
4. Clicking a holding opens its analysis page with candlesticks, SMAs, Fibonacci lines
   and the RSI, MACD and volume panes.
5. The analysis page shows SMA, RSI, MACD, ATR and relative volume values, and they
   match the API.
6. Short/medium/long scores are shown with a full breakdown that matches the stored
   components and weights.
7. Every API response and screen shows provenance and the SYNTHETIC label.
8. NESN visibly reports its data gap. A listing queried with `as_of` inside its
   warm-up period shows "insufficient history" rather than fake values.
9. The Overview shows the 4 US index benchmarks. Each opens an analysis page with
   no volume pane values, and its score lists `volume` under `excluded_components`.
10. `pytest` passes with ≥ 90% line coverage on `app/engine/`. `npm run build` and
   `npm run lint` pass.
11. No secrets in the repo (`.env` is git-ignored; secret scan is clean if available).

## 11. Required tests (`backend/tests/`)

**Golden fixtures** (hand-checkable, committed as CSV/JSON):
- `sma_basic`: 1..30 closes → known SMA10/20 values.
- `rsi_wilder`: the 30-bar close series from Wilder's original worked example (or an
  equivalent published worked example). Expected RSI to 4 decimal places.
- `macd_ema_seed`: series that checks EMA SMA-seeding and the signal start index.
- `atr_wilder`: 20-bar OHLC with a gap-up bar, so TR uses |H−Cprev|.
- `relvol`: confirms today's volume is excluded from the average.
- Optional: if `talib` is importable, cross-check SMA/EMA/RSI/MACD/ATR on synthetic
  AAPL to 1e-8; otherwise `pytest.skip`.

**Engine tests**
- Swing detection on a hand-built zigzag series: exact pivot dates and confirmed
  dates for k = 1.5 and 2.5. Equal-high tie-break uses the earliest bar.
- **No look-ahead:** for 20 random `as_of` dates, analysis(as_of) computed on the full
  history equals analysis computed on history truncated at as_of.
- Fibonacci retracements and extensions for both up and down swings, exact to 1e-9.
  Negative extension is dropped. Retracement depth outside [0,1] sets `beyond_swing`.
- `insufficient_swings` and `insufficient_data` paths.
- Score: hand-computed expected totals for 3 fixtures (bullish, neutral, bearish).
  Renormalisation when a component is null.
- **Reproducibility:** generator output hash is stable across runs. Recalculation
  yields identical `input_hash`, `params_hash` and values.

**Service and API tests**
- Portfolio valuation with Decimal: USD, EUR and CHF holdings converted to USD with
  the correct dated rate.
- Index listings are rejected by holdings import, and their score renormalises without volume.
- Every endpoint returns `provenance` with `is_synthetic: true`.
- Error responses contain no stack traces.

## 12. Phase 1 report (write to `DEVELOPMENT.md` and reply to the user)

- Completed functionality, mapped to each acceptance criterion (pass/fail).
- Test results (counts, coverage) and the exact commands.
- How to run on macOS.
- Known limitations (e.g. no holidays in the synthetic calendar, daily timeframe only).
- Decisions made where this spec left room.
- Outstanding work and required user configuration for Phase 2 (provider choice and
  API key).
- Recommended next step: write `PHASE_2_TASK.md`. **Then stop.**
