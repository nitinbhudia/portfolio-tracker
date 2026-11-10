# Development notes

## Index comparison and chart time ranges

**CSV formats** (`engine/indexcsv.py`): comma, semicolon or tab files; Date/Datum/observation_date columns; Close,
Close/Last, Adj Close, Price, Last, Schluss columns (or FRED's single value column); ISO, US, UK/European and named-month
dates, two- or four-digit years, with or without times; `$ £ €`, thousands commas and decimal commas. Day-first vs
month-first is decided per file (a number above 12, else the tidier run of trading days), and refused when it truly can't
be told. Tested with Stooq, FRED, Nasdaq.com, Investing.com, WSJ, Yahoo and European layouts.

**Fix (index data):** S&P 500, Nasdaq Composite and Nasdaq-100 now come from FRED (series SP500, NASDAQCOM, NASDAQ100; free,
no key; verified live), Russell 2000 and FTSE 100 from Stooq (FRED doesn't carry them). The page fetches one index per
request with a 25-second limit, so a slow or blocked site can't push the whole request past the web page's 2-minute
proxy limit (the "backend isn't responding" error), and every failure, including unexpected ones, comes back as a
message for that index. Source and symbol can be changed per index; CSV upload still works for any index.

- **Index data** (`index_prices`): daily closes for S&P 500 (`^spx`), Nasdaq Composite (`^ndq`), Nasdaq-100 (`^ndx`),
  Russell 2000 (`^rut`) and FTSE 100 (`^ukx`) from Stooq's free CSV download, or a CSV you upload (Date + Close). The
  Stooq symbol of each index can be changed on the page. Stooq refuses connections from the cloud environment this was
  built in, so the live download is untested there; parsing, the fetch (simulated) and every calculation are tested.
- **Comparisons** (`engine/benchmarks.py`): your portfolio's day-by-day value is unknown (no price history for your
  stocks), so the comparison uses your trades: (1) per sale, each FIFO purchase replayed in the index from purchase date to
  sale date with the same dollars (and open lots to the latest price date); (2) all time, every purchase buys the index and
  every sale sells the same dollar amount, XIRR on identical cash flows (reported as "ran out" if a sale takes more than the
  index holding is worth); (3) each index's change over the period. Index levels are converted to USD at the ECB rate of the
  day (FTSE 100). Price indexes exclude dividends, as do your gains unless entered.
- **Time ranges**: one range for every chart (presets or custom dates, remembered on this computer): Overview and Per year
  bars switch to months for periods up to 2 years; the money-in-shares line and both index charts follow the range.
- **Tests**: 9 more backend (CSV formats and errors, Stooq fetch and "no data", USD conversion and stale gaps, refresh and
  failures keeping earlier data, upload, per-trade comparison by hand, "ran out", periods and validation) → 46; frontend
  range and period helpers. Browser-checked with made-up index CSVs uploaded through the page, desktop and 390 px.

## Phase 3: trades, fees, corrections, dividends, prices (complete, awaiting approval)

- **Trades entered in the app** (`manual_trades`): buys and sells in any currency (GBP optionally in pence), with broker,
  fee and note; grouped by stock name like the sheet's names, so they join the same FIFO pool. Edit and delete.
- **Fees**: on app trades directly; on trades from the sheet in `trade_fees` (kept with the row's fingerprint). FIFO adds a
  purchase's fee to its cost (per share) and takes a sale's fee off its proceeds, so gains are after costs. The check
  against the sheet ignores fees (the sheet has none).
- **Corrections to sheet trades** (date / sale date, shares, buy or sell price, currency) are stored on the row like a
  review decision (merged into an existing decision), kept across re-imports of the same row, dropped if the row changes.
- **Dividends** (`dividends`): received amount after tax (tax kept for information), any currency; counted in total gain,
  the trade XIRR (money out), return on capital, per year (dividends column; gain ÷ money in shares includes them) and per
  stock (to the stock's main currency pool).
- **Prices** (`prices`): type a price (dated today) or upload an updated workbook to read only the open rows' Live Price,
  dated on its save date; trades and review decisions are untouched. The newest price per stock wins over the sheet's;
  each position shows its price date and source; the valuation date is the newest price date.
- **UI**: Trades (add/edit/delete, fee or correction on sheet trades), Dividends, Prices (typed + from workbook, undo);
  the menu groups data pages under "Data ▾"; dividends and price dates appear on Overview, Positions, Per stock,
  Per year and Returns.
- **Tests**: 6 more backend → 37 (app trades in FIFO with fees, new stock needing a price, fees on sheet trades, corrections
  and their survival on re-import, dividends in returns/years/per stock, typed vs older prices, prices from a workbook).
  Browser click-tested: an app sale, a fee, a dividend, a typed price and a workbook price update; 390 px without overflow.

### Decisions

- **The newest price wins** (by date; on the same date, the one entered in the app), so an older typed price never
  overrides a newer workbook.
- **Fees are in the trade's currency** (pounds for GBP even when prices are in pence).

## Phase 2: analysis pages, returns and charts (complete, awaiting approval)

- **Engine** `backend/app/engine/analytics.py`: trading statistics (win rate, average win/loss, profit factor,
  average per sale, holding period of winners vs losers, by holding period, best/worst sales, currency effect);
  realised gain per month and year; month-end timeline of money in shares (FIFO cost of holdings) and cumulative
  realised gain; per stock (buys, sells, average prices, realised + unrealised, total % on everything paid);
  XIRR (bisection on a bracketed root, so it always converges or says "no answer"); returns.
- **Returns**: money-weighted return of your trades (purchases in, sales out, open positions at today's value)
  needs nothing else; return on capital (XIRR and total gain ÷ net capital, and per year: realised ÷ (capital at
  the start of the year + money added)) uses the deposits/withdrawals you enter (`capital_flows` table, any
  currency, converted at the ECB rate of the day).
- **Importer**: also reads the sheet's cash block(s) as recorded (shown on the Returns page, not used).
- **API**: `/api/analysis`, `/api/by-stock`, `/api/by-stock/detail?pool=`, `/api/capital` (GET/POST/DELETE).
- **UI**: Overview (KPI tiles, realised per year, money in shares vs cumulative realised, allocation by
  broker/currency/stock), Per stock (table + drill-down with every trade and its FIFO matches), Per year (years and
  month by month), Returns (deposits form, both kinds of return, cash block), Statistics. Charts are plain SVG
  (`components/charts.tsx`): validated palette (blue/orange lines, blue/red gain/loss, both modes), 2px lines,
  ≤24px columns with a 4px rounded data end, hairline grid, hover/focus tooltips, legends, tables beside every chart.
- **Tests**: 7 more backend (XIRR known values, statistics/months/years/timeline/returns by hand, cash block,
  analysis/per-stock/capital API incl. "money in shares at the end = FIFO cost held") → 31; frontend chart ticks.
  Browser-checked at 1300/1400 and 390 px, light and dark, with a deposit added and deleted and a drill-down opened.

### Decisions

- **Only computable numbers**: no per-year total return or past values (no price history); deposits are never
  inferred from the cash block (it holds balances).
- **XIRR of your trades** as the headline return until deposits are entered: it needs nothing beyond the trades.

## Phase 1: import, review, FIFO, check figures (complete, awaiting approval)

- **Importer** `backend/app/importer/live_portfolio.py`: finds the tab named "Live Portfolio" (ignoring spaces
  and case), maps columns by the header row, reads saved values *and* formulas (to see which position row each
  sales-log line points to, e.g. `=G818`). Position rows run from row 2 to the last row with a date and status
  Open/Closed above the sales log; the sales log starts at the row with "Date | Stock | P/L…" and runs while the
  Date column holds dates. Encrypted files get a clear message.
- **Rebuild** `app/engine/rebuild.py`: open rows and closed P/L-0 rows are purchases; rows the log points to are
  sales dated on the log's date. A quantity match (sales against the oldest earlier closed purchases of the same
  stock) finds unsold purchases and sales without a purchase. Everything uncertain goes to the review list and
  is left out until decided. Decisions are stored per row with a fingerprint of the row's content, so they're
  dropped (and reported) if that row changes in a later import.
- **FX** `app/engine/fx.py`: ECB euro reference rates; USD per X = (USD per EUR)/(X per EUR); last rate on or
  before the date, at most 7 days old, else "no rate" (USD values not computed, never filled in).
- **FIFO** `app/engine/fifo.py`: one pool per stock and currency, across brokers. Cost at the buy-date rate,
  proceeds at the sale-date rate; gain split into price effect + currency effect. Overselling is flagged.
- **Check figures** `app/engine/check.py`: per sales-log line, the app's P/L with the sheet's own matching
  (sale row's sell price × shares − its buy price × shares) vs the sheet's P/L, by year and in total; open
  positions' cost and P/L per stock vs Org val and P/L. Each difference gets a reason.
- **API** `app/main.py` (FastAPI, port 8001), **storage** SQLite (`portfolio.db`, git-ignored), **UI** Next.js
  (port 3001): Overview, Open positions, Sales (FIFO), Review, Stocks, Check vs sheet, Import.
- **Tests**: 25 backend (importer, rebuild rules, decisions, FIFO by hand incl. currency effect and oversell,
  FX cross rates and holidays, check figures, API incl. re-import idempotence and FX failure) on made-up
  workbooks built by `tests/fixture_book.py` (formulas with saved values, like Excel writes them); frontend
  table helpers. Browser-checked at 1400 and 390 px.

### Result on your workbook (run locally, not stored in the repository)

- 1,374 position rows: 111 open purchases, 649 closed purchases, 572 sales; 97 review items before any decision.
- After FIFO, every stock's remaining shares equal the sheet's open shares; no sale oversells.
- Sales log: 523 of 572 lines reproduce the sheet's P/L exactly before review; every other line has a reason
  (waiting on review, P/L typed by hand, cost differs from shares × price, typed in the log).

### Decisions

- **The sheet's layout drives the rebuild** (purchase rows + sale rows), found by checking the data rather than
  assumed; it is documented in `docs/SPEC.md` §2.
- **Pending means left out**, including the purchases a pending sale would have used, so open positions never
  show shares the sheet says were sold.
- **GBP prices are pence.** Rows whose cost is 1/100 of shares × price in another currency are flagged, not changed.
