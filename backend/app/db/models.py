"""SQLite storage. The uploaded file itself is never stored: only what was read from it."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app import demo as _demo

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Demo mode never opens your real database: it has its own file (see app/demo/__init__.py).
DATABASE_URL = f"sqlite:///{_demo.TRACKER_DB}" if _demo.DEMO else \
    os.environ.get("PT_DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'portfolio.db'}")


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


# Columns added after a table first shipped: created on older databases at start-up (SQLite ADD COLUMN, nullable).
ADDED_COLUMNS = {"journal_ideas": {"sector": "VARCHAR(60)"}}


def init_db(eng=None) -> None:
    from sqlalchemy import inspect, text
    eng = eng or engine
    Base.metadata.create_all(eng)
    insp = inspect(eng)
    with eng.begin() as c:
        for table, cols in ADDED_COLUMNS.items():
            if not insp.has_table(table):
                continue
            have = {x["name"] for x in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


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


class JournalEntry(Base):
    """Your notes on one trade (trade journal). `key` identifies the trade by what it is, not by its sheet row."""
    __tablename__ = "journal_entries"
    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    kind: Mapped[str] = mapped_column(String(4))  # buy | sell
    reasons: Mapped[list] = mapped_column(JSON, default=list)  # buy: why (tags)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)  # buy: plan, in the trade's price unit
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    sell_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lesson: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(10000), nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)  # "nothing to write": off the to-journal list
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class JournalIdea(Base):
    """A trade idea: a stock you're watching, its price levels (entry, target, stop, alerts) and why."""
    __tablename__ = "journal_ideas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock: Mapped[str] = mapped_column(String(200))
    ticker: Mapped[str] = mapped_column(String(30))
    exchange: Mapped[str] = mapped_column(String(10), default="US")  # US (Tiingo) or a European MIC
    side: Mapped[str] = mapped_column(String(5), default="buy")  # buy | sell | watch
    sector: Mapped[str | None] = mapped_column(String(60), nullable=True)  # else the sector of the stock if you hold/held it
    levels: Mapped[list] = mapped_column(JSON, default=list)  # [{label, kind: entry|target|stop|alert, price}]
    near_pct: Mapped[float] = mapped_column(Float, default=3.0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(10000), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="watching")  # watching | done | dropped
    listing_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Research listing with its daily prices
    price_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    bought_key: Mapped[str | None] = mapped_column(String(300), nullable=True)  # the buy it became (journal key)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class JournalIdeaEvent(Base):
    """A price level of an idea that was reached (hit) or came close (near). Unseen ones show as a badge."""
    __tablename__ = "journal_idea_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idea_id: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(100))
    level: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(5))  # near | hit
    date: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StockPrice(Base):
    """Daily close of a stock: `series` is a US ticker (from Tiingo) or "csv:<pool>" (a file you uploaded)."""
    __tablename__ = "stock_prices"
    series: Mapped[str] = mapped_column(String(240), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float)
    split: Mapped[float] = mapped_column(Float, default=1.0)  # split factor on that day (Tiingo); 1 = none


class PriceFetch(Base):
    """Download progress per ticker, so a download interrupted by the hourly limit resumes where it stopped."""
    __tablename__ = "price_fetches"
    series: Mapped[str] = mapped_column(String(240), primary_key=True)
    fetched_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    fetched_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # ok | not_found | error
    message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
