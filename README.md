# Portfolio Tracker

A local app for your Mac that imports the **Live Portfolio** tab of your stock-tracking workbook once and shows
what you gained on every sale (**first in, first out**, in **US dollars**), your open positions, and gains per year.
Specification: [`docs/SPEC.md`](docs/SPEC.md). Development notes: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

**Your data stays on your computer.** The workbook isn't kept: only what was read from it is stored in
`backend/portfolio.db`. Spreadsheets, CSVs and the database are git-ignored; tests use made-up workbooks.

## Run it on a Mac

Needs Python 3.11+ and Node.js 20+ (`brew install python@3.12 node@22`).

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
6. **Check vs sheet**: the app's rebuilt numbers next to your sheet's own (sales-log P/L per year, open
   positions' cost and P/L), with the reason for every difference.

Gains are before fees and dividends, which the sheet doesn't record. This reports what happened; it isn't advice.

## Tests

```bash
./scripts/dev.sh --test
```
