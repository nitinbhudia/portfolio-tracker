"""Seed universe. All ISINs start with 'XX' (fictional) so they cannot collide with real ones.
Prices generated for these listings are SYNTHETIC and not real market data."""

EXCHANGES = [
    # mic, name, timezone, currency, close time (local)
    ("XNAS", "Nasdaq", "America/New_York", "USD", "16:00"),
    ("XNYS", "New York Stock Exchange", "America/New_York", "USD", "16:00"),
    ("ARCX", "NYSE Arca", "America/New_York", "USD", "16:00"),
    ("XAMS", "Euronext Amsterdam", "Europe/Amsterdam", "EUR", "17:30"),
    ("XETR", "Xetra", "Europe/Berlin", "EUR", "17:30"),
    ("XSWX", "SIX Swiss Exchange", "Europe/Zurich", "CHF", "17:30"),
    ("INDX", "Index (not an exchange)", "America/New_York", "USD", "16:00"),
]

# ticker, mic, currency, asset_class, name, sector, tracks, start_price, annual_vol, benchmark
LISTINGS = [
    ("AAPL", "XNAS", "USD", "stock", "Apple Inc. (synthetic)", "Technology", None, 180.0, 0.28, False),
    ("MSFT", "XNAS", "USD", "stock", "Microsoft Corp. (synthetic)", "Technology", None, 380.0, 0.25, False),
    ("NVDA", "XNAS", "USD", "stock", "NVIDIA Corp. (synthetic)", "Technology", None, 120.0, 0.50, False),
    ("VOO", "ARCX", "USD", "etf", "Vanguard S&P 500 ETF (synthetic)", None, "S&P 500", 450.0, 0.16, False),
    ("ASML", "XAMS", "EUR", "stock", "ASML Holding (synthetic)", "Technology", None, 700.0, 0.35, False),
    ("SAP", "XETR", "EUR", "stock", "SAP SE (synthetic)", "Technology", None, 180.0, 0.25, False),
    ("NESN", "XSWX", "CHF", "stock", "Nestlé (synthetic)", "Consumer Staples", None, 95.0, 0.17, False),
    ("VWRL", "XAMS", "EUR", "etf", "Vanguard FTSE All-World (synthetic)", None, "FTSE All-World", 110.0, 0.15, False),
    ("QQQ", "XNAS", "USD", "etf", "Invesco QQQ Trust (synthetic)", None, "Nasdaq-100", 440.0, 0.22, True),
    ("DIA", "ARCX", "USD", "etf", "SPDR Dow Jones Industrial Average ETF (synthetic)", None, "Dow Jones Industrial Average", 390.0, 0.15, True),
    ("IWM", "ARCX", "USD", "etf", "iShares Russell 2000 ETF (synthetic)", None, "Russell 2000", 200.0, 0.24, True),
    ("SPX", "INDX", "USD", "index", "S&P 500 Index (synthetic)", None, "S&P 500", 5000.0, 0.16, True),
    ("NDX", "INDX", "USD", "index", "Nasdaq-100 Index (synthetic)", None, "Nasdaq-100", 18000.0, 0.22, True),
    ("DJI", "INDX", "USD", "index", "Dow Jones Industrial Average (synthetic)", None, "Dow Jones Industrial Average", 39000.0, 0.15, True),
    ("RUT", "INDX", "USD", "index", "Russell 2000 Index (synthetic)", None, "Russell 2000", 2000.0, 0.24, True),
]

INDEX_STRIP = ["SPX", "NDX", "DJI", "RUT"]

# NESN gets a deliberate 3-business-day hole so the missing-data path is exercised.
GAPS = {("NESN", "XSWX"): (480, 3)}  # (start offset in generated calendar, length)

FX_PAIRS = [("EUR", "USD", 1.08, 0.07), ("USD", "CHF", 0.88, 0.07)]  # base, quote, start, vol
