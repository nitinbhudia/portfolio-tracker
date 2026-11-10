"""SQLite storage. The uploaded file itself is never stored: only what was read from it."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("PT_DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'portfolio.db'}")


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Import(Base):
    __tablename__ = "imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Decision(Base):
    """A review decision, keyed by sheet row ("P123" position, "S123" sales log) and that row's content."""
    __tablename__ = "decisions"
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    decision: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class StockName(Base):
    """A stock name as written in the sheet (normalised) and the stock group it belongs to."""
    __tablename__ = "stock_names"
    name_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    group_key: Mapped[str] = mapped_column(String(200), index=True)


class StockGroup(Base):
    __tablename__ = "stock_groups"
    group_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    ticker: Mapped[str | None] = mapped_column(String(30), nullable=True)


class FxRate(Base):
    """ECB euro reference rate: units of `currency` per 1 EUR."""
    __tablename__ = "fx_rates"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    per_eur: Mapped[float] = mapped_column(Float)


class CapitalFlow(Base):
    """Money you put into (positive) or took out of (negative) your accounts, entered on the Returns page."""
    __tablename__ = "capital_flows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)  # in `currency`; + deposit, − withdrawal
    currency: Mapped[str] = mapped_column(String(3))
    account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ManualTrade(Base):
    """A buy or sell entered in the app (after the import, or anything the sheet doesn't have)."""
    __tablename__ = "manual_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(4))  # buy | sell
    date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(200))  # stock name; grouped like the sheet's names
    shares: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    pence: Mapped[bool] = mapped_column(Boolean, default=False)
    broker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TradeFee(Base):
    """A fee on a trade that came from the sheet, kept with the row's fingerprint (dropped if the row changes)."""
    __tablename__ = "trade_fees"
    trade_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # B12, S40, A40, L7
    fingerprint: Mapped[str] = mapped_column(String(64))
    amount: Mapped[float] = mapped_column(Float)


class Dividend(Base):
    __tablename__ = "dividends"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float)  # received, after withholding tax
    tax: Mapped[float] = mapped_column(Float, default=0.0)  # withholding tax, for information
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Price(Base):
    """A current price for a stock (pool = stock group + currency), typed in or read from an updated workbook."""
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool: Mapped[str] = mapped_column(String(220), index=True)
    price: Mapped[float] = mapped_column(Float)
    date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(eng=None) -> None:
    Base.metadata.create_all(eng or engine)


class IndexPrice(Base):
    """Daily close of a benchmark index (in the index's own currency)."""
    __tablename__ = "index_prices"
    index_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float)


class StockSector(Base):
    """Sector of a stock group: suggested by Claude (unconfirmed) or set/confirmed by you. Only confirmed ones are used."""
    __tablename__ = "stock_sectors"
    group_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    sector: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(10))  # ai | you
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class AssistantChat(Base):
    """One conversation with the assistant: the API messages exactly as exchanged (kept unchanged for replay)."""
    __tablename__ = "assistant_chats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    display: Mapped[list] = mapped_column(JSON, default=list)
