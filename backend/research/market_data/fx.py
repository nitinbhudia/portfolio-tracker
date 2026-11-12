"""Real FX history from ECB reference rates, stored in fx_rates (source 'ecb' / 'ecb_derived').

Stored pairs: EURUSD and EURCHF as published; USDCHF derived as EURCHF / EURUSD on the same
date. Real rates are never used for the synthetic demo portfolio (see portfolio.FxBook).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from research.db import models as m

from .ecb import PROVIDER, EcbClient
from .tiingo import MarketDataError

HISTORY_YEARS = 5
OVERLAP_DAYS = 7
DERIVED = "ecb_derived"
STATE_KEY = "ecb_last_refresh"


def _last(db: Session) -> date | None:
    return db.scalar(select(func.max(m.FxRate.date)).where(m.FxRate.source == PROVIDER))


def refresh(db: Session, client: EcbClient | None = None, today: date | None = None) -> dict:
    client = client or EcbClient()
    today = today or date.today()
    last = _last(db)
    start = (last - timedelta(days=OVERLAP_DAYS)) if last else today - timedelta(days=int(365.25 * HISTORY_YEARS))
    ok = True
    try:
        rates = client.daily(["USD", "CHF"], start)
    except MarketDataError:
        ok = False
        raise
    finally:
        db.add(m.ProviderRequest(provider=PROVIDER, symbol="EXR:USD+CHF", ok=ok, at=datetime.now(timezone.utc)))
        db.commit()
    by_day: dict[date, dict[str, float]] = {}
    for r in rates:
        if r.date >= start:  # only the range we replace below, even if the service sends more
            by_day.setdefault(r.date, {})[r.currency] = r.rate
    db.execute(delete(m.FxRate).where(m.FxRate.date >= start, or_(m.FxRate.source == PROVIDER, m.FxRate.source == DERIVED)))
    added = 0
    for d, v in sorted(by_day.items()):
        if "USD" in v:
            db.add(m.FxRate(base="EUR", quote="USD", date=d, rate=Decimal(str(v["USD"])), source=PROVIDER, is_synthetic=False))
        if "CHF" in v:
            db.add(m.FxRate(base="EUR", quote="CHF", date=d, rate=Decimal(str(v["CHF"])), source=PROVIDER, is_synthetic=False))
        if "USD" in v and "CHF" in v:
            usdchf = (Decimal(str(v["CHF"])) / Decimal(str(v["USD"]))).quantize(Decimal("1e-10"))
            db.add(m.FxRate(base="USD", quote="CHF", date=d, rate=usdchf, source=DERIVED, is_synthetic=False))
        if d > (last or date.min):
            added += 1
    stamp = {"at": datetime.now(timezone.utc).isoformat(), "from": start.isoformat()}
    row = db.get(m.AppSetting, STATE_KEY)
    if row is None:
        db.add(m.AppSetting(key=STATE_KEY, value_json=stamp))
    else:
        row.value_json = stamp
    db.commit()
    new_last = _last(db)
    return {"status": "updated" if added else "up_to_date", "new_days": added,
            "last_date": new_last.isoformat() if new_last else None}


def status(db: Session) -> dict:
    last = _last(db)
    n = db.scalar(select(func.count(m.FxRate.id)).where(m.FxRate.source == PROVIDER)) or 0
    latest = {}
    for base, quote in (("EUR", "USD"), ("EUR", "CHF"), ("USD", "CHF")):
        r = db.scalar(select(m.FxRate).where(m.FxRate.base == base, m.FxRate.quote == quote,
                                            m.FxRate.is_synthetic.is_(False)).order_by(m.FxRate.date.desc()).limit(1))
        if r:
            latest[f"{base}{quote}"] = {"rate": float(r.rate), "date": r.date.isoformat(), "source": r.source}
    row = db.get(m.AppSetting, STATE_KEY)
    return {"provider": PROVIDER, "configured": True, "last_date": last.isoformat() if last else None,
            "observations": n, "latest": latest, "last_refresh": row.value_json if row else None,
            "note": "ECB euro reference rates, published around 16:00 CET on TARGET working days, "
                    "for information purposes only. USDCHF is derived (EURCHF ÷ EURUSD).",
            "provenance": {"source": PROVIDER, "is_synthetic": False, "as_of": last.isoformat() if last else None,
                           "exchange_timezone": "Europe/Berlin", "is_delayed": False, "delay_minutes": None,
                           "stale": last is None or (date.today() - last).days > 5, "data_type": "end_of_day"}}


def rate(db: Session, f: str, t: str, on: date) -> dict | None:
    """Real (ECB) rate f->t on or before `on`, directly or inverted. None if not stored."""
    for base, quote, inv in ((f, t, False), (t, f, True)):
        r = db.scalar(select(m.FxRate).where(m.FxRate.base == base, m.FxRate.quote == quote, m.FxRate.date <= on,
                                            m.FxRate.is_synthetic.is_(False)).order_by(m.FxRate.date.desc()).limit(1))
        if r is not None:
            v = Decimal(r.rate)
            return {"rate": (Decimal(1) / v) if inv else v, "date": r.date.isoformat(), "source": r.source,
                    "stored_pair": f"{base}{quote}"}
    return None
