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


# ---------------------------------------------------------------- average down

DROPS = (0.0, 10.0, 20.0, 30.0)  # buy-price scenarios: today's price and this % lower
SIZES = (0.5, 1.0, 2.0)  # extra shares as a multiple of what you hold
STRESS = 20.0  # "what if it then falls another 20%"


def _plan(h: Holding, p_usd: float, n: float, fee_usd: float) -> dict:
    """Buy n more shares at p_usd (USD per share) and compare with doing nothing."""
    s, c = h.shares, h.cost_usd
    unit = h.unit_usd
    s2, c2 = s + n, c + n * p_usd + (fee_usd if n else 0.0)
    be = c2 / s2
    worse = p_usd * (1 - STRESS / 100)
    return {"shares_added": n, "money_usd": n * p_usd + (fee_usd if n else 0.0), "shares_after": s2, "cost_after_usd": c2,
            "break_even_usd": be, "break_even_cut_pct": (c / s - be) / (c / s) * 100,
            "rise_needed_from_buy_pct": (be / p_usd - 1) * 100, "rise_needed_from_today_pct": (be / unit - 1) * 100,
            "value_at_buy_price_usd": s2 * p_usd, "unrealised_at_buy_price_usd": s2 * p_usd - c2,
            "if_falls_further_usd": s2 * worse - c2, "if_falls_further_without_usd": s * worse - c,
            "at_old_break_even_gain_usd": s2 * (c / s) - c2}


def average_down(h: Holding, today: date, buy_price: float | None = None, shares: float | None = None,
                 amount_usd: float | None = None, target_break_even: float | None = None, fee: float = 0.0) -> dict:
    """Break-even maths for buying more of a position. Prices in the listing's units (pence for GBP); fee in its currency.

    New break-even = (cost so far + new money) / (shares after). Shares needed for a target break-even X at price p:
    S * (avg - X) / (X - p). Everything in USD at today's rate for the new purchase; old lots keep their FIFO cost.
    """
    if h.price is None or h.rate is None:
        raise WhatIfError(f"{h.stock}: no current price or exchange rate. Add a price on the Prices page.")
    if h.cost_usd is None or h.shares <= 0:
        raise WhatIfError(f"{h.stock}: the cost of some purchases isn't known in USD.")
    k = h.scale * h.rate  # USD per listing unit
    listing = lambda usd_: usd_ / k  # noqa: E731
    p = h.price if buy_price is None else float(buy_price)
    if p <= 0:
        raise WhatIfError("The buy price must be more than 0.")
    p_usd, fee_usd = p * k, fee * h.rate
    s, c = h.shares, h.cost_usd
    avg = c / s
    given = [x is not None for x in (shares, amount_usd, target_break_even)]
    if sum(given) > 1:
        raise WhatIfError("Give shares, an amount or a target break-even, not more than one.")
    n = None
    if shares is not None:
        if shares <= 0:
            raise WhatIfError("The number of shares to buy must be more than 0.")
        n = float(shares)
    elif amount_usd is not None:
        if amount_usd <= fee_usd:
            raise WhatIfError("The amount must be more than the fee.")
        n = math.floor((amount_usd - fee_usd) / p_usd + 1e-9)
        if n <= 0:
            raise WhatIfError(f"That amount doesn't buy one whole share at {p:g}.")
    elif target_break_even is not None:
        x = float(target_break_even) * k
        if x >= avg:
            raise WhatIfError(f"Your break-even is already {listing(avg):.2f}; pick a target below it.")
        if x <= p_usd:
            raise WhatIfError(f"A break-even of {target_break_even:g} can't be reached by buying at {p:g}: it must be above the buy price.")
        n = math.ceil((c + fee_usd - x * s) / (x - p_usd) - 1e-9)

    def show(d: dict) -> dict:
        d["break_even"] = listing(d["break_even_usd"])
        return d

    plan = None
    if n is not None:
        plan = show(_plan(h, p_usd, n, fee_usd))
        plan["buy_price"] = p
        # FIFO: if you later sell just the number of shares you added, at the new break-even, the oldest lots go first.
        extra = Lot("new", 0, today, h.stock, "", h.currency, "", n, p, h.scale, h.rate, today, fee_usd / h.rate / n if n else 0.0, "whatif")
        hh = Holding(h.pool, h.stock, h.currency, h.sector, list(h.lots) + [extra], plan["break_even"], h.scale, h.rate, h.price_date)
        later = sell(hh, n, today)
        plan["sell_added_at_break_even"] = {"shares": n, "gain_usd": later.gain_usd,
                                            "lots": [{"bought": lot["bought"], "shares": lot["shares"], "gain_usd": lot["gain_usd"]}
                                                     for lot in later.lots]}
    table = []
    for d in DROPS:
        price = h.price * (1 - d / 100)
        row = {"drop_pct": d, "buy_price": price, "plans": []}
        for mult in SIZES:
            row["plans"].append(show(_plan(h, price * k, math.ceil(s * mult - 1e-9), fee_usd)) | {"multiple": mult})
        table.append(row)
    return {
        "pool": h.pool, "stock": h.stock, "currency": h.currency, "pence": h.scale == 0.01, "price": h.price, "price_date": h.price_date,
        "now": {"shares": s, "cost_usd": c, "value_usd": h.value_usd, "unrealised_usd": h.value_usd - c,
                "break_even": listing(avg), "break_even_usd": avg, "rise_needed_pct": (avg / h.unit_usd - 1) * 100,
                "in_loss": h.value_usd < c, "if_falls_further_usd": s * h.unit_usd * (1 - STRESS / 100) - c},
        "plan": plan, "table": table, "stress_pct": STRESS,
        "notes": ("Maths, not advice: buying more lowers the rise you need to break even but puts more money in one stock. "
                  "Break-even is for the whole position (sell everything). FIFO sells your oldest, dearest shares first, so selling "
                  "only the added shares later realises a loss even at the new break-even. Before tax; past realised gains or "
                  "losses aren't included" + (". Non-USD: break-even prices use today's exchange rate." if h.currency != "USD" else ".")),
    }
