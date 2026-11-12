"""Sector Rotation module (SECTOR_ROTATION_TASK.md): dashboard, sector detail, holdings, score weights.

Data comes from the existing price store. Real (Tiingo) and synthetic demo data are never mixed in one
view: `data="auto"` picks real data when the benchmark and most sector ETFs have enough real history.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from research.core.hashing import stable_hash
from research.core.calendars import holidays_for
from research.data.sectors import BENCHMARK_NAMES, REGIONS, region_of
from research.db import models as m
from research.engine import indicators, rotation, rrg
from research.market_data import holdings as H
from research.market_data.tiingo import MarketDataError

from . import analysis as an
from .screener import _held_listing_ids

WEIGHTS_KEY = "rotation_score_weights"
TRAIL_MAX = max(rrg.TRAILS)
DETAIL_TRAIL = 60
REL_CHART_BARS = 252
MIN_REAL_SECTORS = 6
DATA_CHOICES = ("auto", "real", "synthetic")
NOTES = [
    rrg.METHOD_NOTE,
    "ETF prices and volumes are proxies for where capital is moving; they don't measure institutional fund flows. "
    "ETF fund-flow data isn't included because no reliable free source is available.",
    "A rotation signal is a condition to research, not a buy or sell signal. Check the absolute trend and the broader market too.",
]


# ---------------------------------------------------------------- settings

def get_weights(db: Session) -> dict:
    row = db.get(m.AppSetting, WEIGHTS_KEY)
    try:
        return rotation.validate_weights(row.value_json if row and isinstance(row.value_json, dict) else None)
    except ValueError:
        return dict(rotation.DEFAULT_WEIGHTS)


def save_weights(db: Session, w: dict) -> dict:
    valid = rotation.validate_weights(w)
    row = db.get(m.AppSetting, WEIGHTS_KEY)
    if row is None:
        db.add(m.AppSetting(key=WEIGHTS_KEY, value_json=valid))
    else:
        row.value_json = valid
    db.commit()
    return valid


# ---------------------------------------------------------------- data loading

def _listing(db: Session, namespace: str, ticker: str, mic: str | None = None) -> m.Listing | None:
    q = select(m.Listing).where(m.Listing.namespace == namespace, m.Listing.ticker == ticker)
    if mic:
        q = q.where(m.Listing.exchange_mic == mic)
    return db.scalar(q.order_by(m.Listing.id).limit(1))


REGION_NOTES = {
    "us": "US sectors: the 11 GICS sectors via SPDR Select Sector ETFs. Real prices from Tiingo (TIINGO_API_KEY).",
    "eu": "European sectors: the 19 STOXX Europe 600 ICB supersectors via iShares (DE) ETFs on Xetra, in EUR — "
          "a different sector system from GICS. Benchmark: iShares STOXX Europe 600 (EXSA). Real prices from EODHD "
          "(EODHD_API_KEY). Distributing ETFs: dividend-adjusted prices are used.",
}


def _bars(db: Session, lst: m.Listing | None) -> pd.DataFrame:
    return an.load_bars(db, lst.id).df if lst is not None else pd.DataFrame()


def _availability(db: Session, region, namespace: str, need: int) -> dict:
    b = _listing(db, namespace, region.default_benchmark, region.benchmark_mics[region.default_benchmark])
    bench_n = len(_bars(db, b))
    ok = sum(len(_bars(db, _listing(db, namespace, e.ticker, e.mic))) >= need for e in region.etfs)
    return {"benchmark_bars": bench_n, "sectors_with_history": ok, "usable": bench_n >= need and ok >= MIN_REAL_SECTORS}


def choose_namespace(db: Session, region, data: str, need: int) -> tuple[str, dict]:
    if data not in DATA_CHOICES:
        raise an.BadRequest(f"data must be one of {DATA_CHOICES}")
    real = _availability(db, region, "real", need)
    if data == "real":
        return "real", real
    if data == "synthetic":
        return "synthetic", real
    return ("real" if real["usable"] else "synthetic"), real


def _validate(region_id: str, benchmark: str, timeframe: str):
    if region_id not in REGIONS:
        raise an.BadRequest(f"unknown region '{region_id}'")
    region = REGIONS[region_id]
    if benchmark not in region.benchmarks:
        raise an.BadRequest(f"benchmark must be one of {region.benchmarks}")
    if timeframe not in rrg.TIMEFRAMES:
        raise an.BadRequest(f"timeframe must be one of {list(rrg.TIMEFRAMES)}")
    return region


# ---------------------------------------------------------------- core computation

def _analyse_universe(db: Session, region, namespace: str, benchmark: str, timeframe: str) -> dict:
    need = max(rrg.bars_needed(timeframe), 200 + TRAIL_MAX)
    bl = _listing(db, namespace, benchmark, region.benchmark_mics.get(benchmark))
    bdf = _bars(db, bl)
    if bl is None or bdf.empty:
        return {"status": "no_benchmark", "need": need, "rows": [], "benchmark_listing": bl, "dates": []}
    frames, rows, provs = {}, {}, []
    for e in region.etfs:
        lst = _listing(db, namespace, e.ticker, e.mic)
        df = _bars(db, lst)
        base = {"ticker": e.ticker, "sector": e.sector, "etf_name": e.name, "listing_id": lst.id if lst else None,
                "bars_available": len(df)}
        if lst is None or df.empty:
            rows[e.ticker] = {**base, "status": "no_price_history"}
            continue
        prov = an.provenance(lst, df)
        provs.append(prov)
        gaps = an.find_gaps(list(df["date"]), holidays_for(lst.exchange_mic, lst.namespace))
        rows[e.ticker] = {**base, "provenance": prov, "data_gaps": gaps}
        if len(df) < need:
            rows[e.ticker]["status"] = "insufficient_history"
            continue
        frames[e.ticker] = df.set_index("date")
    bframe = bdf.set_index("date")
    common = bframe.index
    for f in frames.values():
        common = common.intersection(f.index)
    common = common.sort_values()
    dropped = {t: int(len(f.index.difference(common))) for t, f in frames.items()}
    if len(common) < need:
        for t in frames:
            rows[t]["status"] = "insufficient_history"
        return {"status": "insufficient_history", "need": need, "rows": list(rows.values()), "benchmark_listing": bl,
                "dates": [], "provs": provs, "aligned_bars": len(common)}
    dates = list(common)
    bclose = bframe.loc[common, "close"].to_numpy(dtype=float)
    t = len(dates) - 1
    for tk, f in frames.items():
        a = f.loc[common]
        o, h, lo, c = (a[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        v = a["volume"].to_numpy(dtype=float)
        ind = indicators.compute_all(o, h, lo, c, v)
        series = rrg.compute(c, bclose, timeframe)
        met = rotation.metrics(c, v, ind, bclose, t)
        events = rotation.transitions(series, dates, c, ind["sma50"], t)
        r_t, m_t = rrg._f(series.ratio[t]), rrg._f(series.momentum[t])
        if r_t is None or m_t is None:  # e.g. the sector moves exactly with the benchmark: undefined, not 100
            rows[tk].update({"status": "rrg_unavailable", "metrics": met,
                             "reason": "RS-Ratio/RS-Momentum undefined (relative strength didn't vary in the window)"})
            continue
        rows[tk].update({
            "status": "ok", "_series": series, "_close": c, "_bclose": bclose,
            "ratio": rrg._f(series.ratio[t]), "momentum": rrg._f(series.momentum[t]),
            "quadrant": rrg.quadrant(series.ratio[t], series.momentum[t]),
            "trail": rrg.trail(series, dates, t, TRAIL_MAX), "metrics": met, "events": events,
            "dates_dropped_by_alignment": dropped[tk],
        })
    return {"status": "ok", "need": need, "rows": list(rows.values()), "benchmark_listing": bl, "dates": dates,
            "bclose": bclose, "provs": provs, "aligned_bars": len(dates)}


def _merge_prov(provs: list[dict], tz: str = "America/New_York") -> dict:
    if not provs:
        return {"source": None, "is_synthetic": None, "as_of": None, "exchange_timezone": None,
                "is_delayed": None, "delay_minutes": None, "stale": True}
    return {"source": ",".join(sorted({p["source"] or "none" for p in provs})),
            "is_synthetic": any(p["is_synthetic"] for p in provs),
            "as_of": max((p["as_of"] for p in provs if p["as_of"]), default=None),
            "oldest_as_of": min((p["as_of"] for p in provs if p["as_of"]), default=None),
            "exchange_timezone": tz, "is_delayed": False, "delay_minutes": None,
            "stale": any(p["stale"] for p in provs), "data_type": "end_of_day",
            "price_adjustment": provs[0].get("price_adjustment")}


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _last_refresh(db: Session, namespace: str, region) -> dict | None:
    if namespace == "synthetic":
        return None
    row = db.get(m.AppSetting, "eodhd_last_refresh" if region.price_provider == "eodhd" else "market_data_last_refresh")
    return row.value_json if row else None


def dashboard(db: Session, region_id: str = "us", benchmark: str | None = None, timeframe: str = rrg.DEFAULT_TIMEFRAME,
              data: str = "auto") -> dict:
    region = REGIONS.get(region_id) or REGIONS["us"]
    benchmark = benchmark or region.default_benchmark
    region = _validate(region_id, benchmark, timeframe)
    need = max(rrg.bars_needed(timeframe), 200 + TRAIL_MAX)
    ns, real_avail = choose_namespace(db, region, data, need)
    u = _analyse_universe(db, region, ns, benchmark, timeframe)
    weights = get_weights(db)
    ok = [r for r in u["rows"] if r.get("status") == "ok"]
    for r in ok:
        r["score"] = rotation.score(r["_series"], r["metrics"], r["events"], len(u["dates"]) - 1, weights)
    ranked = sorted(ok, key=lambda r: -(r["score"]["total"] or -1))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    counts = {q: sum(r["quadrant"] == q for r in ok) for q in rrg.QUADRANTS}
    events = sorted(({**e, "ticker": r["ticker"], "sector": r["sector"]} for r in ok for e in r["events"]),
                    key=lambda e: (e["sessions_ago"], e["ticker"]))
    improving = [r for r in ok if r["quadrant"] == "improving"]
    bl = u["benchmark_listing"]
    bench = None
    if bl is not None:
        ba = an.analyse_listing(db, bl.id, include_series=False)
        if ba["status"] == "ok":
            bdf = an.load_bars(db, bl.id).df
            bc = bdf["close"].to_numpy(dtype=float)
            bind = indicators.compute_all(*(bdf[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume")))
            bm = rotation.metrics(bc, bdf["volume"].to_numpy(dtype=float), bind, bc, len(bc) - 1)
            bench = {"ticker": bl.ticker, "name": BENCHMARK_NAMES.get(bl.ticker, bl.instrument.name), "listing_id": bl.id,
                     "close": bm["close"], "change_20d_pct": bm["change_20d_pct"], "change_50d_pct": bm["change_50d_pct"],
                     "absolute_trend": bm["absolute_trend"], "above_sma50": bm["above_sma50"], "above_sma200": bm["above_sma200"],
                     "classification": {h: s["classification"] for h, s in ba["scores"].items()},
                     "provenance": ba["provenance"]}
    held = _held_listing_ids(db, _holdings_source(db))
    for r in u["rows"]:
        r["held"] = r.get("listing_id") in held
    out_rows = [_public(r) for r in sorted(u["rows"], key=lambda r: (r.get("rank") or 99, r["ticker"]))]
    pick = lambda rs, key, rev: (_public(sorted(rs, key=key, reverse=rev)[0]) if rs else None)  # noqa: E731
    return {
        "status": u["status"],
        "region": {"id": region.id, "name": region.name, "classification": region.classification,
                   "currency": region.currency, "price_provider": region.price_provider},
        "regions": [{"id": r.id, "name": r.name} for r in REGIONS.values()],
        "data": ns, "data_requested": data, "real_data_availability": real_avail,
        "benchmark": benchmark, "benchmarks": list(region.benchmarks), "benchmark_info": bench,
        "timeframe": timeframe, "timeframes": {k: v[0] for k, v in rrg.TIMEFRAMES.items()},
        "trails": list(rrg.TRAILS), "bars_needed": u["need"], "aligned_bars": u.get("aligned_bars", 0),
        "as_of": u["dates"][-1].isoformat() if u["dates"] else None,
        "rows": out_rows, "quadrant_counts": counts,
        "highlights": {
            "most_attractive": pick(ok, lambda r: r["score"]["total"] or 0, True),
            "strongest_improving": pick(improving, lambda r: r["momentum"], True),
            "weakest": pick(ok, lambda r: r["score"]["total"] or 0, False),
            "strongest_rs": pick(ok, lambda r: r["ratio"], True), "weakest_rs": pick(ok, lambda r: r["ratio"], False),
        },
        "events": events, "event_categories": rotation.CATEGORY_LABELS,
        "score": {"weights": weights, "labels": rotation.WEIGHT_LABELS, "defaults": rotation.DEFAULT_WEIGHTS},
        "last_refresh": _last_refresh(db, ns, region), "method": {"version": rrg.RRG_VERSION, "rotation_version": rotation.ROTATION_VERSION,
                                                        "windows": dict(zip(("label", "window", "momentum_lag", "smoothing"), rrg.TIMEFRAMES[timeframe]))},
        "notes": [REGION_NOTES[region.id], *NOTES], "provenance": _merge_prov(u.get("provs", []), region.timezone),
    }


def _holdings_source(db: Session) -> str:
    row = db.get(m.AppSetting, "holdings_source")
    return row.value_json if row else "synthetic"


# ---------------------------------------------------------------- holdings

def holdings_for(db: Session, etf: str) -> list[m.SectorHolding]:
    return list(db.scalars(select(m.SectorHolding).where(m.SectorHolding.etf_ticker == etf).order_by(m.SectorHolding.rank)).all())


def store_holdings(db: Session, f: H.HoldingsFile, source: str = H.SOURCE) -> int:
    db.execute(delete(m.SectorHolding).where(m.SectorHolding.etf_ticker == f.etf_ticker))
    now = datetime.now(timezone.utc)
    for h in f.holdings:
        db.add(m.SectorHolding(etf_ticker=f.etf_ticker, as_of=f.as_of, rank=h.rank, name=h.name[:200], ticker=h.ticker,
                               identifier=h.identifier, weight_pct=h.weight_pct, exchange=h.exchange,
                               source=source, fetched_at=now))
    db.commit()
    return len(f.holdings)


def refresh_holdings(db: Session, tickers: list[str] | None = None, fetch=H.fetch_ssga, region_id: str | None = None,
                     fetch_ishares=H.fetch_ishares) -> dict:
    regions = [REGIONS[region_id]] if region_id else list(REGIONS.values())
    wanted = [(r, e) for r in regions for e in r.etfs if not tickers or e.ticker in tickers]
    results = []
    for region, e in wanted:
        t = e.ticker
        try:
            if region.holdings_source == "ishares":
                f, src = fetch_ishares(t, e.holdings_path), H.ISHARES_SOURCE
            else:
                f, src = fetch(t), H.SOURCE
            n = store_holdings(db, f, src)
            results.append({"ticker": t, "status": "updated", "holdings": n, "as_of": f.as_of.isoformat()})
        except MarketDataError as e:
            db.rollback()
            results.append({"ticker": t, "status": "failed", "error_code": e.code, "message": e.message})
    return {"results": results, "source": "issuer holdings files (State Street for US SPDR, iShares for Europe)"}


def holdings_status(db: Session, region_id: str = "us") -> list[dict]:
    out = []
    for e in (REGIONS.get(region_id) or REGIONS["us"]).etfs:
        hs = holdings_for(db, e.ticker)
        out.append({"ticker": e.ticker, "count": len(hs), "as_of": hs[0].as_of.isoformat() if hs else None,
                    "fetched_at": hs[0].fetched_at.isoformat() if hs else None})
    return out


# ---------------------------------------------------------------- sector detail

def _constituent(db: Session, lst: m.Listing, sector_df: pd.DataFrame, timeframe: str, held: set, watched: set) -> dict:
    df = an.load_bars(db, lst.id).df
    base = {"listing_id": lst.id, "ticker": lst.ticker, "name": lst.instrument.name, "namespace": lst.namespace,
            "held": lst.id in held, "watchlisted": lst.id in watched, "bars_available": len(df)}
    if df.empty:
        return {**base, "status": "no_price_history"}
    j = df.set_index("date")[["close"]].join(sector_df.set_index("date")[["close"]], how="inner", rsuffix="_sector")
    c, s = j["close"].to_numpy(dtype=float), j["close_sector"].to_numpy(dtype=float)
    t = len(c) - 1
    ret20 = (c[t] / c[t - 20] - 1) * 100 if t >= 20 else None
    sec20 = (s[t] / s[t - 20] - 1) * 100 if t >= 20 else None
    out = {**base, "status": "ok", "close": float(c[t]), "change_20d_pct": ret20,
           "relative_to_sector_20d_pct": (ret20 - sec20) if ret20 is not None and sec20 is not None else None,
           "as_of": j.index[-1].isoformat(), "provenance": an.provenance(lst, df)}
    if len(c) >= rrg.bars_needed(timeframe, 1):
        ser = rrg.compute(c, s, timeframe)
        r, mo = rrg._f(ser.ratio[t]), rrg._f(ser.momentum[t])
        out.update(rs_ratio_vs_sector=r, rs_momentum_vs_sector=mo, quadrant_vs_sector=rrg.quadrant(r, mo),
                   beats_sector=r is not None and r > 100)
    else:
        out.update(rs_ratio_vs_sector=None, rs_momentum_vs_sector=None, quadrant_vs_sector=None, beats_sector=None,
                   rrg_note="not enough history for an RS-Ratio against the sector")
    return out


def sector_detail(db: Session, ticker: str, region_id: str = "us", benchmark: str | None = None,
                  timeframe: str = rrg.DEFAULT_TIMEFRAME, data: str = "auto") -> dict:
    region = region_of(ticker.upper())
    etf = next((e for e in region.etfs if e.ticker == ticker.upper()), None) if region else None
    if etf is None:
        raise an.NotFound(f"{ticker} is not a sector ETF in this module")
    if benchmark not in region.benchmarks:
        benchmark = None  # e.g. a US benchmark carried over from the US view: use this region's default
    d = dashboard(db, region.id, benchmark, timeframe, data)
    ns = d["data"]
    row = next(r for r in d["rows"] if r["ticker"] == etf.ticker)
    lst = _listing(db, ns, etf.ticker, etf.mic)
    out = {"ticker": etf.ticker, "sector": etf.sector, "etf_name": etf.name, "data": ns, "benchmark": d["benchmark"],
           "timeframe": d["timeframe"], "timeframes": d["timeframes"], "benchmarks": d["benchmarks"], "row": row,
           "listing_id": lst.id if lst else None, "notes": d["notes"], "provenance": d["provenance"],
           "event_categories": d["event_categories"], "score_labels": d["score"]["labels"], "region": d["region"]}
    if row.get("status") == "ok":
        u = _analyse_universe(db, region, ns, d["benchmark"], d["timeframe"])  # same alignment as the dashboard
        r = next(x for x in u["rows"] if x["ticker"] == etf.ticker)
        dates, t = u["dates"], len(u["dates"]) - 1
        out["trail"] = rrg.trail(r["_series"], dates, t, DETAIL_TRAIL)
        k = max(0, t - REL_CHART_BARS + 1)
        c, b = r["_close"][k:], r["_bclose"][k:]
        out["relative_chart"] = {"dates": [x.isoformat() for x in dates[k:]], "sector": list(c / c[0] * 100),
                                 "benchmark": list(b / b[0] * 100), "relative": list((c / b) / (c[0] / b[0]) * 100)}
    # constituents: issuer holdings (real reference data) vs instruments of this sector in the current data set
    held, watched = _held_listing_ids(db, _holdings_source(db)), set(db.scalars(select(m.WatchlistItem.listing_id)).all())
    hs = holdings_for(db, etf.ticker)
    sector_df = an.load_bars(db, lst.id).df if lst else pd.DataFrame()
    top = []
    for h in hs[:10]:
        item = {"rank": h.rank, "name": h.name, "ticker": h.ticker, "weight_pct": h.weight_pct, "exchange": h.exchange,
                "price_supported": _constituent_mic(region, h) is not None}
        if ns == "real" and h.ticker and not sector_df.empty and item["price_supported"]:
            cl = _real_constituent_listing(db, region, h)
            item["analysis"] = _constituent(db, cl, sector_df, d["timeframe"], held, watched) if cl else None
        top.append(item)
    out["holdings"] = {"source": "iShares holdings file (ishares.com)" if region.holdings_source == "ishares"
                       else "State Street (SSGA) daily holdings file", "as_of": hs[0].as_of.isoformat() if hs else None,
                       "fetched_at": hs[0].fetched_at.isoformat() if hs else None, "count": len(hs), "top10": top,
                       "top10_weight_pct": sum(h.weight_pct for h in hs[:10]) if hs else None,
                       "missing_prices": [x["ticker"] for x in top if ns == "real" and x["ticker"] and x["price_supported"]
                                          and not x.get("analysis")],
                       "unsupported_exchanges": sorted({x["exchange"] for x in top if x["ticker"] and not x["price_supported"] and x["exchange"]})}
    in_set = []
    if not sector_df.empty:
        q = select(m.Listing).join(m.Instrument).where(m.Listing.namespace == ns, m.Instrument.sector == etf.sector,
                                                       m.Instrument.asset_class == "stock",
                                                       m.Listing.exchange_mic.in_(_region_mics(region)))
        in_set = [_constituent(db, cl, sector_df, d["timeframe"], held, watched) for cl in db.scalars(q).all()]
    analysed = [x["analysis"] for x in top if x.get("analysis") and x["analysis"]["status"] == "ok"] if ns == "real" else []
    pool = {x["listing_id"]: x for x in analysed + [x for x in in_set if x["status"] == "ok"]}.values()
    ranked = sorted((x for x in pool if x.get("change_20d_pct") is not None), key=lambda x: -x["change_20d_pct"])
    out["constituents_in_app"] = in_set
    out["strongest"] = ranked[:3]
    out["weakest"] = ranked[::-1][:3]
    out["beating_sector"] = [x for x in pool if x.get("beats_sector")]
    return out


def _region_mics(region) -> set[str]:
    from research.core.calendars import EU_MICS, US_MICS
    return set(US_MICS) if region.id == "us" else set(EU_MICS)


def _constituent_mic(region, h: m.SectorHolding) -> str | None:
    """Exchange we can price this holding on, or None (US holdings: Tiingo, any US venue)."""
    if region.id == "us":
        return "US"
    from research.market_data.eu_service import HOLDINGS_EXCHANGES
    return HOLDINGS_EXCHANGES.get(h.exchange or "")


def _real_constituent_listing(db: Session, region, h: m.SectorHolding) -> m.Listing | None:
    if region.id == "us":
        from research.market_data.service import find_real_listing
        return find_real_listing(db, h.ticker)
    from research.market_data import eu_service
    mic = _constituent_mic(region, h)
    return eu_service.find_listing(db, h.ticker, mic) if mic else None


def download_constituents(db: Session, ticker: str, add=None) -> dict:
    """Download real prices for the ETF's top 10 holdings (Tiingo for US, EODHD for Europe), one at a time,
    within the providers' budgets. Holdings on exchanges we can't price yet are reported, not skipped silently."""
    from research.market_data import eu_service
    from research.market_data import service as md
    region = region_of(ticker.upper())
    if region is None:
        raise an.NotFound(f"{ticker} is not a sector ETF in this module")
    if add is None:
        add = md.add_symbol if region.id == "us" else (lambda db_, t, mic: eu_service.add_symbol(db_, t, mic))
    hs = [h for h in holdings_for(db, ticker.upper())[:10] if h.ticker]
    if not hs:
        raise an.BadRequest(f"No holdings stored for {ticker}. Update holdings first.")
    results = []
    for h in hs:
        mic = _constituent_mic(region, h)
        if mic is None:
            results.append({"ticker": h.ticker, "status": "unsupported_exchange",
                            "message": f"{h.exchange}: prices for this exchange aren't supported yet"})
            continue
        if _real_constituent_listing(db, region, h) is not None:
            results.append({"ticker": h.ticker, "status": "already_tracked"})
            continue
        try:
            r = add(db, h.ticker) if region.id == "us" else add(db, h.ticker, mic)
            results.append({"ticker": h.ticker, "status": r.get("status", "updated")})
        except MarketDataError as e:
            db.rollback()
            results.append({"ticker": h.ticker, "status": "failed", "error_code": e.code, "message": e.message})
            if e.code in ("auth", "not_configured", "budget"):
                break
    return {"results": results}


# ---------------------------------------------------------------- aligned history for the rotation backtest

def aligned_history(db: Session, region_id: str, benchmark: str | None, data: str, need: int) -> dict:
    """Benchmark + sector ETF daily bars on common dates (ROTATION_BACKTEST_TASK.md §2). ETFs with fewer than
    `need` bars are left out (and listed) rather than shortening everyone's history."""
    region = REGIONS.get(region_id)
    if region is None:
        raise an.BadRequest(f"unknown region '{region_id}'")
    benchmark = benchmark or region.default_benchmark
    if benchmark not in region.benchmarks:
        raise an.BadRequest(f"benchmark must be one of {region.benchmarks}")
    ns, _ = choose_namespace(db, region, data, need)
    bl = _listing(db, ns, benchmark, region.benchmark_mics.get(benchmark))
    bdf = _bars(db, bl)
    if bl is None or bdf.empty:
        raise an.BadRequest(f"{benchmark} has no {ns} price history yet.")
    frames, excluded, provs, dfs = {}, [], [an.provenance(bl, bdf)], [bdf]
    for e in region.etfs:
        lst = _listing(db, ns, e.ticker, e.mic)
        df = _bars(db, lst)
        if lst is None or len(df) < need:
            excluded.append({"ticker": e.ticker, "sector": e.sector, "bars_available": len(df)})
            continue
        provs.append(an.provenance(lst, df))
        dfs.append(df)
        frames[e.ticker] = (e.sector, df.set_index("date"))
    bframe = bdf.set_index("date")
    common = bframe.index
    for _, f in frames.values():
        common = common.intersection(f.index)
    common = common.sort_values()
    sectors = {}
    for tk, (sector, f) in frames.items():
        a = f.loc[common]
        sectors[tk] = {"sector": sector, **{k: a[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume")}}
    b = bframe.loc[common]
    return {"region": region, "namespace": ns, "benchmark_listing": bl, "dates": list(common),
            "bench_open": b["open"].to_numpy(dtype=float), "bench_close": b["close"].to_numpy(dtype=float),
            "sectors": sectors, "excluded": excluded, "provenance": _merge_prov(provs, region.timezone),
            "input_hash": stable_hash([an.input_hash(d) for d in dfs])}
