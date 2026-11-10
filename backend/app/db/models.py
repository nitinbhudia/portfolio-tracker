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


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(eng=None) -> None:
    Base.metadata.create_all(eng or engine)
