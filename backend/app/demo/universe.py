"""The made-up companies of the demo portfolio. None of them exist; tickers and names are invented for the demo.

ticker, name, mic, currency, sector, price at the start of the synthetic market (Jan 2019), annual volatility, beta to
the synthetic market, extra yearly drift, and the sale group its trades go in.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    mic: str
    currency: str
    sector: str
    p0: float
    vol: float
    beta: float
    drift: float
    group: str
    pence: bool = False

    @property
    def us(self) -> bool:
        return self.currency == "USD"


GROUPS = ["Long term", "Tech leaders", "Trading", "Dividend", "Europe", "Crypto"]

COMPANIES = [
    Company("NWRX", "Northwind Robotics", "XNAS", "USD", "Information Technology", 42.0, 0.42, 1.3, 0.18, "Tech leaders"),
    Company("HLXA", "Helix Analytics", "XNAS", "USD", "Information Technology", 88.0, 0.34, 1.2, 0.10, "Tech leaders"),
    Company("QLTS", "Quantum Lattice Systems", "XNAS", "USD", "Information Technology", 23.0, 0.58, 1.6, 0.05, "Trading"),
    Company("BRGT", "Brightpath Semiconductors", "XNAS", "USD", "Information Technology", 61.0, 0.46, 1.5, 0.22, "Tech leaders"),
    Company("CLDV", "Cloudvale Software", "XNYS", "USD", "Information Technology", 140.0, 0.36, 1.2, -0.12, "Trading"),
    Company("MRVH", "Meridian Vertex Health", "XNYS", "USD", "Health Care", 74.0, 0.24, 0.8, 0.04, "Long term"),
    Company("AQMD", "Aquila Medical Devices", "XNAS", "USD", "Health Care", 33.0, 0.38, 0.9, -0.08, "Trading"),
    Company("SLFG", "Solarforge Energy", "XNAS", "USD", "Utilities", 19.0, 0.52, 1.1, 0.02, "Trading"),
    Company("PCPT", "Pinecrest Petroleum", "XNYS", "USD", "Energy", 54.0, 0.32, 0.7, -0.04, "Dividend"),
    Company("IRHL", "Ironhill Industrials", "XNYS", "USD", "Industrials", 97.0, 0.26, 1.0, 0.05, "Long term"),
    Company("ORBF", "Orbital Freight", "XNYS", "USD", "Industrials", 46.0, 0.35, 1.1, -0.03, "Trading"),
    Company("FNCB", "Fincrest Bancorp", "XNYS", "USD", "Financials", 38.0, 0.27, 1.0, 0.03, "Dividend"),
    Company("CRVP", "Coralview Payments", "XNAS", "USD", "Financials", 120.0, 0.33, 1.2, -0.12, "Long term"),
    Company("GRLF", "Greenleaf Consumer Brands", "XNYS", "USD", "Consumer Staples", 64.0, 0.18, 0.6, 0.02, "Dividend"),
    Company("UBRT", "Urbanrise Retail", "XNYS", "USD", "Consumer Discretionary", 29.0, 0.40, 1.2, 0.00, "Trading"),
    Company("DGLT", "Digital Ledger Trust", "XNAS", "USD", "Crypto-related", 12.0, 0.75, 1.8, 0.15, "Crypto"),
    Company("RHWK", "Rheinwerk AG", "XETR", "EUR", "Industrials", 72.0, 0.28, 0.9, 0.04, "Europe"),
    Company("NRDL", "Nordlicht Energie AG", "XETR", "EUR", "Utilities", 31.0, 0.30, 0.7, 0.01, "Europe"),
    Company("BTVA", "Batavia Chips NV", "XAMS", "EUR", "Information Technology", 210.0, 0.40, 1.4, -0.15, "Europe"),
    Company("THMS", "Thameside Holdings plc", "XLON", "GBP", "Financials", 540.0, 0.24, 0.8, 0.02, "Europe", pence=True),
]
BY_TICKER = {c.ticker: c for c in COMPANIES}

# Index levels at the start of the synthetic market, keyed by the symbols the Benchmarks page downloads.
INDEXES = {"SP500": (2510.0, 0.17, 1.0), "NASDAQCOM": (6650.0, 0.22, 1.2), "NASDAQ100": (6360.0, 0.22, 1.25),
           "^rut": (1350.0, 0.23, 1.15), "^ukx": (6730.0, 0.15, 0.6)}

# Units per 1 EUR at the start, for the synthetic ECB rates.
FX_START = {"USD": 1.14, "GBP": 0.89, "CHF": 1.12, "JPY": 125.0, "CAD": 1.55, "SEK": 10.2, "NOK": 9.8, "DKK": 7.46,
            "AUD": 1.60, "HKD": 8.9, "PLN": 4.3, "HUF": 320.0, "CZK": 25.7}
