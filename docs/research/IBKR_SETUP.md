# Connect Interactive Brokers (read-only)

Fibonacci AI uses IBKR's **Flex Web Service**. It downloads a *report* of your
positions. It cannot place, modify or cancel orders, and it never needs your IBKR
username or password.

## 1. Create the Flex Query (in IBKR Client Portal)

1. Log in to **Client Portal** → **Performance & Reports** → **Flex Queries**.
2. Next to **Activity Flex Query**, click **+**.
3. Query name: e.g. `FibonacciAI Positions`.
4. Sections. Tick these and choose **Select All** fields in each:
   - **Open Positions**, with **Options: Summary**
   - **Account Information** (provides your account's base currency)
   - **Conversion Rates** (lets the app convert totals into USD)
5. Delivery configuration: **Format: XML**, **Period: Last Business Day**.
   Leave the date format at its default.
6. Save. Note the **Query ID** shown in the list.

## 2. Enable the Flex Web Service token

On the same Flex Queries page, open **Flex Web Service Configuration** (gear icon):
- Turn the service **on**.
- **Generate a new token** and copy it. Tokens have an expiry date that you can choose.
  Renew the token when it expires.
- Optional but recommended: restrict the token to your home IP address.

## 3. Add the values to `.env` (on your Mac only)

Open `fibonacci-ai/.env` in TextEdit (it's a hidden file: in Finder press
**⇧⌘.** to show hidden files), then add:

```
IBKR_FLEX_TOKEN=paste-your-token-here
IBKR_FLEX_QUERY_ID=paste-your-query-id-here
```

Save the file, stop the app (Ctrl-C) and start it again with `./scripts/dev.sh`.

**Never share the token** (not in chats, emails or screenshots). `.env` is excluded
from Git.

## 4. Sync

In the app: **Settings → Interactive Brokers → Sync from IBKR**. IBKR takes a few
seconds to a minute to generate the report. When the sync succeeds, the app switches
to your IBKR holdings automatically. You can switch back to the demo portfolio under
**Settings → Portfolio holdings**.

### No token? Import a file instead
In Client Portal, run the Flex Query, download the **XML**, then use
**Import Flex XML file…** in Settings.

## What gets imported

| Imported | Not imported (listed as "skipped") |
|---|---|
| Stocks and ETFs (IBKR category STK): symbol, ISIN, exchange, currency, quantity, average cost, IBKR end-of-day price, market value, unrealised P/L, FX rate to your base currency | Options, futures, bonds, funds, cash and FX balances |

The account number is masked (e.g. `U****567`). The raw IBKR report is not stored.

## Common messages

| Message | What to do |
|---|---|
| Token has expired / invalid | Generate a new token, update `.env` and restart the app |
| Query ID is invalid | Check `IBKR_FLEX_QUERY_ID` |
| Still generating / try again | Wait a minute and sync again. IBKR limits requests to 10 per minute. |
| No 'Open Positions' section | Edit the Flex Query and add Open Positions |
| Totals shown in EUR (or your base) | Add the **Conversion Rates** section to the query |
| Report date is old (STALE) | Sync again. Flex reports are end-of-day. |
