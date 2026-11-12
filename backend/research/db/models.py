"""ORM models. Portable SQLAlchemy types only, so PostgreSQL needs only a URL change.

Money/prices: Numeric(20, 6). Timestamps: UTC. Bar dates: exchange-local trading date.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric,
                        String, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base

Money = Numeric(20, 6)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Exchange(Base):
    __tablename__ = "exchanges"
    mic: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3))
    close_time: Mapped[str] = mapped_column(String(5), default="16:00")


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    asset_class: Mapped[str] = mapped_column(String(16))  # stock | etf | index
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tracks: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_holdable: Mapped[bool] = mapped_column(Boolean, default=True)
    listings: Mapped[list[Listing]] = relationship(back_populates="instrument")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("namespace", "exchange_mic", "ticker", name="uq_listings_ns_mic_ticker"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    # "synthetic" = generated demo data; "real" = real market data (e.g. Tiingo). Never mixed.
    namespace: Mapped[str] = mapped_column(String(16), default="synthetic", server_default="synthetic")
    provider_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    exchange_mic: Mapped[str] = mapped_column(ForeignKey("exchanges.mic"))
    ticker: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    is_benchmark: Mapped[bool] = mapped_column(Boolean, default=False)
    instrument: Mapped[Instrument] = relationship(back_populates="listings")
    exchange: Mapped[Exchange] = relationship()


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("listing_id", "interval", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    interval: Mapped[str] = mapped_column(String(4), default="1d")
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    adj_close: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # For real data, OHLCV above are split/dividend-ADJUSTED (what the engine uses);
    # the raw printed close/volume and corporate-action fields are kept alongside.
    adjustment: Mapped[str] = mapped_column(String(24), default="none", server_default="none")
    raw_close: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    raw_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    div_cash: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    split_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    is_delayed: Mapped[bool] = mapped_column(Boolean, default=False)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("base", "quote", "date", "source", name="uq_fx_rates_pair_date_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    date: Mapped[date] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    source: Mapped[str] = mapped_column(String(32))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)


class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    quantity: Mapped[Decimal] = mapped_column(Money)
    avg_cost: Mapped[Decimal] = mapped_column(Money)  # in listing currency
    opened_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    listing: Mapped[Listing] = relationship()


class IndicatorResult(Base):
    __tablename__ = "indicator_results"
    __table_args__ = (UniqueConstraint("listing_id", "interval", "date", "name", "params_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    interval: Mapped[str] = mapped_column(String(4))
    date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(32))
    params_json: Mapped[dict] = mapped_column(JSON)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    calc_version: Mapped[str] = mapped_column(String(32))
    params_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SwingPoint(Base):
    __tablename__ = "swing_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    interval: Mapped[str] = mapped_column(String(4))
    atr_multiple: Mapped[float] = mapped_column(Float)
    date: Mapped[date] = mapped_column(Date)
    confirmed_date: Mapped[date] = mapped_column(Date)
    price: Mapped[Decimal] = mapped_column(Money)
    kind: Mapped[str] = mapped_column(String(4))
    calc_version: Mapped[str] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64))


class FibonacciResult(Base):
    __tablename__ = "fibonacci_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    interval: Mapped[str] = mapped_column(String(4))
    as_of_date: Mapped[date] = mapped_column(Date)
    atr_multiple: Mapped[float] = mapped_column(Float)
    result_json: Mapped[dict] = mapped_column(JSON)
    calc_version: Mapped[str] = mapped_column(String(32))
    params_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TechnicalScore(Base):
    __tablename__ = "technical_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    horizon: Mapped[str] = mapped_column(String(8))
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(8), nullable=True)
    components: Mapped[dict] = mapped_column(JSON)
    weights: Mapped[dict] = mapped_column(JSON)
    inputs: Mapped[dict] = mapped_column(JSON)
    score_version: Mapped[str] = mapped_column(String(8))
    params_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchlistItem(Base):
    """Listings the user wants to keep an eye on (Phase 4 watchlist)."""
    __tablename__ = "watchlist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), unique=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[dict | str | float | int | bool | None] = mapped_column(JSON)


# --------------------------------------------------------------------------- broker (read-only)

class BrokerSyncRun(Base):
    """One import attempt. Positions are only replaced when a run succeeds."""
    __tablename__ = "broker_sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # ibkr_flex | ibkr_flex_file
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # running | success | failed
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    generated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # as reported by IBKR
    accounts: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # masked account -> base ccy
    fx_rates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    skipped: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    positions_count: Mapped[int] = mapped_column(Integer, default=0)


class BrokerPositionRow(Base):
    """Real positions from a broker. Kept separate from the synthetic universe on purpose."""
    __tablename__ = "broker_positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("broker_sync_runs.id"), index=True)
    account_masked: Mapped[str] = mapped_column(String(32))
    conid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    asset_category: Mapped[str] = mapped_column(String(8))
    listing_exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    quantity: Mapped[Decimal] = mapped_column(Money)
    multiplier: Mapped[Decimal] = mapped_column(Money)
    mark_price: Mapped[Decimal] = mapped_column(Money)
    position_value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    cost_basis_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    cost_basis_money: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    unrealised_pnl: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    fx_rate_to_base: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class ProviderRequest(Base):
    """Log of outbound market-data requests, used to stay inside free-plan limits."""
    __tablename__ = "provider_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    ok: Mapped[bool] = mapped_column(Boolean)


# --------------------------------------------------------------------------- opportunity scanner

class ScanRun(Base):
    """One scanner run. Results are kept so every scan can be audited and reproduced."""
    __tablename__ = "scan_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(16))
    atr_multiple: Mapped[float] = mapped_column(Float)
    setups_version: Mapped[str] = mapped_column(String(32))
    score_version: Mapped[str] = mapped_column(String(8))
    params_hash: Mapped[str] = mapped_column(String(64))
    universe_size: Mapped[int] = mapped_column(Integer)
    scanned: Mapped[int] = mapped_column(Integer)
    coverage: Mapped[dict] = mapped_column(JSON)


class ScanResult(Base):
    __tablename__ = "scan_results"
    __table_args__ = (UniqueConstraint("run_id", "listing_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    status: Mapped[str] = mapped_column(String(32))
    bar_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    triggered: Mapped[list] = mapped_column(JSON)
    row: Mapped[dict] = mapped_column(JSON)  # full scanner row incl. detector rule breakdowns


# --------------------------------------------------------------------------- alerts (Phase 6, in-app)

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("listing_id", "key", "bar_date", name="uq_alerts_listing_key_bar"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(8))  # bullish | bearish | neutral
    bar_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[dict] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)


class AlertState(Base):
    """Last closed bar evaluated per listing, so each bar is evaluated once."""
    __tablename__ = "alert_state"
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    last_bar_date: Mapped[date] = mapped_column(Date)
    config_hash: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- backtesting (Phase 7)

class BacktestRun(Base):
    """One stored backtest: the exact request, the full result, and hashes for reproducibility."""
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    version: Mapped[str] = mapped_column(String(32))
    params_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))


# --------------------------------------------------------------------------- sector rotation

class SectorHolding(Base):
    """Constituents of a sector ETF from the issuer's holdings file (latest download per ETF)."""
    __tablename__ = "sector_holdings"
    __table_args__ = (UniqueConstraint("etf_ticker", "rank", name="uq_sector_holdings_etf_rank"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    etf_ticker: Mapped[str] = mapped_column(String(12), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    rank: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    identifier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weight_pct: Mapped[float] = mapped_column(Float)
    exchange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
