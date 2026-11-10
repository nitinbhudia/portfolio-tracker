"""What-if: sell simulations and rebalancing previews. Nothing here changes any data.

All numbers are computed from the app's own FIFO lots, current prices and ECB rates, before tax:
- a simulated sale takes shares from the oldest remaining purchases of that stock (FIFO), like a real sale would;
- proceeds are valued at the current price and today's rate; cost is each lot's FIFO cost at its purchase-date rate,
  so the gain includes the currency effect, exactly like the Sales page;
- a rebalance keeps the stocks you don't mention as they are; selling and buying are matched to the targets and the
  difference is cash raised (or extra cash needed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from .fifo import Lot


@dataclass
class Holding:
    pool: str
    stock: str
    currency: str
    sector: str | None
    lots: list[Lot]  # FIFO order: oldest first
    price: float | None  # current price in the listing's units (pence for GBP)
    scale: float
    rate: float | None  # USD per unit of the currency, at the price date
    price_date: str | None

    @property
    def shares(self) -> float:
        return sum(lot.shares for lot in self.lots)

    @property
    def unit_usd(self) -> float | None:
        return self.price * self.scale * self.rate if self.price is not None and self.rate is not None else None

    @property
    def value_usd(self) -> float | None:
        u = self.unit_usd
        return self.shares * u if u is not None else None

    @property
    def cost_usd(self) -> float | None:
        if any(lot.cost_rate is None for lot in self.lots):
            return None
        return sum(lot.shares * (lot.price * lot.scale + lot.fee_per_share) * lot.cost_rate for lot in self.lots)


class WhatIfError(ValueError):
    pass


@dataclass
class SaleResult:
    pool: str
    stock: str
    currency: str
    sector: str | None
    shares: float
    price: float
    proceeds_usd: float
    cost_usd: float
    gain_usd: float
    gain_pct: float | None
    held_over_1y_gain_usd: float
    held_under_1y_gain_usd: float
    lots: list[dict] = field(default_factory=list)
    remaining_shares: float = 0.0


def sell(h: Holding, shares: float, today: date, fee: float = 0.0) -> SaleResult:
    """Sell `shares` of one holding now (FIFO). `fee` in the listing's currency (not pence)."""
    if h.price is None or h.rate is None:
        raise WhatIfError(f"{h.stock}: no current price or exchange rate, so a sale can't be valued. Add a price on the Prices page.")
    if shares <= 0:
        raise WhatIfError(f"{h.stock}: the number of shares to sell must be more than 0.")
    if shares > h.shares + 1e-9:
        raise WhatIfError(f"{h.stock}: you hold {h.shares:g} shares; can't sell {shares:g}.")
    need, lots, cost = shares, [], 0.0
    over, under = 0.0, 0.0
    unit = h.price * h.scale * h.rate
    fee_usd_per_share = (fee * h.rate / shares) if shares else 0.0
    for lot in h.lots:
        if need <= 1e-9:
            break
        take = min(lot.shares, need)
        if lot.cost_rate is None:
            raise WhatIfError(f"{h.stock}: a purchase on {lot.date} has no exchange rate, so its cost in USD isn't known.")
        c = take * (lot.price * lot.scale + lot.fee_per_share) * lot.cost_rate
        p = take * (unit - fee_usd_per_share)
        days = (today - lot.date).days
        if days > 365:
            over += p - c
        else:
            under += p - c
        lots.append({"bought": lot.date.isoformat(), "row": lot.row or None, "broker": lot.broker, "shares": take,
                     "buy_price": lot.price, "cost_usd": c, "proceeds_usd": p, "gain_usd": p - c, "days_held": days})
        cost += c
        need -= take
    proceeds = shares * unit - fee * h.rate
    gain = proceeds - cost
    return SaleResult(h.pool, h.stock, h.currency, h.sector, shares, h.price, proceeds, cost, gain,
                      gain / cost * 100 if cost else None, over, under, lots, h.shares - shares)


def select(holdings: dict[str, Holding], stocks: list[str] | None = None, sector: str | None = None,
           everything: bool = False) -> list[Holding]:
    if everything:
        return list(holdings.values())
    if sector:
        hs = [h for h in holdings.values() if (h.sector or "").lower() == sector.lower()]
        if not hs:
            known = sorted({h.sector for h in holdings.values() if h.sector})
            raise WhatIfError(f"No open position has the sector '{sector}'. Sectors in use: {', '.join(known) or 'none confirmed yet'}.")
        return hs
    out = []
    for s in stocks or []:
        if s not in holdings:
            raise WhatIfError(f"'{s}' isn't one of your open positions.")
        out.append(holdings[s])
    if not out:
        raise WhatIfError("Choose at least one stock, a sector, or the whole portfolio.")
    return out


def sell_many(holdings: dict[str, Holding], picks: list[tuple[Holding, float]], today: date, ytd_realised: float,
              fee_per_sale: float = 0.0) -> dict:
    results = [sell(h, sh, today, fee_per_sale) for h, sh in picks]
    tot_p = sum(r.proceeds_usd for r in results)
    tot_c = sum(r.cost_usd for r in results)
    gains = [r.gain_usd for r in results]
    before = sum(h.value_usd or 0 for h in holdings.values())
    return {
        "sales": [r.__dict__ for r in results],
        "totals": {"proceeds_usd": tot_p, "cost_usd": tot_c, "gain_usd": tot_p - tot_c,
                   "gain_pct": (tot_p - tot_c) / tot_c * 100 if tot_c else None,
                   "gains_usd": sum(g for g in gains if g > 0), "losses_usd": sum(g for g in gains if g < 0),
                   "held_over_1y_gain_usd": sum(r.held_over_1y_gain_usd for r in results),
                   "held_under_1y_gain_usd": sum(r.held_under_1y_gain_usd for r in results)},
        "year": {"realised_so_far_usd": ytd_realised, "realised_after_usd": ytd_realised + tot_p - tot_c},
        "portfolio": {"value_before_usd": before, "value_after_usd": before - sum(r.shares * holdings[r.pool].unit_usd for r in results),
                      "cash_raised_usd": tot_p},
    }


def rebalance(holdings: dict[str, Holding], by: str, targets: dict[str, float], today: date, ytd_realised: float,
              whole_shares: bool = True) -> dict:
    """targets: stock pool or sector -> % of today's portfolio value. Anything not listed is left as it is."""
    if by not in ("stock", "sector"):
        raise WhatIfError("by must be 'stock' or 'sector'")
    valued = {k: h for k, h in holdings.items() if h.value_usd is not None}
    total = sum(h.value_usd for h in valued.values())
    if total <= 0:
        raise WhatIfError("No open positions with a current price.")
    for k, pct in targets.items():
        if pct < 0 or pct > 100:
            raise WhatIfError(f"Target for {k} must be between 0% and 100%.")

    def key_of(h: Holding) -> str | None:
        return h.pool if by == "stock" else h.sector

    groups: dict[str, list[Holding]] = {}
    for h in valued.values():
        k = key_of(h)
        if k is not None:
            groups.setdefault(k, []).append(h)
    unknown = [k for k in targets if k not in groups]
    if unknown:
        raise WhatIfError(f"Not an open position{' sector' if by == 'sector' else ''}: {', '.join(unknown)}.")
    trades = []
    for k, pct in targets.items():
        members = groups[k]
        cur = sum(h.value_usd for h in members)
        diff = total * pct / 100 - cur
        for h in members:
            share = (h.value_usd / cur) if cur else 1 / len(members)
            usd = diff * share
            sh = abs(usd) / h.unit_usd
            if whole_shares:
                sh = math.floor(sh + 1e-9)
            if usd < 0:
                sh = min(sh, h.shares)
            if sh <= 0:
                continue
            trades.append({"pool": h.pool, "stock": h.stock, "sector": h.sector, "action": "sell" if usd < 0 else "buy",
                           "shares": sh, "price": h.price, "currency": h.currency, "value_usd": sh * h.unit_usd})
    sells = [(holdings[t["pool"]], t["shares"]) for t in trades if t["action"] == "sell"]
    sale = sell_many(holdings, sells, today, ytd_realised) if sells else None
    bought = sum(t["value_usd"] for t in trades if t["action"] == "buy")
    sold = sale["totals"]["proceeds_usd"] if sale else 0.0
    after: dict[str, float] = {}
    for h in valued.values():
        k = key_of(h) or "(no sector)"
        delta = sum((t["shares"] if t["action"] == "buy" else -t["shares"]) for t in trades if t["pool"] == h.pool)
        after[k] = after.get(k, 0.0) + (h.shares + delta) * h.unit_usd
    before: dict[str, float] = {}
    for h in valued.values():
        k = key_of(h) or "(no sector)"
        before[k] = before.get(k, 0.0) + h.value_usd
    cash = sold - bought
    total_after = sum(after.values())
    rows = []
    for k in sorted(set(before) | set(after), key=lambda x: -before.get(x, 0)):
        name = valued[k].stock if by == "stock" and k in valued else k
        rows.append({"key": k, "name": name, "before_usd": before.get(k, 0.0), "before_pct": before.get(k, 0.0) / total * 100,
                     "target_pct": targets.get(k), "after_usd": after.get(k, 0.0),
                     "after_pct": after.get(k, 0.0) / (total_after + max(cash, 0)) * 100 if total_after + max(cash, 0) else None})
    return {"by": by, "total_usd": total, "trades": trades, "sale": sale, "bought_usd": bought, "sold_usd": sold,
            "cash_usd": cash, "rows": rows,
            "note": "Positions you didn't set a target for are left as they are. Positive cash = money raised; negative = extra "
                    "money you'd need to add. Whole shares only, so results land near the targets, not exactly on them." if whole_shares else
                    "Positions you didn't set a target for are left as they are. Positive cash = money raised; negative = extra money needed."}
