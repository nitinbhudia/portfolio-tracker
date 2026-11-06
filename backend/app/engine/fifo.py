"""First in, first out matching of sells to buys, with USD values (SPEC.md §3–4).

One pool per stock and currency. A sell takes shares from the oldest remaining buys of its pool;
partial lots are split. Each buy is valued in USD at the rate of its own date and each sell at the rate
of the sale date, so gains include the currency effect, which is reported separately:

    gain = proceeds_usd − cost_usd
         = shares·scale·(P_sell − P_buy)·R_sell   (price effect, at the sale-date rate)
         + shares·scale·P_buy·(R_sell − R_buy)    (currency effect)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date

from .fx import Rates
from .rebuild import Trade

EPS = 1e-9


@dataclass
class Match:
    buy_id: str
    buy_row: int
    buy_date: date
    broker: str
    shares: float
    buy_price: float
    cost_local: float
    cost_usd: float | None
    buy_rate: float | None
    buy_rate_date: date | None
    days_held: int


@dataclass
class Sale:
    id: str
    row: int
    sale_row: int | None
    date: date
    stock: str
    stock_key: str
    currency: str
    broker: str
    shares: float
    price: float
    proceeds_local: float
    proceeds_usd: float | None
    sell_rate: float | None
    sell_rate_date: date | None
    matches: list[Match]
    cost_local: float
    cost_usd: float | None
    gain_local: float | None
    gain_usd: float | None
    gain_pct: float | None
    price_effect_usd: float | None
    fx_effect_usd: float | None
    days_held: float | None  # share-weighted
    sheet_pl: float | None  # what the sheet recorded for this row (specific matching, own currency)
    unmatched_shares: float = 0.0
    problems: list[str] = field(default_factory=list)


@dataclass
class Lot:
    buy_id: str
    row: int
    date: date
    stock: str
    stock_key: str
    currency: str
    broker: str
    shares: float  # remaining
    price: float
    scale: float
    cost_rate: float | None
    cost_rate_date: date | None


def run(trades: list[Trade], rates: Rates, sheet_pl: dict[int, float | None] | None = None) -> tuple[list[Sale], list[Lot]]:
    sheet_pl = sheet_pl or {}
    pools: dict[str, deque[Lot]] = {}
    sales: list[Sale] = []
    for t in sorted(trades, key=lambda t: (t.date, 0 if t.kind == "buy" else 1, t.row)):
        q = pools.setdefault(t.pool, deque())
        if t.kind == "buy":
            r = rates.usd(t.currency, t.date)
            q.append(Lot(t.id, t.row, t.date, t.stock, t.stock_key, t.currency, t.broker, t.shares, t.price, t.scale,
                         r.rate if r else None, r.rate_date if r else None))
            continue
        need, matches = t.shares, []
        while need > EPS and q:
            lot = q[0]
            take = min(lot.shares, need)
            cl = take * lot.price * lot.scale
            matches.append(Match(lot.buy_id, lot.row, lot.date, lot.broker, take, lot.price, cl,
                                 cl * lot.cost_rate if lot.cost_rate is not None else None, lot.cost_rate,
                                 lot.cost_rate_date, (t.date - lot.date).days))
            lot.shares -= take
            need -= take
            if lot.shares <= EPS:
                q.popleft()
        sr = rates.usd(t.currency, t.date)
        proceeds = t.value
        problems = []
        if need > EPS:
            problems.append(f"Sold {need:g} more shares than were held at that date: gain not computed.")
        cost_local = sum(m.cost_local for m in matches)
        missing_fx = sr is None or any(m.cost_usd is None for m in matches)
        if missing_fx:
            problems.append("No ECB rate for a date involved: USD values not computed.")
        ok = need <= EPS
        p_usd = proceeds * sr.rate if sr else None
        c_usd = None if missing_fx else sum(m.cost_usd for m in matches)
        gain_usd = (p_usd - c_usd) if ok and not missing_fx else None
        price_eff = fx_eff = None
        if gain_usd is not None:
            price_eff = sum(m.shares * t.scale * (t.price - m.buy_price) * sr.rate for m in matches)
            fx_eff = sum(m.cost_local * (sr.rate - m.buy_rate) for m in matches)
        matched = sum(m.shares for m in matches)
        sales.append(Sale(
            id=t.id, row=t.row, sale_row=t.sale_row, date=t.date, stock=t.stock, stock_key=t.stock_key, currency=t.currency,
            broker=t.broker, shares=t.shares, price=t.price, proceeds_local=proceeds, proceeds_usd=p_usd,
            sell_rate=sr.rate if sr else None, sell_rate_date=sr.rate_date if sr else None, matches=matches,
            cost_local=cost_local, cost_usd=c_usd, gain_local=(proceeds - cost_local) if ok else None, gain_usd=gain_usd,
            gain_pct=(gain_usd / c_usd * 100) if gain_usd is not None and c_usd else None,
            price_effect_usd=price_eff, fx_effect_usd=fx_eff,
            days_held=(sum(m.shares * m.days_held for m in matches) / matched) if matched else None,
            sheet_pl=sheet_pl.get(t.row), unmatched_shares=max(need, 0.0) if need > EPS else 0.0, problems=problems))
    lots = [lot for q in pools.values() for lot in q if lot.shares > EPS]
    return sales, lots
