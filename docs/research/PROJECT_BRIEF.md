# Fibonacci AI — Project Brief

> **How to use this file:** Read this brief for context only. Implement **only** the
> phase task file you are given (currently `PHASE_1_TASK.md`). Do not start any
> later phase until the user has approved the current one in writing.

## 1. Product

Fibonacci AI is a **personal investment research and decision-support tool** that
runs locally on a MacBook Pro. It is not a broker, not a financial adviser and not
an automated trading system.

It helps the user to:

1. Monitor an existing investment portfolio.
2. Analyse individual stocks and ETFs (US and European).
3. Identify Fibonacci retracements, extensions, support and resistance.
4. Assess trend, momentum, volume and volatility.
5. Spot possible accumulation, breakout, breakdown, reversal and profit-taking conditions.
6. Read clear, explainable technical research.
7. Receive alerts when important technical conditions occur.
8. Eventually backtest Fibonacci, moving-average, RSI and MACD strategies.

## 2. Non-negotiable rules (apply to every phase)

**Trading and advice**
1. Never implement trade execution. Never place, modify or cancel orders. No broker
   API scope that allows trading may be requested.
2. All investment decisions remain with the user. The app never recommends a trade
   and never gives personalised financial advice.
3. No RSI reading, Fibonacci level or score is ever presented as a standalone buy or
   sell signal.
4. A visible disclaimer stating "research tool, not investment advice" appears in the
   app footer and on every AI-generated analysis.

**Data integrity**
5. Never fabricate market data, prices, indicators, financial results or analysis.
6. Until a real provider is configured, use synthetic data and label it **SYNTHETIC**
   in every API response and on every screen that shows it.
7. Every price series, indicator, Fibonacci result, score and AI analysis carries its
   provenance: `source`, `is_synthetic`, `as_of` (UTC timestamp), `exchange_timezone`,
   `is_delayed` and `delay_minutes`.
8. **No look-ahead bias.** A value calculated for date *D* uses only bars dated ≤ *D*.
   A swing pivot counts only from the date it was *confirmed*, not the date it occurred.
9. **Reproducibility.** Every stored calculation records `calc_version`,
   `params_hash` and `input_hash` (hash of the exact OHLCV rows used). Recalculating
   from the same inputs must produce identical outputs.
10. Missing, stale, delayed or partial data is shown in both the UI and the API, never
    silently ignored or filled in. Gaps are never forward-filled without a flag.
11. Monetary amounts are stored in the listing's trading currency. Portfolio totals are
    converted to the base currency (**USD**) with an explicit, dated FX rate, and that rate and
    its date are shown.
12. Instruments are identified by ISIN, and each exchange listing (ticker, exchange,
    currency) is a separate record. A ticker on its own is never treated as unique.

**Security**
13. Secrets come from environment variables only (`.env`, git-ignored). They never
    appear in frontend code, Git history, logs or error messages. `.env.example`
    contains placeholders only.
14. Broker integrations are read-only. Broker passwords are never stored.

**Engineering honesty**
15. Do not claim an integration works until it has been implemented and tested
    against the real service. Claims about third-party coverage, pricing or limits
    must be marked *unverified* unless confirmed from current official documentation.
16. Do not leave placeholder buttons. A feature that is not built is hidden, not
    shown as a dead control.
17. Correctness, reproducibility and explainability of calculations come before
    visual polish.
18. Ask a concise clarifying question only when continuing would otherwise mean
    making an unsafe or irreversible assumption. Otherwise pick a sensible default
    and record it in `DEVELOPMENT.md` under "Decisions".

## 3. Core analytical principles

- Fibonacci levels are analytical reference levels, not guaranteed support or resistance.
- Technical scores are deterministic, versioned and fully explainable: the user can
  see the inputs, component scores, weights and formula version.
- Claude (or any LLM) **never** calculates prices, indicators, scores or financial
  metrics, and never invents data. It only interprets structured, pre-calculated
  results supplied by the backend.
- Outputs clearly separate four categories: **observed data**, **calculated
  indicators**, **interpretation** and **speculative scenarios**.

## 4. Technology stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Pydantic v2, Uvicorn, pandas, NumPy, pytest |
| Database | SQLite (Phase 1) → PostgreSQL later, with no rewrite of application logic. Alembic from Phase 1. |
| Indicators | Implemented directly and tested against golden fixtures. A TA library may be used only as an optional cross-check in tests. |
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS, TradingView Lightweight Charts (with the attribution its licence requires) |
| Optional later | Docker / Docker Compose, structured JSON logging |

Runtime requirements for local development: **Python 3.11+ and Node.js 20 LTS.**
Docker, PostgreSQL, broker credentials and paid data are not required until the
phase that introduces them.

## 5. Roadmap (later phases: context only, do not implement yet)

Each phase gets its own `PHASE_N_TASK.md` with acceptance criteria before work starts.

### Phase 2 — Real market data
- `MarketDataProvider` interface; `SyntheticDataProvider` becomes one implementation.
- **Before writing provider code:** produce `docs/data-provider-evaluation.md` comparing
  EODHD, Twelve Data and Financial Modeling Prep on exchange coverage (NASDAQ, NYSE, NYSE Arca,
  Euronext Amsterdam, Xetra, SIX, LSE), historical depth, adjusted vs raw prices,
  corporate-action data, FX data, rate limits, cost, and licence terms for personal
  display, **and US index data (S&P 500, Nasdaq-100, Dow, Russell 2000). Index levels
  are often licensed separately or delayed, so if direct index data is unavailable,
  fall back to the tracking ETFs (VOO/SPY, QQQ, DIA, IWM) and label them as proxies.**
  Every row cites the official source and date checked. The user picks the
  provider.
- Store provider symbol mapping, timezone, currency and delay status per listing.
- Store raw **and** split/dividend-adjusted series. Label which one each calculation uses.
- Add weekly and monthly timeframes, resampled from daily bars by exchange-calendar
  week/month. Fibonacci is calculated independently per timeframe and daily levels are
  never reused.
- Real FX rates from the chosen provider or ECB reference rates.

### Phase 3 — Read-only broker integration (IBKR first)
- `BrokerAdapter` interface; `MockBrokerAdapter` first.
- Short written comparison of IBKR Client Portal Web API vs TWS API (auth model,
  session expiry, gateway requirement, read-only scopes) before choosing.
- Retrieve only: accounts, positions, average cost, market value, currency,
  transactions/trades and dividends where available.
- Handle disconnection, session expiry and rate limits visibly. Last-sync time is
  shown, and a partial sync is shown as partial.
- The interface must allow KBC Securities, Trading 212 and CSV import to be added
  later without changing the portfolio engine.

### Phase 4 — Opportunity scanner
- Scans only instruments the configured provider actually covers. Shows universe
  size, coverage, last scan time and freshness. Never claims "whole exchange" coverage.
- Setup detectors (each a deterministic, documented rule set): potential bullish/bearish
  reversal, Fibonacci support/resistance approaching, potential breakout/breakdown,
  bullish/bearish MA alignment, momentum acceleration, potential accumulation/distribution.
- Filters: exchange, sector, asset class, currency, market cap (where available),
  volume, score, timeframe. Ranked by the transparent score, with all inputs visible.

### Phase 5 — Claude AI analyst
- Anthropic API, backend only. Input is a versioned JSON payload of pre-calculated
  results. Output is validated against a schema with the sections: technical position,
  Fibonacci, moving averages, momentum, volume, short/medium/long outlook,
  bullish scenario, bearish scenario, key levels, key risks, overall assessment
  (strong bullish … strong bearish). Every section is tagged observed /
  calculated / interpretation / speculative.
- **Number guard:** every price or number in the output must appear in the input
  payload (within rounding). An output that fails this check is rejected, not shown.
- **Cost control:** cache by `input_hash`. Regenerate only on user request, on a
  material change (defined numerically, e.g. score moves ≥10 points, or a new swing is
  confirmed, or price crosses a Fibonacci level or SMA 50/200), or in one scheduled daily
  batch. Enforce `AI_MONTHLY_BUDGET_USD` and `AI_MAX_CALLS_PER_DAY`, and log tokens and
  estimated cost per call. Use a smaller model for routine refreshes.
- Store prompt version, model, input hash and output for every analysis (audit trail).

### Phase 6 — Alerts
- Price approaching or breaking a Fibonacci level, SMA 10/20/50/100/200 crosses,
  RSI entering overbought/oversold, MACD crossovers, relative-volume spikes,
  material score changes.
- Configurable thresholds, deduplication and cooldowns. Alerts are evaluated on
  closed bars only. In-app first, then email, with Telegram optional.

### Phase 7 — Backtesting
- Event-driven, closed-bar engine reusing the exact Phase 1 indicator code.
- Walk-forward validation, a final untouched holdout period, transaction costs and
  slippage (configurable, conservative defaults), and point-in-time data only.
- Report: number of trades, win rate, average return, max drawdown, Sharpe-like
  ratio, exposure, results per sub-period, comparison against buy-and-hold, and
  **the number of parameter combinations tested** (overfitting disclosure).
- Show "past performance does not guarantee future results" on every report.

## 6. UI principles (all phases)

- Clean, professional research dashboard. Dark and light modes. Compact financial
  tables. Works in Safari and Chrome on macOS and is responsive on iPad and iPhone.
- Every data view has explicit **empty, loading, error, stale and synthetic** states.
- Navigation shows only built sections. Full target navigation: Overview, My
  Portfolio, Opportunity Scanner, Watchlist, Market Analysis, AI Investment Analyst,
  Alerts, Settings.

## 7. Working process (all phases)

1. Git with logically separated commits. `.gitignore` covers `.env`, `*.db` and
   `node_modules`. Run a secret scan (e.g. `gitleaks`, if installed) before each phase report.
2. Keep `README.md`, `DEVELOPMENT.md` (progress and decisions) and `ROADMAP.md` current.
3. End every phase with a report: what works, test results, how to run, what does
   not work, what remains, what configuration the user must provide, and the
   recommended next phase. Then **stop and wait for approval.**
