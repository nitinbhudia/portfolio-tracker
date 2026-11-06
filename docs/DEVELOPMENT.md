# Development notes

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
