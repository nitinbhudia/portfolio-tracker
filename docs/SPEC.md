# Portfolio Tracker — specification (v1, for approval)

A local app on your Mac. It imports the **Live Portfolio** tab of your Excel workbook once, turns it
into a clean list of trades, and shows what you gained on each buy and sell, per stock, per year,
and on your capital. Results are in **US dollars**. Sales are matched to buys **first in, first out (FIFO)**.

Decisions so far: separate app · FIFO · USD · import the sheet once · prices from the sheet ·
repository `portfolio-tracker`.

## 1. Rules

1. **Nothing invented.** Every number comes from your sheet, your later edits, or a published FX rate.
   If something can't be worked out, the app says so and asks you; it never fills in a guess.
2. **Your data stays on your Mac.** The database and uploaded files are git-ignored. Tests and the demo
   use made-up data only.
3. **Every figure can be traced.** Each trade keeps the sheet row it came from; each gain shows the buy
   lots it was matched to and the FX rates used.
4. **Not advice.** The app reports what happened; it doesn't tell you what to buy or sell.

## 2. What the import reads (Live Portfolio tab only; all other tabs ignored)

| Sheet area | Used for |
|---|---|
| Position rows 2–1381 (one row per purchase): Date, Price Entry, pieces, Live Price, Status, Broker, Stock Name, Currency, Org val, P/L | **Buys.** Open rows also give the current price ("Live Price" as saved in the file). Closed rows give the sell price (the Live Price you overwrote when selling). |
| Sales log rows 1410–1982: sale date, stock, P/L, % and P/L USD, and the row each sale points to (e.g. `=G818`) | **Sells**: date of the sale, linked to its position row. |
| Cash / capital block (rows 2019–2045) | **Capital** per account, as the starting point for return on capital (see §5). |
| Pivot tables and the summary block | Not imported. Used only as **check figures** (§7). |

How a trade is rebuilt (layout verified on your workbook in phase 1: 503 of 577 sales match a purchase row
exactly by stock, buy price and shares):

- **Open row** = a purchase you still hold: buy on its Date at Price Entry.
- **Closed row with P/L 0 and no sales-log line** = a purchase whose shares were sold later: buy on its Date.
- **Closed row the sales log points to** = a *sale*, dated on the sale day (the log's date), shares = pieces,
  sell price = Live Price as typed when you sold. Its Price Entry is the buy price your sheet used (kept for
  the check figures; FIFO uses the purchase rows).
- **Needs review** (shown on the review page, never guessed; left out of results until decided):
  - purchases with shares that no sale accounts for, after matching every sale to the oldest earlier
    purchases of the same stock (mostly 2020–21 rows sold before the log started);
  - sales with no earlier purchase in the sheet for some of their shares (enter the purchase, or exclude);
  - closed rows with a P/L but no sales-log line: treat as a sale on the row's date (your usual layout), or
    enter a sale date and price, or exclude;
  - the sales typed by hand in the log (no link to a row) — kept as "sheet only" or linked to a row;
  - rows whose Live Price is still the live formula although sold, rows linked twice, a sale pointing to an
    Open row, unreadable values, and prices that look like pence/cents with another currency.
- **Stock names → one stock.** Tickers in the sheet are broken (`#VALUE!` for 1,335 of 1,374 rows, Excel's
  linked Stocks type doesn't survive outside Excel), so stocks are identified by Stock Name. Names differing
  only in spaces/capitals are one stock; the Stocks page suggests near-identical names for you to merge.
- **GBP prices are pence** (London quotes): value = shares × price / 100.

Re-importing the same file is safe (same result, nothing duplicated). After the import, you add new
trades in the app.

## 3. Money and currency

- Trades keep their own currency (USD, EUR, GBP, CAD seen). Every buy and sell is converted to USD at the
  **ECB reference rate for that day** (last published rate before the date if the day had none). The rate
  used is shown next to each conversion.
- Current value of open positions = shares × Live Price from the sheet, converted at the latest ECB rate.
  The "as of" date (the file's save date) is shown everywhere.
- FIFO gains in USD = USD proceeds − USD cost of the matched lots, so gains **include currency effects**;
  the split into "price" and "currency" gain is shown per sale.
- Fees and dividends aren't in the sheet, so v1 gains are **before costs**. You can add fees and
  dividends to any trade later and they are included from then on.

## 4. FIFO

- Sells are matched to the oldest remaining buys of the same stock (across brokers, by default;
  optionally per broker — see question below). Partial lots are split.
- A sell larger than the shares held is flagged, not silently allowed.
- For each sale: matched lots, holding period (days), cost, proceeds, gain and % gain in USD, and the
  gain your sheet recorded for that row (the sheet matches sales to a **specific** purchase, so the two
  can differ per sale; the all-time totals of closed-out stocks agree).

## 5. Analysis pages

1. **Overview:** portfolio value, invested capital, total gain (realised + unrealised), return on capital,
   this year's realised gain, number of open positions; value by broker and currency.
2. **Open positions:** per stock and per lot — shares, average FIFO cost, current value, unrealised gain
   and %, days held, weight in the portfolio. Sort/filter like Fibonacci AI's tables.
3. **Sales (realised):** every sale with its FIFO-matched lots and gain; filters by year, broker, stock.
4. **Per stock:** all buys and sells, realised + unrealised gain, average buy and sell price, total return.
5. **Per year:** realised gains, number of sales, win rate; and total return for the year
   (realised + change in unrealised). Monthly breakdown inside each year.
6. **Return on capital:**
   - simple: total gain ÷ capital put in;
   - per year: gain in the year ÷ capital at the start of the year (+ money added during the year);
   - money-weighted return (XIRR) on dated deposits, once you've entered them.
   v1 capital = the per-account amounts in your cash block, dated 1 January of the year in their name
   (e.g. "IBKR USD 2023" → 2023-01-01). You can replace them with real dated deposits and withdrawals.
7. **Trading statistics:** win rate, average win vs average loss, profit factor, best and worst sales and
   stocks, average holding period of winners vs losers, gains by holding period (<1 month, 1–12 months,
   >1 year).
8. **Reconciliation:** the check figures of §7 next to the app's numbers, with differences explained.
9. **Add / edit trades** (buy, sell, fee, dividend, deposit, withdrawal) and **update prices**
   (type a price, or re-upload an updated Live Portfolio tab for prices only).

Charts: realised gain per year and month (bars), portfolio value and capital over time (line),
allocation by stock/broker/currency (bars, not pies).

## 6. Tech

Same setup as Fibonacci AI: Python (FastAPI, SQLAlchemy, SQLite, pandas, openpyxl) and Next.js +
TypeScript + Tailwind, started with `./scripts/dev.sh` on your Mac; opens at http://localhost:3001
(Fibonacci AI keeps 3000/8000; this app uses 3001/8001, so both can run). Checks for busy ports at start.
ECB rates are fetched from the ECB's free API and stored.

## 7. Acceptance criteria

1. **Import** of your file: every one of the 1,374 position rows and 572 sales-log rows ends up as a trade,
   on the review list, or explicitly excluded — none silently dropped (counts shown).
2. **Check figures match** (on your file, before FX conversion, in each trade's own currency):
   - sales-log P/L total **378,388.82** and per year
     2021 15,504.81 · 2022 22,300.73 · 2023 22,105.10 · 2024 40,552.93 · 2025 182,630.56 · 2026 95,294.69
     ("as recorded by the sheet" view — specific matching, not FIFO);
   - open positions: cost and P/L per stock equal the sheet's Org val and P/L.
   Any difference is listed with its cause.
3. **FIFO** unit tests built by hand: partial sells, several lots, sell across years, oversell flagged,
   currency conversion at the trade-date rate.
4. **Returns** unit tests by hand: simple, per year, XIRR against a known result.
5. **Privacy:** no real data in git (tests use a made-up workbook with the same layout).
6. UI checked in a browser at desktop and phone width; one-command start on macOS.

## 8. Phases (each ends with your approval, as before)

1. **Import + review screen + FIFO + check figures** (§2–4, §7.1–7.3).
2. **Analysis pages, returns and charts** (§5, §7.4).
3. **Editing, deposits/withdrawals, fees/dividends, price updates.**

## 9. Open points (defaults used unless you say otherwise)

- **FIFO across brokers or per broker?** Default: per stock **across all brokers** (one pool per stock).
  Per broker is usual for tax reporting in some countries — say if you want that.
- **Capital** = the cash-block amounts dated 1 January of their year (you can replace them with dated
  deposits later).
- **Accounts named by year** ("IBKR 23", "IBKR 24", "KBC 21") are treated as separate accounts of the same
  broker, grouped under the broker in totals.
