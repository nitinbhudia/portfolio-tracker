# Data provider evaluation (Phase 2b)

**Checked on 2026-11-05**, from each provider's own public pages only. Anything not
stated on those pages is marked **unverified**. Prices and terms change, so re-check
before subscribing. US prices already come from Tiingo (Phase 2a); this evaluation is
about **European listings** (Euronext Amsterdam, Xetra, SIX, LSE), FX and index data.

## Summary

| | EODHD | Twelve Data | Financial Modeling Prep |
|---|---|---|---|
| Cheapest plan that fits | **EOD Historical, $19.99/mo** (or $199/yr), listed under "Personal use" | **Ultra, $999/mo**: the only plan whose licence allows storing and processing data (see below) | **Unverified**: the site refused automated access (HTTP 403) |
| Free plan | 20 API calls/day, 1 year of history | "Basic": testing/evaluation only; data "cannot be displayed to users … or used in production" | Unverified |
| Daily limit (paid) | 100,000 calls/day; 1,000 requests/min | No daily cap; per-minute credits (Grow 377/min, Pro 1,597/min, Ultra 10,946/min) | Unverified |
| History depth | EOD "30+ yrs" on paid plans | Unverified | Unverified |
| Raw vs adjusted | Raw OHLC **and** `adjusted_close` (splits + dividends); volume split-adjusted; separate splits & dividends API | Splits and dividends endpoints exist; adjustment details unverified | Unverified |
| Xetra | ✅ `SAP.XETRA` | Grow tier (EOD) | Unverified |
| LSE | ✅ `BP.LSE` | Grow tier (EOD) | Unverified |
| Euronext Amsterdam | **Unverified** on public pages (the exchange list is behind the API) | Grow tier (EOD) | Unverified |
| SIX Swiss | **Unverified** on public pages | Pro tier ($229/mo) | Unverified |
| FX history | ✅ EOD "Forex: Global" on the EOD plan | Real-time forex listed on Basic; licence as below | Unverified |
| US index levels | ✅ `GSPC.INDX`, `DJI.INDX`; "Indices: Global" on the EOD plan. Index licensing caveats unverified | Unverified | Unverified |
| Update timing | Each exchange 2–3 h after close; NYSE/NASDAQ within 15 min | "EOD … updated after each exchange close" | Unverified |
| Auth | `api_token` in the **query string** | Unverified | Unverified |

## Licence for this app

Fibonacci AI **stores** daily bars and **calculates** indicators, Fibonacci levels and
scores from them, for one person on their own computer.

- **Twelve Data** is explicit. On Grow ($79) and Pro ($229) the data "may be displayed but
  cannot be programmatically processed, stored, transformed, or redistributed". Only
  **Ultra ($999/mo)** allows "programmatic processing, analysis … and internal display".
  Basic is for testing only. **This rules Twelve Data out at a sensible price.**
- **EODHD** lists EOD Historical under "Personal Plans — Personal use", separate from
  "Commercial / B2B Plans". The detailed personal-use terms weren't checked line by line
  (**unverified**), but storing and analysing data for your own use is what the personal plans
  are sold for.
- **FMP:** unverified.

## Recommendation

**EODHD "EOD Historical" ($19.99/month).** It's the only option checked that covers EU
end-of-day prices, FX history and index levels on one personal plan at a low price. It also
returns both raw and adjusted prices, which the brief requires. Before relying on it:

1. Confirm in your EODHD account (or with their support) that **Euronext Amsterdam (VWRL,
   ASML)** and **SIX (NESN)** are on the plan, and their ticker suffixes. The public pages
   don't show this.
2. The token goes in the URL, so the app must redact it from every log and error, as it
   already does for IBKR.
3. Keep Tiingo for US prices (free, already built), or move everything to EODHD later. It's
   your choice, with no code impact on the rest of the app.

FX: the **ECB reference rates** (free, no key) are used for EUR/USD and EUR/CHF history,
whichever provider you pick. See below.

## ECB euro reference rates (used for FX)

- API: `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?startPeriod=…&format=csvdata`.
  Series key `D.<CCY>.EUR.SP00.A`; `+` combines currencies (`D.USD+CHF.EUR.SP00.A`); CSV
  columns include `TIME_PERIOD` and `OBS_VALUE`. Fetched successfully on 2026-11-05
  (EUR/USD 1.1646 on 2025-12-01).
- Published "at around 16:00 CET every working day, except on TARGET closing days".
  The series title says it is the 2.15 pm (C.E.T.) rate.
- "Published for information purposes only. Using the rates for transaction purposes is
  strongly discouraged." That's fine for valuing a portfolio in a research tool.

## Sources (all checked 2026-11-05)

- EODHD pricing: https://eodhd.com/pricing
- EODHD end-of-day API: https://eodhd.com/financial-apis/api-for-historical-data-and-volumes
- EODHD exchanges: https://eodhd.com/financial-apis/list-supported-exchanges
- EODHD limits: https://eodhd.com/financial-apis/api-limits
- Twelve Data pricing: https://twelvedata.com/pricing
- Twelve Data exchanges: https://twelvedata.com/exchanges
- Twelve Data docs index: https://twelvedata.com/docs
- FMP pricing: https://site.financialmodelingprep.com/pricing-plans (HTTP 403 to automated requests)
- ECB reference rates: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
- ECB data API: https://data.ecb.europa.eu/help/api/data
