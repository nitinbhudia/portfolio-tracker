"""Assembles indicators, swings, Fibonacci and scores for one listing as of a date.

No look-ahead: the bar history is truncated at ``as_of`` *before* anything is
calculated, and Fibonacci uses only swings confirmed on or before the scoring bar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from research.core.calendars import holidays_for
from research.core.config import settings
from research.core.hashing import stable_hash
from research.db import models as m
from research.engine import fibonacci, indicators, resample, scoring, setups, swings

INTERVAL = "1d"


class NotFound(LookupError):
    pass


class BadRequest(ValueError):
    pass


@dataclass
class Bars:
    listing: m.Listing
    df: pd.DataFrame  # columns: date, open, high, low, close, volume, source, is_synthetic, ...


def load_bars(db: Session, listing_id: int, as_of: date | None = None) -> Bars:
    lst = db.get(m.Listing, listing_id)
    if lst is None:
        raise NotFound(f"listing {listing_id} not found")
    q = select(m.PriceBar).where(m.PriceBar.listing_id == listing_id,
                                 m.PriceBar.interval == INTERVAL)
    if as_of is not None:
        q = q.where(m.PriceBar.date <= as_of)
    rows = db.scalars(q.order_by(m.PriceBar.date)).all()
    df = pd.DataFrame([{
        "date": r.date, "open": float(r.open), "high": float(r.high), "low": float(r.low),
        "close": float(r.close), "volume": float(r.volume) if r.volume is not None else np.nan,
        "source": r.source, "is_synthetic": r.is_synthetic, "is_delayed": r.is_delayed,
        "delay_minutes": r.delay_minutes, "adjustment": r.adjustment,
    } for r in rows])
    return Bars(lst, df)


def _f(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


NO_HOLIDAYS = np.array([], dtype="datetime64[D]")


def _bdays_between(a: date, b: date, holidays=NO_HOLIDAYS) -> int:
    """Trading days strictly after a up to and including b."""
    if b <= a:
        return 0
    one = np.timedelta64(1, "D")
    return int(np.busday_count(np.datetime64(a, "D") + one, np.datetime64(b, "D") + one, holidays=holidays))


def missing_between(dates: list[date], holidays=NO_HOLIDAYS) -> np.ndarray:
    """missing[j] = trading days missing between bar j-1 and bar j (missing[0] = 0)."""
    if len(dates) < 2:
        return np.zeros(len(dates), dtype=int)
    d = np.array(dates, dtype="datetime64[D]")
    return np.concatenate([[0], np.busday_count(d[:-1], d[1:], holidays=holidays) - 1])


def find_gaps(dates: list[date], holidays=NO_HOLIDAYS) -> list[dict]:
    gaps = []
    miss = missing_between(dates, holidays)
    for j in np.flatnonzero(miss > 0):
        gaps.append({"after": dates[j - 1].isoformat(), "before": dates[j].isoformat(),
                     "missing_business_days": int(miss[j])})
    return gaps


def provenance(listing: m.Listing, df: pd.DataFrame) -> dict:
    hol = holidays_for(listing.exchange_mic, listing.namespace)
    if df.empty:
        return {"source": None, "is_synthetic": None, "as_of": None,
                "exchange_timezone": listing.exchange.timezone, "is_delayed": None,
                "delay_minutes": None, "stale": True, "latest_bar_date": None}
    last = df.iloc[-1]
    tz = ZoneInfo(listing.exchange.timezone)
    hh, mm = (int(x) for x in listing.exchange.close_time.split(":"))
    as_of_local = datetime.combine(last["date"], time(hh, mm), tzinfo=tz)
    synthetic = bool(df["is_synthetic"].all())
    ref = settings.synthetic_end_date if synthetic else date.today()
    stale = _bdays_between(last["date"], ref, hol) > settings.stale_after_business_days
    return {
        "source": str(last["source"]),
        "is_synthetic": synthetic,
        "as_of": as_of_local.astimezone(ZoneInfo("UTC")).isoformat(),
        "exchange_timezone": listing.exchange.timezone,
        "is_delayed": bool(last["is_delayed"]),
        "delay_minutes": int(last["delay_minutes"]),
        "stale": bool(stale),
        "latest_bar_date": last["date"].isoformat(),
        "data_type": "end_of_day",
        "price_adjustment": str(last.get("adjustment", "none")),
    }


def input_hash(df: pd.DataFrame) -> str:
    rows = df[["date", "open", "high", "low", "close", "volume"]].astype(object).values.tolist()
    return stable_hash([[r[0].isoformat(), *[_f(v) for v in r[1:]]] for r in rows])


def _gap_in_window(missing: np.ndarray, idx: int, lookback: int) -> bool:
    lo = max(0, idx - lookback + 1)
    return bool((missing[lo + 1 : idx + 1] > settings.gap_threshold_business_days).any())


def _snapshot(idx: int, df: pd.DataFrame, ind: dict, sw: list, is_index: bool) -> dict:
    close = df["close"].to_numpy()
    vals = {k: _f(v[idx]) for k, v in ind.items()}
    inputs = {"close": float(close[idx]),
              "prev_close": float(close[idx - 1]) if idx > 0 else None, **vals}
    fib = fibonacci.analyse(swings.confirmed_as_of(sw, idx), float(close[idx]), vals.get("atr14"))
    scores = {h: scoring.score(h, inputs, fib) for h in scoring.HORIZONS}
    return {"inputs": inputs, "fib": fib, "scores": scores}


def _swing_out(s: swings.Swing, dates: list[date]) -> dict:
    return {"kind": s.kind, "date": dates[s.index].isoformat(),
            "confirmed_date": dates[s.confirmed_index].isoformat(), "price": s.price}


def calendar_name(listing: m.Listing) -> str:
    hol = holidays_for(listing.exchange_mic, listing.namespace)
    if not len(hol):
        return "Mon-Fri (no holidays)"
    return {"XETR": "Xetra holidays", "XAMS": "Euronext holidays", "XPAR": "Euronext holidays", "XSWX": "SIX holidays",
            "XLON": "London (UK bank) holidays"}.get(listing.exchange_mic, "NYSE holidays")


def compute_analysis(bars: Bars, sensitivity: str | float = "medium",
                     include_series: bool = True, interval: str = INTERVAL,
                     daily_df: pd.DataFrame | None = None, timeframe: dict | None = None) -> dict:
    """``bars`` are daily bars, or resampled bars when ``interval`` is 1w/1mo (then
    ``daily_df`` holds the daily bars they came from, used for provenance and gaps)."""
    lst, df = bars.listing, bars.df
    daily = df if daily_df is None else daily_df
    is_index = lst.instrument.asset_class == "index"
    prov = provenance(lst, daily)
    meta = {"listing": listing_dict(lst), "provenance": prov}
    try:
        k = swings.resolve_k(sensitivity)
    except ValueError as e:
        raise BadRequest(str(e)) from e
    if len(df) < 2:
        return {**meta, "status": "no_price_history" if df.empty else "insufficient_history", "bars_available": len(df)}

    dates = list(df["date"])
    o, h, l_, c, v = (df[col].to_numpy() for col in ("open", "high", "low", "close", "volume"))
    ind = indicators.compute_all(o, h, l_, c, v)
    sw = swings.detect_swings(h, l_, ind["atr14"], k)
    idx = len(df) - 1
    snap = _snapshot(idx, df, ind, sw, is_index)

    params = {"sensitivity": sensitivity, "atr_multiple": k, "interval": interval,
              "versions": [indicators.CALC_VERSION, swings.CALC_VERSION,
                           fibonacci.CALC_VERSION, scoring.SCORE_VERSION]}
    p_hash, i_hash = stable_hash(params), input_hash(df)

    latest = {}
    hol = holidays_for(lst.exchange_mic, lst.namespace)
    daily_gaps = find_gaps(list(daily["date"]), hol)
    if interval == INTERVAL:
        miss = missing_between(dates, hol)

        def gap_in(lookback: int) -> bool:
            return _gap_in_window(miss, idx, lookback)
    else:
        def gap_in(lookback: int) -> bool:  # any daily gap inside the periods the indicator uses
            start = dates[max(0, idx - lookback)].isoformat()
            return any(g["before"] > start for g in daily_gaps)
    for name, arr in ind.items():
        val = _f(arr[idx])
        if name == "relvol20" and is_index:
            status = "not_applicable"
        elif val is None:
            status = "insufficient_history"
        elif gap_in(indicators.LOOKBACK[name]):
            status = "gap_in_window"
        else:
            status = "ok"
        latest[name] = {"value": val, "data_quality": status}

    for sc in snap["scores"].values():
        sc["params_hash"], sc["input_hash"] = p_hash, i_hash
    fib = {**snap["fib"], "atr_multiple": k, "params_hash": p_hash, "input_hash": i_hash}
    if fib.get("status") == "ok":
        for key in ("swing_high", "swing_low"):
            s = fib[key]
            fib[key] = {**s, "date": dates[s["index"]].isoformat(),
                        "confirmed_date": dates[s["confirmed_index"]].isoformat()}

    prev_short = None
    if idx >= 5:
        prev_short = _snapshot(idx - 5, df, ind, sw, is_index)["scores"]["short"]["total"]

    confirmed = swings.confirmed_as_of(sw, idx)
    detected = setups.detect_all(o, h, l_, c, v, ind, snap["fib"], idx, has_volume=not is_index)
    detected["input_hash"] = i_hash
    out = {
        **meta,
        "status": "ok",
        "as_of": dates[idx].isoformat(),
        "interval": interval,
        "timeframe": timeframe or {"interval": interval, "last_bar_in_progress": False},
        "sensitivity": sensitivity,
        "atr_multiple": k,
        "bars_available": len(df),
        "params_hash": p_hash,
        "input_hash": i_hash,
        "data_quality": {"gaps": daily_gaps,
                         "calendar": calendar_name(lst),
                         "volume_available": not is_index,
                         "gap_threshold_business_days": settings.gap_threshold_business_days},
        "latest": {"close": float(c[idx]), "prev_close": _f(c[idx - 1]), "indicators": latest},
        "swings": [_swing_out(s, dates) for s in confirmed],
        "fibonacci": fib,
        "scores": snap["scores"],
        "short_score_5_bars_ago": prev_short,
        "setups": detected,
    }
    if include_series:
        out["series"] = {
            "dates": [d.isoformat() for d in dates],
            "open": o.tolist(), "high": h.tolist(), "low": l_.tolist(), "close": c.tolist(),
            "volume": [_f(x) for x in v],
            **{name: [_f(x) for x in arr] for name, arr in ind.items()},
        }
    return out


SPARK_POINTS = 60


def _downsample(vals: list[float], n: int = SPARK_POINTS) -> list[float]:
    if len(vals) <= n:
        return vals
    step = (len(vals) - 1) / (n - 1)
    return [vals[round(i * step)] for i in range(n)]


def sparklines(df: pd.DataFrame) -> dict:
    """Closes for the last 3 months (63 trading days) and year-to-date, downsampled for display.

    YTD starts from the last close of the previous year when available (standard YTD basis).
    Changes are computed from the full-resolution series, not the downsampled one.
    """
    if df.empty:
        return {"m3": [], "ytd": [], "m3_change_pct": None, "ytd_change_pct": None, "m3_start": None, "ytd_start": None}
    closes, dates = df["close"].tolist(), list(df["date"])
    m3 = closes[-64:] if len(closes) > 1 else closes
    year = dates[-1].year
    first_this_year = next(i for i, d in enumerate(dates) if d.year == year)
    ytd = closes[max(0, first_this_year - 1):]
    pct = lambda v: (v[-1] / v[0] - 1) * 100 if len(v) > 1 and v[0] else None
    return {"m3": [round(x, 4) for x in _downsample(m3)], "ytd": [round(x, 4) for x in _downsample(ytd)],
            "m3_change_pct": pct(m3), "ytd_change_pct": pct(ytd),
            "m3_start": dates[-len(m3)].isoformat(), "ytd_start": dates[max(0, first_this_year - 1)].isoformat()}


def listing_dict(lst: m.Listing) -> dict:
    i = lst.instrument
    return {"id": lst.id, "namespace": lst.namespace, "ticker": lst.ticker, "exchange": lst.exchange_mic,
            "exchange_name": lst.exchange.name, "currency": lst.currency, "name": i.name,
            "isin": i.isin, "asset_class": i.asset_class, "sector": i.sector,
            "tracks": i.tracks, "is_holdable": i.is_holdable, "is_benchmark": lst.is_benchmark}


def analyse_listing(db: Session, listing_id: int, as_of: date | None = None,
                    sensitivity: str | float = "medium", include_series: bool = True,
                    interval: str = INTERVAL) -> dict:
    """``as_of`` truncates the *daily* bars before any resampling, so weekly/monthly views have no look-ahead."""
    if interval not in resample.INTERVALS:
        raise BadRequest(f"interval must be one of {resample.INTERVALS}")
    bars = load_bars(db, listing_id, as_of)
    if interval == INTERVAL:
        return compute_analysis(bars, sensitivity, include_series)
    hol = holidays_for(bars.listing.exchange_mic, bars.listing.namespace)
    rs, meta = resample.resample(bars.df, interval, hol)
    return compute_analysis(Bars(bars.listing, rs), sensitivity, include_series, interval=interval,
                            daily_df=bars.df, timeframe=meta)


def persist_latest(db: Session, listing_id: int, sensitivity: str = "medium") -> dict:
    """Store the latest calculation (indicators, swings, Fibonacci, scores) for audit."""
    a = analyse_listing(db, listing_id, sensitivity=sensitivity, include_series=False)
    if a["status"] != "ok":
        return a
    for model in (m.IndicatorResult, m.SwingPoint, m.FibonacciResult, m.TechnicalScore):
        db.execute(delete(model).where(model.listing_id == listing_id))
    d = date.fromisoformat(a["as_of"])
    for name, item in a["latest"]["indicators"].items():
        db.add(m.IndicatorResult(listing_id=listing_id, interval=INTERVAL, date=d, name=name,
                                 params_json={}, value=item["value"],
                                 calc_version=indicators.CALC_VERSION,
                                 params_hash=a["params_hash"], input_hash=a["input_hash"]))
    for s in a["swings"]:
        db.add(m.SwingPoint(listing_id=listing_id, interval=INTERVAL, atr_multiple=a["atr_multiple"],
                            date=date.fromisoformat(s["date"]),
                            confirmed_date=date.fromisoformat(s["confirmed_date"]),
                            price=s["price"], kind=s["kind"], calc_version=swings.CALC_VERSION,
                            input_hash=a["input_hash"]))
    db.add(m.FibonacciResult(listing_id=listing_id, interval=INTERVAL, as_of_date=d,
                             atr_multiple=a["atr_multiple"], result_json=a["fibonacci"],
                             calc_version=fibonacci.CALC_VERSION, params_hash=a["params_hash"],
                             input_hash=a["input_hash"]))
    for hz, sc in a["scores"].items():
        db.add(m.TechnicalScore(listing_id=listing_id, as_of_date=d, horizon=hz, total=sc["total"],
                                classification=sc["classification"],
                                components=sc.get("components", {}), weights=sc["weights"],
                                inputs=sc["inputs"], score_version=sc["score_version"],
                                params_hash=a["params_hash"], input_hash=a["input_hash"]))
    db.flush()
    return a


def persist_latest_all(db: Session, namespace: str = "synthetic") -> None:
    for lid in db.scalars(select(m.Listing.id).where(m.Listing.namespace == namespace)).all():
        persist_latest(db, lid)
