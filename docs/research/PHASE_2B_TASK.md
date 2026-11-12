# Phase 2b Task: European prices, real FX history, weekly and monthly timeframes

> Read `PROJECT_BRIEF.md` first; every rule in it still applies. Provider decision:
> **EODHD** (chosen by the user on 2026-11-05 after `docs/data-provider-evaluation.md`).
> When every acceptance criterion in §6 passes, write the report and **stop**.

## 1. European end-of-day prices (EODHD)

- Client `app/market_data/eodhd.py`: `GET https://eodhd.com/api/eod/{SYMBOL}.{EXCH}?api_token=…&fmt=json&from=…`.
  The token is read from `EODHD_API_KEY` only and redacted from every error and log (it travels in the URL).
- Exchanges: Xetra (`XETR` → `XETRA`), London (`XLON` → `LSE`), Euronext Amsterdam
  (`XAMS` → `AS`) and SIX (`XSWX` → `SW`). The last two suffixes are **unverified** until
  the user's account confirms them; a 404 is shown as "symbol not found on EODHD".
- EODHD returns raw OHLC plus `adjusted_close` (splits and dividends). The engine uses
  adjusted OHLC: O/H/L are scaled by `adjusted_close / close` for that day. Raw close and
  volume are stored too (`adjustment = "split_dividend"`, as for Tiingo).
- Refresh: first download 5 years, then incremental with a 7-day overlap. If the adjustment
  ratio of any overlapping stored bar changed (a new dividend or split), the full history is
  downloaded again, as EODHD's documentation advises.
- Tracked: EU holdings from the IBKR import (IBKR exchange codes `AEB`, `IBIS`, `EBS`, `LSE`,
  `LSEETF`) and symbols the user adds (ticker + exchange).
- Budget: `EODHD_DAILY_BUDGET` (default 1,000 calls/day) and at most 900 requests/minute,
  logged in `provider_requests`.
- Bars dated after the last completed session of their exchange are never stored.

## 2. Exchange calendars

Built-in full-day holiday rules for real Xetra, Euronext Amsterdam, SIX and LSE data, so
ordinary holidays aren't reported as missing data. These are standard rules, **not yet checked
against each exchange's official calendar**. Synthetic data keeps Mon–Fri.

## 3. FX history (ECB reference rates)

- Client `app/market_data/ecb.py`: `D.USD+CHF.EUR.SP00.A` from the ECB data API (no key).
- Stored in `fx_rates` with `source = "ecb"`, `is_synthetic = False`: EURUSD and EURCHF as
  published, and USDCHF derived as EURCHF ÷ EURUSD on the same date (labelled derived).
- Refreshed with every "refresh everything" and from Settings. Five years on first download, then incremental.
- Used where the IBKR report has no USD rate: totals are converted with the ECB rate of the
  report date (or the latest earlier one), and the rate, its date and source are shown.
  Synthetic portfolios keep synthetic FX. Sources are never mixed in one valuation.

## 4. Weekly and monthly timeframes

- Resampled from daily bars by the listing's trading calendar: a week is the trading days of
  one ISO week, a month those of one calendar month. O = first open, H = max, L = min,
  C = last close, V = sum. The bar is dated by its last trading day.
- `GET /api/listings/{id}/analysis?interval=1w|1mo` (default `1d`). Indicators, swings,
  Fibonacci and scores are calculated **independently** on the resampled bars; daily levels
  are never reused. `as_of` truncates the daily bars first, so there's no look-ahead.
- The last week/month is flagged **in progress** when its period hasn't ended yet.
- Scanner, alerts and the portfolio stay daily.
- Analysis page: a 1D / 1W / 1M selector.

## 5. Also in this phase

- Tiingo downloader: drop any bar dated after the last completed US session.
- Market Analysis page: add a European symbol (ticker + exchange), and show EODHD and ECB status.
- `.env.example`: `EODHD_API_KEY=`, `EODHD_DAILY_BUDGET=`.

## 6. Acceptance criteria

1. EODHD client and refresh tested with simulated responses: adjusted OHLC, raw fields, token
   redaction, 404 / 401 / 429 errors, budget, incremental vs full on a ratio change, unfinished-day filter.
2. ECB client and FX storage tested with a recorded CSV; derived USDCHF; IBKR USD fallback uses it, with the rate shown.
3. Live check: one real ECB request succeeds. EODHD isn't live-checked until the user adds a key.
4. Calendars: known holidays per exchange are excluded; a real gap is still reported.
5. Weekly/monthly: resampling tested (holiday weeks, partial last period); no look-ahead
   (full vs truncated); daily results unchanged.
6. Every new endpoint returns provenance; backend and frontend tests, lint and build pass;
   browser check at desktop and 390 px.
7. Docs updated (README, ROADMAP, DEVELOPMENT decisions, ARCHITECTURE, .env.example).
