"""Sector universe for the Sector Rotation module, by region.

US: the 11 GICS sectors via SPDR Select Sector ETFs (NYSE Arca), benchmark SPY, prices from Tiingo,
holdings from State Street. Europe: the 19 STOXX Europe 600 ICB supersectors via iShares (DE) ETFs on
Xetra, benchmark EXSA (iShares STOXX Europe 600), prices from EODHD, holdings from iShares.

Europe facts (ticker, ISIN, Xetra listing in EUR, distributing share class, benchmark index, holdings
file) were read from each fund's page on ishares.com (Swiss English site) on 2026-11-06.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectorEtf:
    ticker: str
    sector: str
    mic: str
    name: str
    isin: str | None = None
    holdings_path: str | None = None   # issuer-specific download path, when not derivable from the ticker


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    classification: str              # sector system the ETFs follow
    default_benchmark: str
    benchmarks: tuple[str, ...]      # tickers that may be chosen as the benchmark
    benchmark_mics: dict             # ticker -> MIC
    etfs: tuple[SectorEtf, ...]
    holdings_source: str             # "ssga" | "ishares"
    price_provider: str              # "tiingo" | "eodhd"
    timezone: str
    currency: str


def _spdr(ticker: str, sector: str) -> SectorEtf:
    return SectorEtf(ticker, sector, "ARCX", f"{sector} Select Sector SPDR ETF")


US = Region(
    id="us", name="United States", classification="GICS sectors (SPDR Select Sector ETFs)",
    default_benchmark="SPY", benchmarks=("SPY", "QQQ", "DIA", "IWM"),
    benchmark_mics={"SPY": "ARCX", "QQQ": "XNAS", "DIA": "ARCX", "IWM": "ARCX"},
    etfs=(
        _spdr("XLK", "Technology"), _spdr("XLF", "Financials"), _spdr("XLE", "Energy"),
        _spdr("XLV", "Health Care"), _spdr("XLI", "Industrials"), _spdr("XLY", "Consumer Discretionary"),
        _spdr("XLP", "Consumer Staples"), _spdr("XLU", "Utilities"), _spdr("XLB", "Materials"),
        _spdr("XLRE", "Real Estate"), _spdr("XLC", "Communication Services"),
    ),
    holdings_source="ssga", price_provider="tiingo", timezone="America/New_York", currency="USD",
)

_ISH = "/ch/individual/en/products/{id}/ishares-stoxx-europe-600-{slug}-ucits-etf-de-fund/1495092304805.ajax"


def _ish(ticker: str, sector: str, isin: str, pid: int, slug: str) -> SectorEtf:
    return SectorEtf(ticker, sector, "XETR", f"iShares STOXX Europe 600 {sector} UCITS ETF (DE)", isin,
                     _ISH.format(id=pid, slug=slug))


EU_BENCHMARK = SectorEtf("EXSA", "STOXX Europe 600", "XETR", "iShares STOXX Europe 600 UCITS ETF (DE)", "DE0002635307",
                         "/ch/individual/en/products/251931/ishares-stoxx-europe-600-ucits-etf-de-fund/1495092304805.ajax")

EU = Region(
    id="eu", name="Europe", classification="STOXX Europe 600 ICB supersectors (iShares ETFs on Xetra) — not GICS",
    default_benchmark="EXSA", benchmarks=("EXSA",), benchmark_mics={"EXSA": "XETR"},
    etfs=(
        _ish("EXV5", "Automobiles & Parts", "DE000A0Q4R28", 251932, "automobiles-parts"),
        _ish("EXV1", "Banks", "DE000A0F5UJ7", 251934, "banks"),
        _ish("EXV6", "Basic Resources", "DE000A0F5UK5", 251936, "basic-resources"),
        _ish("EXV7", "Chemicals", "DE000A0H08E0", 251938, "chemicals"),
        _ish("EXV8", "Construction & Materials", "DE000A0H08F7", 251940, "construction-materials"),
        _ish("EXH2", "Financial Services", "DE000A0H08G5", 251942, "financial-services"),
        _ish("EXH3", "Food & Beverage", "DE000A0H08H3", 251944, "food-beverage"),
        _ish("EXV4", "Health Care", "DE000A0Q4R36", 251946, "health-care"),
        _ish("EXH4", "Industrial Goods & Services", "DE000A0H08J9", 251948, "industrial-goods-services"),
        _ish("EXH5", "Insurance", "DE000A0H08K7", 251950, "insurance"),
        _ish("EXH6", "Media", "DE000A0H08L5", 251952, "media"),
        _ish("EXH1", "Oil & Gas", "DE000A0H08M3", 251954, "oil-gas"),
        _ish("EXH7", "Personal & Household Goods", "DE000A0H08N1", 251956, "personal-household-goods"),
        _ish("EXI5", "Real Estate", "DE000A0Q4R44", 251958, "real-estate"),
        _ish("EXH8", "Retail", "DE000A0H08P6", 251959, "retail"),
        _ish("EXV3", "Technology", "DE000A0H08Q4", 251961, "technology"),
        _ish("EXV2", "Telecommunications", "DE000A0H08R2", 251963, "telecommunications"),
        _ish("EXV9", "Travel & Leisure", "DE000A0H08S0", 251965, "travel-leisure"),
        _ish("EXH9", "Utilities", "DE000A0Q4R02", 251967, "utilities"),
    ),
    holdings_source="ishares", price_provider="eodhd", timezone="Europe/Berlin", currency="EUR",
)

REGIONS = {US.id: US, EU.id: EU}
SECTOR_TICKERS = {e.ticker for e in US.etfs}            # US set (kept for existing callers)
EU_SECTOR_TICKERS = {e.ticker for e in EU.etfs}
ALL_SECTOR_TICKERS = SECTOR_TICKERS | EU_SECTOR_TICKERS
BENCHMARK_NAMES = {"SPY": "SPDR S&P 500 ETF", "QQQ": "Invesco QQQ (Nasdaq-100)", "DIA": "SPDR Dow Jones ETF",
                   "IWM": "iShares Russell 2000 ETF", "EXSA": "iShares STOXX Europe 600 UCITS ETF (DE)"}


def region_of(ticker: str) -> Region | None:
    return next((r for r in REGIONS.values() if any(e.ticker == ticker for e in r.etfs)), None)


def etf(ticker: str) -> SectorEtf | None:
    if ticker == EU_BENCHMARK.ticker:
        return EU_BENCHMARK
    return next((e for r in REGIONS.values() for e in r.etfs if e.ticker == ticker), None)


# Synthetic demo only: beta to the synthetic market and idiosyncratic volatility per sector, chosen to
# look plausible. THESE ARE NOT ESTIMATES OF REAL SECTOR BEHAVIOUR.
SYNTHETIC_PROFILE = {"XLK": (1.25, 0.16), "XLF": (1.1, 0.14), "XLE": (0.9, 0.24), "XLV": (0.75, 0.12),
                     "XLI": (1.0, 0.11), "XLY": (1.15, 0.14), "XLP": (0.6, 0.11), "XLU": (0.5, 0.14),
                     "XLB": (1.0, 0.14), "XLRE": (0.9, 0.15), "XLC": (1.1, 0.15)}
SYNTHETIC_SPY = ("SPY", "ARCX", 450.0, 0.16)
SYNTHETIC_EU_PROFILE = {"EXV5": (1.3, 0.2), "EXV1": (1.25, 0.18), "EXV6": (1.3, 0.24), "EXV7": (1.0, 0.13),
                        "EXV8": (1.1, 0.13), "EXH2": (1.15, 0.13), "EXH3": (0.65, 0.11), "EXV4": (0.7, 0.12),
                        "EXH4": (1.1, 0.11), "EXH5": (0.9, 0.12), "EXH6": (0.85, 0.14), "EXH1": (0.95, 0.22),
                        "EXH7": (0.8, 0.12), "EXI5": (1.0, 0.17), "EXH8": (1.05, 0.16), "EXV3": (1.3, 0.18),
                        "EXV2": (0.7, 0.13), "EXV9": (1.15, 0.17), "EXH9": (0.65, 0.13)}
SYNTHETIC_EXSA = ("EXSA", "XETR", 50.0, 0.15)
