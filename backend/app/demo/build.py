"""Build demo mode's made-up data: a whole portfolio history (2021 to today) of invented companies, priced by the
synthetic market, run through the app's real import and download code so every page has something to show.

    PT_DEMO=1 python -m app.demo.build              build (into PT_DEMO_DIR, default backend/demo-data/)
    PT_DEMO=1 python -m app.demo.build --if-missing only if there is no demo yet

It runs in its own process (scripts/dev.sh, or the Reset button via app.demo.service) so that it can only ever see the
demo folder. Refuses to run without PT_DEMO=1.
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app import demo
from app.importer.book_writer import F, make, position

from . import market
from .universe import COMPANIES, GROUPS, Company

START = date(2021, 1, 4)
FILENAME = "Demo portfolio (made-up).xlsx"
BROKERS = ("IBKR", "Saxo")
LOTS = {"Trading": (4, 7), "Long term": (2, 4), "Tech leaders": (3, 5), "Dividend": (2, 4), "Europe": (2, 4), "Crypto": (3, 5)}
SELL_P = {"Trading": 0.85, "Crypto": 0.6, "Tech leaders": 0.5, "Long term": 0.3, "Dividend": 0.3, "Europe": 0.45}
MAX_HOLD = {"Trading": 120, "Crypto": 200}
DIVIDEND_YIELD = {"Dividend": 0.035, "Long term": 0.012, "Europe": 0.025}


@dataclass
class Lot:
    company: Company
    buy: date
    price: float
    shares: float
    broker: str
    sale: date | None = None
    sell_price: float | None = None


def _round(c: Company, p: float) -> float:
    return round(p, 1 if c.pence else 2)


def as_of(today: date | None = None) -> date:
    cal = market.calendar()
    return cal[market._upto(today or date.today()) - 1]


def plan(today: date | None = None) -> list[Lot]:
    """Every purchase of the demo portfolio, and its sale if it was sold (oldest lots sold first, so the sheet and the
    app's FIFO agree)."""
    end = as_of(today)
    days = [d for d in market.calendar() if START <= d <= end]
    lots: list[Lot] = []
    for c in COMPANIES:
        rng = random.Random(f"{c.ticker}-demo-v1")
        lo, hi = LOTS[c.group]
        idx = sorted(rng.sample(range(len(days) - 40), rng.randint(lo, hi)))
        prev_sale, selling = -1, True
        for i in idx:
            d = days[i]
            price = _round(c, market.close_on(c.ticker, d))
            scale = 0.01 if c.pence else 1.0
            local = rng.uniform(2500, 12000) / market.usd_per(c.currency, d)
            lot = Lot(c, d, price, float(max(1, round(local / (price * scale)))), rng.choice(BROKERS))
            p_sell = SELL_P[c.group] if prev_sale >= 0 else 1.0  # every stock sold some once: each sale group has sales
            if selling and rng.random() < p_sell:
                k = max(i + rng.randint(15, MAX_HOLD.get(c.group, 420)), prev_sale + rng.randint(1, 20))
                if k < len(days) - 1:
                    lot.sale, prev_sale = days[k], k
                    lot.sell_price = _round(c, market.close_on(c.ticker, days[k]))
                else:
                    selling = False
            else:
                selling = False  # FIFO: once a lot is kept, the later ones are kept too
            lots.append(lot)
    return lots


def workbook(lots: list[Lot], today: date | None = None) -> bytes:
    """The Live Portfolio tab of a made-up workbook: purchases and sales, the sales log, and the sale-group block."""
    end = as_of(today)
    events = sorted([(lot.buy, 0, n, lot) for n, lot in enumerate(lots)]
                    + [(lot.sale, 1, n, lot) for n, lot in enumerate(lots) if lot.sale], key=lambda e: (e[0], e[1], e[2]))
    positions: dict[int, dict] = {}
    sale_rows: list[tuple[date, int, Lot]] = []
    r = 2
    for d, kind, _, lot in events:
        c = lot.company
        kw = {"cur": c.currency, "broker": lot.broker, "pence": c.pence}
        if kind == 0 and lot.sale:  # bought, sold later: a closed purchase row with P/L 0
            positions[r] = position(r, d, c.name, lot.shares, lot.price, lot.price, "Closed", cost=0, pl=0, **kw)
        elif kind == 0:
            positions[r] = position(r, d, c.name, lot.shares, lot.price, _round(c, market.close_on(c.ticker, end)), "Open", **kw)
        else:  # the sale: dated on the sale day, buy price and sell price
            positions[r] = position(r, d, c.name, lot.shares, lot.price, lot.sell_price, "Closed", **kw)
            sale_rows.append((d, r, lot))
        r += 1
    hdr = r + 3
    rows: dict[int, dict] = {}
    by_group: dict[str, list[tuple[int, float]]] = {}
    r = hdr + 1
    for d, prow, lot in sorted(sale_rows, key=lambda x: (x[0], x[1])):
        c, s = lot.company, (0.01 if lot.company.pence else 1.0)
        cost = lot.shares * lot.price * s
        pl = lot.shares * lot.sell_price * s - cost
        usd = round(pl * market.usd_per(c.currency, d), 2)
        rows[r] = {"C": d, "D": c.name, "E": F(f"G{prow}", pl), "F": F(f"F{prow}", pl / cost), "G": usd}
        by_group.setdefault(c.group, []).append((r, usd))
        r += 1
    # One sale typed by hand (no link to a position row), so the Review page has something to show.
    typed = as_of(date(2022, 5, 16))
    rows[r] = {"C": typed, "D": "Old broker transfer (made-up)", "E": 420.0, "F": 0.12, "G": 420.0}
    r += 3
    cols = "HIJKLMNOP"
    names = [g for g in GROUPS if by_group.get(g)]
    rows[r] = {"D": "Tot", **{cols[i]: g for i, g in enumerate(names)}}
    rows[r + 1] = {cols[i]: F("+".join(f"G{x}" for x, _ in by_group[g]), sum(v for _, v in by_group[g])) for i, g in enumerate(names)}
    return make(positions, hdr, rows)


def _quarters(a: date, b: date):
    """The 15th of each quarter's last month after `a`, up to `b`."""
    y, q = a.year, (a.month - 1) // 3
    while True:
        d = date(y, q * 3 + 3, 15)
        if d > b:
            return
        if d > a:
            yield d
        y, q = (y + 1, 0) if q == 3 else (y, q + 1)


def deposits(lots: list[Lot], today: date | None = None) -> list[tuple[date, float]]:
    """Money paid in, in USD: whenever the cash wouldn't cover a purchase, a round deposit at the start of that month;
    one withdrawal later on."""
    end = as_of(today)
    flows: list[tuple[date, float]] = []
    moves = []
    for lot in lots:
        c, s = lot.company, (0.01 if lot.company.pence else 1.0)
        moves.append((lot.buy, -lot.shares * lot.price * s * market.usd_per(c.currency, lot.buy)))
        if lot.sale:
            moves.append((lot.sale, lot.shares * lot.sell_price * s * market.usd_per(c.currency, lot.sale)))
    cash = 0.0
    for d, amount in sorted(moves):
        if cash + amount < 0:
            need = -(cash + amount)
            dep = float(max(10_000, -(-need // 10_000) * 10_000))
            flows.append((date(d.year, d.month, 1) if date(d.year, d.month, 1) >= START - timedelta(days=3) else d, dep))
            cash += dep
        cash += amount
    w = date(end.year - 1, 9, 1)
    if cash > 25_000 and w > START:
        flows.append((w, -15_000.0))
    merged: dict[date, float] = {}
    for d, v in flows:
        merged[d] = merged.get(d, 0.0) + v
    return sorted(merged.items())


def build_tracker(today: date | None = None) -> dict:
    from sqlalchemy import select

    from app.db import models as m
    from app.engine.rebuild import name_key
    from app.services import benchmarks as BMS
    from app.services import entries as E
    from app.services import history as HS
    from app.services import portfolio as P

    m.init_db()
    end = as_of(today)
    lots = plan(today)
    db = m.SessionLocal()
    try:
        P.do_import(db, FILENAME, workbook(lots, today))
        for c in COMPANIES:
            key = name_key(c.name)
            if c.us:
                HS.set_ticker(db, key, c.ticker)
            db.merge(m.StockSector(group_key=key, sector=c.sector, source="you", confirmed=True))
        db.commit()
        for d, amount in deposits(lots, today):
            P.add_capital(db, {"date": d.isoformat(), "amount": amount, "currency": "USD", "account": "IBKR",
                               "note": "made-up deposit" if amount > 0 else "made-up withdrawal"})
        for c in COMPANIES:  # quarterly dividends on what was held, for the dividend-paying ones
            y = DIVIDEND_YIELD.get(c.group)
            if not y:
                continue
            mine = [x for x in lots if x.company is c]
            for q in _quarters(min(x.buy for x in mine), end):
                held = sum(x.shares for x in mine if x.buy < q and (x.sale is None or x.sale > q))
                if held:
                    s = 0.01 if c.pence else 1.0
                    gross = round(held * market.close_on(c.ticker, q) * s * y / 4, 2)
                    E.add_dividend(db, {"date": q.isoformat(), "name": c.name, "amount": round(gross * 0.85, 2),
                                        "tax": round(gross * 0.15, 2), "currency": c.currency, "note": "made-up"})
        # One purchase entered in the app after the workbook, as you would on the Trades page.
        h = next(c for c in COMPANIES if c.ticker == "HLXA")
        when = market.calendar()[market._upto(end) - 3]
        E.add_trade(db, {"kind": "buy", "date": when.isoformat(), "name": h.name, "shares": 10,
                         "price": _round(h, market.close_on(h.ticker, when)), "currency": "USD", "broker": "IBKR",
                         "fee": 1.0, "note": "made-up app trade"})
        for _ in range(20):  # daily prices (the synthetic market answers instantly)
            r = HS.run_batch(db)
            if not r["remaining"]:
                break
        for c in COMPANIES:
            if not c.us:
                first = min(x.buy for x in lots if x.company is c) - timedelta(days=10)
                csv = "Date,Close\n" + "".join(f"{b['date'].isoformat()},{b['close']}\n" for b in market.bars(c.ticker, first, end))
                HS.upload_csv(db, f"{name_key(c.name)}|{c.currency}", csv.encode())
        BMS.refresh(db)
        P._invalidate()
        HS._invalidate()
        _journal(db)
        from app.services import breakeven as BE
        BE.put(db, [{"id": "demo1", "name": "Example: 6 shares at 883 (made-up)", "currency": "USD", "lots": [{"shares": 6, "price": 883}],
                     "price": 633.55, "steps": [1, 3, 6, 7, 17], "target": 700}])
        db.merge(m.Setting(key="demo", value={"built_at": datetime.now(timezone.utc).isoformat(), "as_of": end.isoformat()}))
        db.commit()
        n_open = sum(1 for x in lots if not x.sale)
        return {"lots": len(lots), "sales": len(lots) - n_open, "imports": len(list(db.scalars(select(m.Import))))}
    finally:
        db.close()


NOTES_BUY = {"Fibonacci bounce": "Pulled back to the 61.8% level and held it for three days.",
             "Breakout": "Closed above the range high on rising volume.",
             "Dip buy": "Down sharply after the market sell-off; nothing changed in the business.",
             "Long-term hold": "Quality compounder, adding on weakness.",
             "Momentum": "Strongest name in its sector this quarter."}
SELL = [("Hit target", None), ("Took profit early", "Sold half way to the target; next time scale out instead."),
        ("Hit stop", "The stop did its job."), ("Nervous / market fall", "Sold on a red day near the low: write the plan down first."),
        ("Idea no longer holds", None)]


def _journal(db) -> None:
    """Made-up journal entries on about half the trades, so the Journal pages have something to show."""
    from app.services import journal as JS
    rows = JS.view(db)["rows"]
    rng = random.Random("journal-demo-v1")
    for r in rows:
        if r["date"] >= (date.today() - timedelta(days=JS.INBOX_DAYS)).isoformat() or rng.random() < 0.45:
            continue  # recent trades stay on the To journal list; others stay unwritten
        if r["kind"] == "buy":
            reason = rng.choice(list(NOTES_BUY))
            p = r["price"]
            JS.save(db, r["key"], {"reasons": [reason] + ([rng.choice(["Alpha pick", "Earnings"])] if rng.random() < 0.25 else []),
                                   "target": round(p * rng.uniform(1.15, 1.6), 2), "stop": round(p * rng.uniform(0.82, 0.93), 2),
                                   "horizon_days": rng.choice([30, 60, 90, 180, 365]), "confidence": rng.randint(2, 5),
                                   "notes": NOTES_BUY[reason] + " (made-up)"})
        else:
            why, lesson = rng.choice(SELL)
            JS.save(db, r["key"], {"sell_reason": why, "lesson": lesson, "notes": "(made-up)"})
    JS.skip(db, older=True)


def build_research() -> dict:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import select

    from research.api import routes as R
    from research.core.config import settings
    from research.data import seed
    from research.db import models as rm
    from research.db.session import SessionLocal
    from research.services import scanner

    cfg = Config(str(demo.BACKEND_DIR / "research" / "alembic.ini"))
    cfg.set_main_option("script_location", str(demo.BACKEND_DIR / "research" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    seed.run(reseed=True)
    with SessionLocal() as db:
        R.refresh_everything(db)          # holdings from the demo tracker, then their prices, sector ETFs, alerts
        R.watch_holdings(db)              # every US holding on the watchlist
        for c in COMPANIES:               # and a few you sold, to watch for a way back in
            if c.ticker in ("QLTS", "AQMD", "UBRT", "BTVA"):
                try:
                    R.track(R.TrackIn(ticker=c.ticker, exchange="US" if c.us else c.mic, watch=True,
                                      note="made-up: sold, watching"), db)
                except Exception:  # noqa: BLE001  (a demo extra; never fail the build for it)
                    pass
        R.refresh_everything(db)
        listings = len(db.scalars(select(rm.Listing.id)).all())
        watch = len(db.scalars(select(rm.WatchlistItem.id)).all())
        try:
            scanner.run_scan(db, "medium")
            db.commit()
        except Exception:  # noqa: BLE001
            pass
    return {"listings": listings, "watchlist": watch}


def build_ideas() -> int:
    """Made-up trade ideas: one close to a level, one that hit its entry last month, one new stock, one dropped."""
    from app.db import models as m
    from app.services import ideas as IS
    db = m.SessionLocal()
    try:
        def make(ticker, stock, side, levels, reasons, notes, ago=0, status=None, conf=3):
            d = IS.create(db, {"ticker": ticker, "stock": stock, "side": side, "levels": levels, "reasons": reasons,
                               "notes": notes + " (made-up)", "confidence": conf})
            i = db.get(m.JournalIdea, d["id"])
            if ago:
                i.created_at = datetime.now(timezone.utc) - timedelta(days=ago)
            if status:
                i.status = status
            db.commit()
        last = lambda t: market.bars(t)[-1]["close"]  # noqa: E731
        q = last("QLTS")
        make("QLTS", "Quantum Lattice Systems", "buy",
             [{"label": "Watch: back near support", "kind": "alert", "price": round(q * 0.985, 2)},
              {"label": "Entry: 61.8% Fibonacci", "kind": "entry", "price": round(q * 0.9, 2)},
              {"label": "Stop", "kind": "stop", "price": round(q * 0.78, 2)}, {"label": "Target", "kind": "target", "price": round(q * 1.35, 2)}],
             ["Fibonacci bounce"], "Sold too early last time; buy back on a pullback to the 61.8% level.", conf=4)
        rows = market.bars("AQMD", date.today() - timedelta(days=30))
        lo = min(r["low"] for r in rows[5:])
        make("AQMD", "Aquila Medical Devices", "buy",
             [{"label": "Entry", "kind": "entry", "price": round(lo * 1.01, 2)}, {"label": "Stop", "kind": "stop", "price": round(lo * 0.88, 2)},
              {"label": "Target", "kind": "target", "price": round(lo * 1.4, 2)}], ["Dip buy"], "Oversold after the trial news.", ago=30)
        k = last("KSTR")
        make("KSTR", "Kestrel Aerospace", "watch",
             [{"label": "Breakout above the range", "kind": "alert", "price": round(k * 1.08, 2)},
              {"label": "Back to the 200-day average", "kind": "alert", "price": round(k * 0.9, 2)}],
             ["Breakout"], "New name on the radar; wait for a breakout or a pullback.", conf=2)
        make("UBRT", "Urbanrise Retail", "buy", [{"label": "Entry", "kind": "entry", "price": round(last("UBRT") * 0.8, 2)}],
             ["Dip buy"], "Dropped: the story changed.", status="dropped", conf=2)
        IS.check(db)
        return len(IS.view(db, run_check=False)["ideas"])
    finally:
        db.close()


def build(today: date | None = None) -> dict:
    if not demo.DEMO:
        raise SystemExit("app.demo.build only runs in demo mode (PT_DEMO=1): it must never touch your real data.")
    from app.core_env import load_env
    load_env()
    from . import network
    network.install()
    demo.DEMO_DIR.mkdir(parents=True, exist_ok=True)
    for p in (demo.TRACKER_DB, demo.RESEARCH_DB):
        if p.exists():
            p.unlink()
    out = {"tracker": build_tracker(today), "research": build_research()}
    out["ideas"] = build_ideas()
    return out


def main(argv: list[str]) -> None:
    if "--if-missing" in argv and demo.TRACKER_DB.exists() and demo.RESEARCH_DB.exists():
        print("Demo data is there already.")
        return
    print("Building the demo (made-up data)…")
    print(build())


if __name__ == "__main__":
    main(sys.argv[1:])
