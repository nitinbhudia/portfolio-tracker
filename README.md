# Portfolio Tracker

A local app for your Mac that imports the **Live Portfolio** tab of your stock-tracking workbook once and shows
what you gained on every sale (**first in, first out**, in **US dollars**), your open positions, and gains per year.
Specification: [`docs/SPEC.md`](docs/SPEC.md). Development notes: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

**Your data stays on your computer.** The workbook isn't kept: only what was read from it is stored in
`backend/portfolio.db`. Spreadsheets, CSVs and the database are git-ignored; tests use made-up workbooks.

## Run it on a Mac

Needs Python 3.11+ and Node.js 20+ (`brew install python@3.12 node@22`).

**Double-click `Start Portfolio Tracker.command`** in the app's folder (Finder). It opens a Terminal window, starts the
app and opens it in your browser when it's ready; keep that window open while you use the app, and press Ctrl-C (or
close the window) to stop it. Drag the file to the Dock for one-click starts. If the app is already running, it just
opens it.

The first time only, macOS may say the file "cannot be opened because it is from an unidentified developer" (it came
in a download): right-click it, choose **Open**, then **Open** again.

Or from Terminal, in the app's folder:

```bash
./scripts/dev.sh
```

Then open http://localhost:3001. It uses ports **3001 and 8001**, so it can run next to Fibonacci AI (3000/8000).
If a port is busy, the script says which program is using it. Stop the app with **Ctrl-C**.

## Use it

1. **Import**: choose your workbook (an unprotected copy; password-protected or labelled files are encrypted
   and can't be read). Only the Live Portfolio tab is read. ECB exchange rates are fetched at the same time.
2. **Review**: decide on the rows the app can't rebuild by itself (see `docs/SPEC.md` §2). Nothing is guessed;
   until you decide, those rows are left out. Decisions are kept if you import the same rows again.
3. **Stocks**: merge names that are the same stock (suggestions are offered) and add tickers if you like.
4. **Overview**, **Positions**, **Sales**, **Per stock**, **Per year**, **Statistics**: the results, in USD at the ECB
   rate of each trade date.
5. **Returns**: the money-weighted return of your trades; enter your dated deposits and withdrawals to also see
   your return on capital (overall and per year).
6. **Data ▾ Trades / Dividends / Prices**: add new trades (or correct and add fees to imported ones), record dividends,
   and keep prices current by typing them or uploading an updated workbook (prices only; nothing else changes).
7. **vs Indexes**: compare your trades with the S&P 500, Nasdaq Composite, Nasdaq-100, Russell 2000 and FTSE 100. Press
   "Get index data" (free daily history, no key: S&P 500 and Nasdaq from FRED, Russell 2000 and FTSE 100 from Stooq); if a
   download fails, the page says why for that index and you can upload a CSV for it: the daily-history download of most
   finance sites works (US, UK and European date formats, Close / Close/Last / Price columns).
8. **Time range**: the buttons at the top (1M, 3M, 6M, YTD, 1Y, 3Y, 5Y, All, or your own dates) change every chart.
9. **Gains by group** (Overview): your own groups of sales (e.g. Alpha picks, Trading, Mag 7, EU, Quant Pro, Crypto)
   are read from the workbook on every import: the row of group names under the sales log, and the formula under each
   name adding up that group's sales-log rows (`=G1539+G1533+…`, `SUM(…)` ranges, or a reference to another cell of the
   block, like `=E1996`). The app shows each group's FIFO gain in USD, per year, its win rate and the sheet's own total.
   Click a group to see its sales and move one to another group (kept across imports); sales no formula includes, or
   entered in the app, are "Not grouped". Rows in two groups, or formula references outside the sales log, are listed.
   **Performance**: profit/loss over time (total, open positions, closed positions) with a draggable overview strip to
   zoom, market value against cost (optionally including everything already sold), allocation by stock or sector, and
   monthly P/L in USD or %. Click a legend entry to hide a line; click a month for its split.
   Needs **daily prices** for your stocks (Data ▾ Price history): US stocks from Tiingo (free key: add
   `TIINGO_API_KEY=` to `.env`; set each stock's ticker on that page, then Download; the free plan allows about 50
   requests an hour, so a first download of a few hundred tickers runs in the background for several hours and resumes
   by itself), other listings from a CSV per stock (e.g. Investing.com's Historical Data download). Stocks without
   daily prices are valued at their last trade price, and the page says how much of the value is estimated that way.
   The page also flags trades whose price is far from the same stock's other trades within a month (usually two stocks
   written with the same name); fix the name on Data ▾ Trades → correct.
   **Explore**: interactive drill-down charts. A portfolio map (size = value, colour = gain/loss %): click a sector, then a
   stock, then see its purchase lots. Realised gains over time: click a year, then a month, then a sale to see which
   purchases it sold (FIFO). A trail above each chart takes you back up; hover or tab to anything for details.
   **What-if**: "if I sold now" for one stock, several, a sector or everything (FIFO gain per purchase lot, before tax),
   and a rebalancing preview by stock or sector (trades, gain realised, cash raised, weights before and after).
   **Average down**: for a position in loss, what buying more does to your break-even. Plan by shares, an amount or a
   target break-even, at today's price or a lower one; compares with doing nothing (rise needed, loss if it falls another
   20%), shows what FIFO would realise if you later sold only the added shares, and a table of buy prices (today, −10/−20/−30%)
   by size (+50%, +100%, +200%). Simulations only: nothing is traded. Maths, not advice.
10. **Ask**: type questions such as "if I sell all my Microsoft now, what's my P&L?". Claude (Anthropic's API) answers by
   calling the app's own what-if calculations, so every figure comes from the app; the calculations used are shown under
   each answer. Needs an Anthropic API key: copy `.env.example` to `.env` in the app's folder, put the key after
   `ANTHROPIC_API_KEY=`, and restart. Your question and the figures it needs are sent to Anthropic; about $0.05–0.15 per
   question. **Sectors** (Data ▾ Names) can be suggested by Claude and are only used once you confirm them.
11. **Check vs sheet**: the app's rebuilt numbers next to your sheet's own (sales-log P/L per year, open
   positions' cost and P/L), with the reason for every difference.

Gains are before fees and dividends, which the sheet doesn't record. This reports what happened; it isn't advice.

## Research (the former Fibonacci AI app)

The **Research** tab is the Fibonacci AI app, now part of Portfolio Tracker: one start button, one `.env`, one Terminal
window. Its sub-menu has **Overview, Sector Rotation, Scanner, Watchlist, Market Analysis** (charts with SMAs, Fibonacci
levels, RSI, MACD and short/medium/long-term scores), **Alerts, Backtesting** and **Settings**. What each does is described
in `docs/research/` (the former Fibonacci AI docs).

- **Your holdings come from Portfolio Tracker.** Research follows your open positions (from your workbook) for its Overview,
  the scanner's "My holdings" preset and alerts. US stocks with a ticker (Data ▾ Price history) get real Tiingo prices and a
  full analysis; others are valued with the tracker's own price. On **Positions**, the **φ** button next to any stock
  downloads its price history, calculates and saves its Fibonacci levels, moving averages, RSI, MACD and scores, and
  opens it in Research or puts it on Research's watchlist (★ marks watched stocks). US stocks use Tiingo; European ones
  need EODHD and an exchange (Xetra, Euronext Amsterdam/Paris, SIX, London). The stock stays tracked from then on.
  The ticker link next to a stock opens its Research analysis directly. Fibonacci AI's own My Portfolio page and IBKR sync were dropped (Research → Settings can still switch
  to the synthetic demo portfolio).
- **Keys:** the same `TIINGO_API_KEY` serves both. For European prices in Research add `EODHD_API_KEY` (optional, paid).
- **Data:** Research keeps its own database, `backend/fibonacci_ai.db` (prices, watchlist, alerts, backtests, settings).
  To keep what you had in Fibonacci AI, copy `fibonacci-ai/backend/fibonacci_ai.db` into this app's `backend` folder
  before starting it; the starter brings it up to date. Without it, Research starts with its synthetic demo data and
  downloads real prices for your holdings when you press **Update prices** / **Refresh data**.
- Research is a research tool, not investment advice: setups and scores are conditions to look into, not buy or sell signals.

## Tests

```bash
./scripts/dev.sh --test
```
