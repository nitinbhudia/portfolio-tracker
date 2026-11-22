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
   **Fibonacci buy zones** (on the same tab): the stock's Fibonacci levels below today's price, from Research, each with the
   extra money, new break-even, rise needed and downside if you bought there (as many shares as you hold, a number of
   shares, or a USD amount); **use** puts a zone into the calculator. If Research has no analysis yet, one click
   calculates it. A warning shows when Research's price and the tracker's price disagree (wrong ticker or a missed split).
10. **Ask**: type questions such as "if I sell all my Microsoft now, what's my P&L?". Claude (Anthropic's API) answers by
   calling the app's own what-if calculations, so every figure comes from the app; the calculations used are shown under
   each answer. Needs an Anthropic API key: copy `.env.example` to `.env` in the app's folder, put the key after
   `ANTHROPIC_API_KEY=`, and restart. Your question and the figures it needs are sent to Anthropic; about $0.05–0.15 per
   question. **Sectors** (Data ▾ Names) can be suggested by Claude and are only used once you confirm them.
11. **Check vs sheet**: the app's rebuilt numbers next to your sheet's own (sales-log P/L per year, open
   positions' cost and P/L), with the reason for every difference.

Gains are before fees and dividends, which the sheet doesn't record. This reports what happened; it isn't advice.

## Mac app (no Terminal window)

Double-click **Make Mac App** (in the app's folder) once. It builds **Portfolio Tracker.app** in your Applications folder
(`~/Applications`), with its own icon, using tools every Mac has. Then open Portfolio Tracker from Launchpad, Spotlight or the
Dock like any other app:

- it starts everything in the background and opens the app's window when ready (a Chrome app window without browser
  tabs if Google Chrome is installed, otherwise your default browser); click its Dock icon again to reopen the window;
- **Quit** (Dock menu, or ⌘Q in the applet) stops everything;
- it runs the built pages (faster than the Terminal starter's development mode); the first start, and the first after an
  update, builds them (a minute or two);
- if it can't start it says why and offers the log (`~/Library/Logs/Portfolio Tracker/app.log`);
- updates from Data ▾ Updates & backups restart it by itself. Moved or renamed the folder? Double-click Make Mac App again.

The Terminal starter (`Start Portfolio Tracker`) still works; don't run both at once (they use the same ports).

## Risk (top menu)

The risk of what you hold today:
- **Concentration:** your largest position, the top 5 and top 10, and the "effective number of positions". Positions over
  10% (and 20%) of the portfolio are called out.
- **Exposure:** your money by sector, currency and broker.
- **Market risk:** today's positions replayed over the last 6 months, 1 year or 3 years of daily USD prices. It shows:
  - yearly volatility;
  - the deepest fall;
  - the loss on a bad day (1 day in 20, historical VaR 95%);
  - beta and correlation to the S&P 500;
  - what a 10/20/30% market fall would roughly do;
  - each stock's share of the risk;
  - how your biggest positions move together.

Market risk needs daily prices (Data ▾ Price history) and the S&P 500 (vs Indexes). Positions without them are listed
and left out.

## Demo mode (show the app without your data)

The **Live | Demo** switch at the top right swaps the whole app to a made-up portfolio: twenty invented companies
(Northwind Robotics, Helix Analytics, Rheinwerk AG, Thameside Holdings plc…), bought and sold since 2021 in USD, EUR and
GBP, with deposits, dividends, sale groups, sectors, price history, benchmarks and a full Research section (watchlist,
scanner, sector rotation, alerts, Fibonacci levels). Every page works, so you can show any feature. A yellow bar on every
page says you are in the demo; **Back to Live** returns to your portfolio.

How your data stays out of it:
- The demo is a separate copy of the backend (port 8002) with its own databases in `backend/demo-data/`. It never opens
  `portfolio.db` or `fibonacci_ai.db`, so nothing it shows can come from them.
- It doesn't read your keys from `.env` (only the Claude key, so **Ask** works on the made-up data).
- It sends nothing to the internet: price, exchange-rate and index requests are answered on the spot by a made-up market,
  and anything else (GitHub, your broker) is refused. Updates & backups are switched off in the demo.
- If the demo copy isn't running, Demo pages show an error, never your data.

Change anything you like in the demo (import, trades, watchlist…); **Reset demo data** in the yellow bar rebuilds it
(about half a minute). The demo is built the first time the app starts (also about half a minute).

## Automatic daily price refresh (Data ▾ Price history)

While the app runs it checks every 15 minutes. Once a US trading day has closed (about 18:00 New York time; if the app was
closed then, as soon as you open it) it updates exchange rates, Research (your holdings, Tiingo prices for everything it
tracks, European prices if EODHD is set up, then alerts) and Performance's daily price history. If Tiingo's hourly limit
leaves something over, it continues about an hour later until done. Positions, Overview and What-if then value each stock
at its latest downloaded close when that's newer than the workbook's price. Switch it off, see what the last run did, or
**Run now**, at the top of Data ▾ Price history. (Needs the app started by `Start Portfolio Tracker` / `scripts/dev.sh`.)

## Updates and backups (Data ▾ Updates & backups)

- **Update now** checks GitHub for a newer version, lists what's new, backs up both databases, installs the new version
  into this folder and restarts the app; the page reloads by itself. Never touched: your data (`*.db`), keys (`.env`),
  backups, installed packages. Packages are re-installed on restart if the new version needs different ones.
- **Backups** of both databases go to `backups/` in the app's folder: one a day automatically (last 14 kept), one before
  every update or restore, and whenever you press **Back up now**. **Restore** puts one back (after backing up the
  current state) and restarts the app; **download** saves a backup as a ZIP.
- The automatic restart needs the app to be started by `Start Portfolio Tracker` / `scripts/dev.sh` of this version or
  later; with an older starter, close its Terminal window and start it again after an update.

## Shortcuts panel

The panel on the left lists shortcuts to pages you use often (it starts with a few). On any page, **☆ Add this page**
adds it, including specific ones like a sector or a stock's analysis. Hover a shortcut to rename (✎), reorder (↑ ↓) or
remove it (✕). « collapses the panel to a slim bar. On a narrow window, the **★ Shortcuts** button at the bottom-left
opens it. Shortcuts are saved in the app's database (`backend/portfolio.db`), so they move with it.

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
  The ticker link next to a stock opens its Research analysis directly.
- **Research → Watchlist → Add all my US holdings** puts every US stock you hold (with a ticker) on the watchlist and
  downloads as many price histories as Tiingo's free hourly limit allows; press **Refresh data** later for the rest.
- **Research → Scanner → Add a stock**: type a ticker, or a company name and press **Search by name** (one Tiingo request),
  then **Add** or **Add & watch**. The stock's history is downloaded, analysed and saved, and the scan is run again so it
  appears in the results. European stocks: choose the exchange (needs EODHD).
- **Sector pages** (click a sector in Sector Rotation) start with **Top 10 stocks in the sector**: the ETF's ten biggest
  holdings by weight, downloaded automatically from the issuer's daily file (State Street for US sectors, iShares for
  Europe), marked "you hold" where you own them. **φ Analyse** / **☆ Watch** per stock, or **φ Analyse all**, downloads their
  prices and shows each one's Fibonacci analysis, 20-day change and strength against the sector. Fibonacci AI's own My Portfolio page and IBKR sync were dropped (Research → Settings can still switch
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
