"""Broker integration primitives (read-only).

Fibonacci AI never places, modifies or cancels orders. Broker adapters expose
*only* a method to fetch a snapshot of positions. There is deliberately no
order-related interface anywhere in this package (enforced by a test).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class BrokerError(Exception):
    """Error safe to show to the user. Messages must never contain secrets."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class BrokerPosition:
    account_masked: str
    conid: str | None
    isin: str | None
    symbol: str
    description: str | None
    asset_category: str
    listing_exchange: str | None
    currency: str
    quantity: Decimal
    multiplier: Decimal
    mark_price: Decimal
    position_value: Decimal | None
    cost_basis_price: Decimal | None
    cost_basis_money: Decimal | None
    unrealised_pnl: Decimal | None
    fx_rate_to_base: Decimal | None
    report_date: date | None


@dataclass(frozen=True)
class SkippedPosition:
    symbol: str
    asset_category: str
    reason: str


@dataclass
class BrokerSnapshot:
    source: str  # e.g. "ibkr_flex"
    generated_at: datetime | None
    report_date: date | None
    accounts: dict[str, str] = field(default_factory=dict)  # masked account -> base currency ("" if unknown)
    positions: list[BrokerPosition] = field(default_factory=list)
    skipped: list[SkippedPosition] = field(default_factory=list)
    # (from_ccy, to_ccy) -> rate, i.e. 1 from_ccy = rate to_ccy, with the date it applies to
    fx_rates: dict[tuple[str, str], tuple[Decimal, date | None]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class BrokerAdapter(Protocol):
    """Read-only broker adapter. Implementations must not expose any trading capability."""

    name: str

    def fetch_snapshot(self) -> BrokerSnapshot: ...


def mask_account(account_id: str | None) -> str:
    if not account_id:
        return "unknown"
    a = account_id.strip()
    if len(a) <= 4:
        return "*" * len(a)
    return f"{a[:1]}{'*' * (len(a) - 4)}{a[-3:]}"
