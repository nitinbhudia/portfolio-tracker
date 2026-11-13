"""Seed the database with the synthetic universe, FX rates and the seed portfolio.

Usage:  python -m research.data.seed [--reseed]
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from research.core.config import settings
from research.db import models as m
from research.db.session import SessionLocal

from . import synthetic
from .universe import EXCHANGES, FX_PAIRS, GAPS, LISTINGS

PORTFOLIO_CSV = Path(__file__).with_name("seed_portfolio.csv")


class HoldingImportError(ValueError):
    pass


def _wipe(db: Session) -> None:
    """Remove the synthetic demo only. Real market data, broker data and settings are kept."""
    syn_ids = select(m.Listing.id).where(m.Listing.namespace == "synthetic")
    syn_inst = select(m.Listing.instrument_id).where(m.Listing.namespace == "synthetic")
    # Everything that points at a synthetic listing goes too: rebuilt listings get new ids, and a left-over
    # row could otherwise end up attached to a different instrument.
    for model in (m.TechnicalScore, m.FibonacciResult, m.SwingPoint, m.IndicatorResult,
                  m.Holding, m.WatchlistItem, m.Alert, m.AlertState, m.BacktestRun, m.PriceBar):
        db.execute(delete(model).where(model.listing_id.in_(syn_ids)))
    # A scan run is a snapshot of the whole universe: drop runs that included synthetic listings.
    runs = select(m.ScanResult.run_id).where(m.ScanResult.listing_id.in_(syn_ids)).distinct()
    run_ids = list(db.scalars(runs).all())
    if run_ids:
        db.execute(delete(m.ScanResult).where(m.ScanResult.run_id.in_(run_ids)))
        db.execute(delete(m.ScanRun).where(m.ScanRun.id.in_(run_ids)))
    db.execute(delete(m.AppSetting).where(m.AppSetting.key == "alert_rotation_state"))
    inst_ids = [i for i in db.scalars(syn_inst).all()]
    db.execute(delete(m.Listing).where(m.Listing.namespace == "synthetic"))
    db.execute(delete(m.Instrument).where(m.Instrument.id.in_(inst_ids)))
    db.execute(delete(m.FxRate).where(m.FxRate.is_synthetic.is_(True)))


def seed_universe(db: Session, end: date | None = None, n: int | None = None) -> None:
    end = end or settings.synthetic_end_date
    n = n or settings.synthetic_days
    for mic, name, tz, ccy, close_time in EXCHANGES:
        if db.get(m.Exchange, mic) is None:
            db.add(m.Exchange(mic=mic, name=name, timezone=tz, currency=ccy, close_time=close_time))
    db.flush()
    for i, (ticker, mic, ccy, cls, name, sector, tracks, p0, vol, bench) in enumerate(LISTINGS):
        inst = m.Instrument(isin=None if cls == "index" else f"XX{i:010d}", name=name,
                            asset_class=cls, sector=sector, tracks=tracks,
                            is_holdable=cls != "index")
        db.add(inst)
        db.flush()
        lst = m.Listing(instrument_id=inst.id, exchange_mic=mic, ticker=ticker,
                        currency=ccy, is_benchmark=bench)
        db.add(lst)
        db.flush()
        rows = synthetic.generate_ohlcv(ticker, mic, p0, vol, end, n,
                                        with_volume=cls != "index", gap=GAPS.get((ticker, mic)))
        db.add_all(m.PriceBar(listing_id=lst.id, interval="1d", source=synthetic.SOURCE,
                              is_synthetic=True, **{k: (Decimal(str(v)) if isinstance(v, float) else v)
                                                    for k, v in r.items()})
                   for r in rows)
    _seed_sector_demo(db, end, n)
    for base, quote, start, vol in FX_PAIRS:
        db.add_all(m.FxRate(base=base, quote=quote, date=r["date"], rate=Decimal(str(r["rate"])),
                            source=synthetic.SOURCE, is_synthetic=True)
                   for r in synthetic.generate_fx(base, quote, start, vol, end, n))
    for key, value in (("base_currency", settings.base_currency),
                       ("default_sensitivity", settings.default_sensitivity),
                       ("theme", "system"), ("holdings_source", "synthetic")):
        if db.get(m.AppSetting, key) is None:
            db.add(m.AppSetting(key=key, value_json=value))
    db.flush()


def _add_synthetic(db: Session, ticker: str, mic: str, name: str, cls: str, sector: str | None,
                   tracks: str | None, rows: list[dict], isin: str, currency: str = "USD") -> None:
    inst = m.Instrument(isin=isin, name=name, asset_class=cls, sector=sector, tracks=tracks, is_holdable=True)
    db.add(inst)
    db.flush()
    lst = m.Listing(instrument_id=inst.id, exchange_mic=mic, ticker=ticker, currency=currency, is_benchmark=False)
    db.add(lst)
    db.flush()
    db.add_all(m.PriceBar(listing_id=lst.id, interval="1d", source=synthetic.SOURCE, is_synthetic=True,
                          **{k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in r.items()})
               for r in rows)


def _seed_sector_demo(db: Session, end: date, n: int) -> None:
    """Synthetic SPY + 11 US and EXSA + 19 European sector ETFs for the Sector Rotation demo (labelled SYNTHETIC)."""
    from .sectors import EU, EU_BENCHMARK, SYNTHETIC_EU_PROFILE, SYNTHETIC_EXSA, SYNTHETIC_PROFILE, SYNTHETIC_SPY, US
    t, mic, p0, vol = SYNTHETIC_SPY
    market = synthetic.generate_ohlcv(t, mic, p0, vol, end, n)
    _add_synthetic(db, t, mic, "SPDR S&P 500 ETF (synthetic)", "etf", None, "S&P 500", market, "XX0000000100")
    for i, e in enumerate(US.etfs, 1):
        beta, idio = SYNTHETIC_PROFILE[e.ticker]
        rows = synthetic.generate_sector_ohlcv(e.ticker, e.mic, market, beta, idio)
        _add_synthetic(db, e.ticker, e.mic, f"{e.name} (synthetic)", "etf", e.sector, f"{e.sector} sector",
                       rows, f"XX{100 + i:010d}")
    t, mic, p0, vol = SYNTHETIC_EXSA
    eu_market = synthetic.generate_ohlcv(t, mic, p0, vol, end, n)
    _add_synthetic(db, t, mic, f"{EU_BENCHMARK.name} (synthetic)", "etf", None, "STOXX Europe 600", eu_market,
                   "XX0000000200", "EUR")
    for i, e in enumerate(EU.etfs, 1):
        beta, idio = SYNTHETIC_EU_PROFILE[e.ticker]
        rows = synthetic.generate_sector_ohlcv(e.ticker, e.mic, eu_market, beta, idio, start_price=40.0)
        _add_synthetic(db, e.ticker, e.mic, f"{e.name} (synthetic)", "etf", e.sector, f"STOXX Europe 600 {e.sector}",
                       rows, f"XX{200 + i:010d}", "EUR")


def import_holdings(db: Session, path: Path = PORTFOLIO_CSV) -> int:
    count = 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            lst = db.scalar(select(m.Listing).where(m.Listing.namespace == "synthetic", m.Listing.ticker == row["ticker"],
                                                    m.Listing.exchange_mic == row["mic"]))
            if lst is None:
                raise HoldingImportError(f"unknown listing {row['ticker']}@{row['mic']}")
            if not lst.instrument.is_holdable:
                raise HoldingImportError(f"{row['ticker']} is an index and cannot be held")
            db.add(m.Holding(listing_id=lst.id, quantity=Decimal(row["quantity"]),
                             avg_cost=Decimal(row["avg_cost"]),
                             opened_at=date.fromisoformat(row["opened_at"]) if row.get("opened_at") else None))
            count += 1
    db.flush()
    return count


def use_tracker_holdings_once(db: Session) -> bool:
    """Since Research became part of Portfolio Tracker, its holdings come from the tracker. Switch an existing
    Fibonacci AI database over once (a later choice in Research → Settings is kept)."""
    if db.get(m.AppSetting, "tracker_switch_done") is not None:
        return False
    row = db.get(m.AppSetting, "holdings_source")
    if row is None:
        db.add(m.AppSetting(key="holdings_source", value_json="tracker"))
    else:
        row.value_json = "tracker"
    db.add(m.AppSetting(key="tracker_switch_done", value_json=True))
    db.commit()
    return True


def run(reseed: bool = True) -> None:
    from research.services.analysis import persist_latest_all

    with SessionLocal() as db:
        if use_tracker_holdings_once(db):
            print("Research: holdings now come from Portfolio Tracker.")
        if not reseed and db.scalar(select(m.Listing.id).where(m.Listing.namespace == "synthetic").limit(1)) is not None:
            print("Database already seeded (use --reseed to rebuild).")
            return
        _wipe(db)
        seed_universe(db)
        n = import_holdings(db)
        persist_latest_all(db)
        db.commit()
        print(f"Seeded {len(LISTINGS)} listings + 32 sector-demo ETFs, {n} holdings (SYNTHETIC data).")


if __name__ == "__main__":
    run(reseed="--reseed" in sys.argv)
