"""In-app alerts (PHASE_6_TASK.md): evaluation on closed bars, dedup, cooldown, storage."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from research.db import models as m
from research.engine import alerts as A
from research.engine import indicators, setups, swings

from . import analysis as an
from .screener import _held_listing_ids

CONFIG_KEY = "alert_config"
LAST_EVAL_KEY = "alert_last_evaluation"
MAX_BACKFILL_BARS = 10
CLOSE_BUFFER = timedelta(hours=2)  # end-of-day data is published a while after the close


def _utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


# ---------------------------------------------------------------- config

def get_config(db: Session) -> dict:
    row = db.get(m.AppSetting, CONFIG_KEY)
    try:
        return A.validate_config(row.value_json if row and isinstance(row.value_json, dict) else {})
    except ValueError:
        return A.validate_config({})  # a stored config that no longer validates falls back to defaults


def save_config(db: Session, cfg: dict) -> dict:
    valid = A.validate_config(cfg)
    row = db.get(m.AppSetting, CONFIG_KEY)
    if row is None:
        db.add(m.AppSetting(key=CONFIG_KEY, value_json=valid))
    else:
        row.value_json = valid
    db.commit()
    return valid


# ---------------------------------------------------------------- closed bars

def is_closed(bar_date: date, exchange: m.Exchange, now: datetime | None = None) -> bool:
    """A daily bar is closed once its exchange's session has ended (plus a publishing buffer)."""
    tz = ZoneInfo(exchange.timezone)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    if bar_date < local.date():
        return True
    if bar_date > local.date():
        return False
    hh, mm = (int(x) for x in exchange.close_time.split(":"))
    return local >= datetime.combine(bar_date, time(hh, mm), tzinfo=tz) + CLOSE_BUFFER


# ---------------------------------------------------------------- scope

def scope_listing_ids(db: Session, cfg: dict, holdings_source: str) -> list[int]:
    if cfg["scope"] == "all":
        return list(db.scalars(select(m.Listing.id).order_by(m.Listing.id)).all())
    ids = _held_listing_ids(db, holdings_source) | set(db.scalars(select(m.WatchlistItem.listing_id)).all())
    return sorted(ids)


# ---------------------------------------------------------------- evaluation

class _Series:
    """Indicators and swings for one listing's closed history; snapshots per bar, cached."""

    def __init__(self, df, k: float, is_index: bool, lookback: int):
        self.df, self.is_index, self.lookback = df, is_index, lookback
        self.arr = {col: df[col].to_numpy() for col in ("open", "high", "low", "close", "volume")}
        a = self.arr
        self.ind = indicators.compute_all(a["open"], a["high"], a["low"], a["close"], a["volume"])
        self.sw = swings.detect_swings(a["high"], a["low"], self.ind["atr14"], k)
        self._cache: dict[int, dict] = {}

    def _raw(self, t: int) -> dict:
        if t not in self._cache:
            self._cache[t] = an._snapshot(t, self.df, self.ind, self.sw, self.is_index)
        return self._cache[t]

    def snap(self, t: int) -> dict:
        s = self._raw(t)
        ago = self._raw(t - self.lookback)["scores"] if t - self.lookback >= 0 else {}
        a = self.arr
        trig = setups.detect_all(a["open"], a["high"], a["low"], a["close"], a["volume"], self.ind, s["fib"], t,
                                 has_volume=not self.is_index)["triggered"]
        return {"close": s["inputs"]["close"], "ind": {k: an._f(v[t]) for k, v in self.ind.items()},
                "fib": s["fib"], "scores": {h: v["total"] for h, v in s["scores"].items()},
                "scores_ago": {h: v["total"] for h, v in ago.items()} if ago else {},
                "triggered": trig}


def events_at(df, t: int, k: float, is_index: bool, cfg: dict) -> list[dict]:
    """Alert events for bar t of a (closed-bar) history. Used by evaluation and by tests."""
    s = _Series(df, k, is_index, cfg["rules"]["score_change"]["lookback"])
    return A.detect(s.snap(t - 1), s.snap(t), cfg, has_volume=not is_index)


def evaluate(db: Session, holdings_source: str, sensitivity: str, now: datetime | None = None) -> dict:
    cfg = get_config(db)
    k = swings.resolve_k(sensitivity)
    chash = A.config_hash(cfg, sensitivity)
    cooldown = cfg["cooldown_bars"]
    ids = scope_listing_ids(db, cfg, holdings_source)
    summary = {"at": _utc(now or datetime.now(timezone.utc)), "scope": cfg["scope"], "listings": len(ids),
               "evaluated_listings": 0, "bars_evaluated": 0, "created": 0, "duplicates": 0,
               "suppressed_cooldown": 0, "skipped_unclosed_bars": 0, "skipped_backfill_bars": 0,
               "insufficient_history": [], "config_hash": chash, "version": A.ALERTS_VERSION}
    for lid in ids:
        bars = an.load_bars(db, lid)
        lst, df = bars.listing, bars.df
        if not df.empty:
            closed = df["date"].map(lambda d: is_closed(d, lst.exchange, now))
            summary["skipped_unclosed_bars"] += int((~closed).sum())
            df = df[closed].reset_index(drop=True)
        if len(df) < 3:
            summary["insufficient_history"].append(lst.ticker)
            continue
        dates = list(df["date"])
        last = len(df) - 1
        state = db.get(m.AlertState, lid)
        if state is None or state.config_hash != chash:
            todo = [last]
        else:
            todo = [i for i, d in enumerate(dates) if d > state.last_bar_date]
            if len(todo) > MAX_BACKFILL_BARS:
                summary["skipped_backfill_bars"] += len(todo) - MAX_BACKFILL_BARS
                todo = todo[-MAX_BACKFILL_BARS:]
        is_index = lst.instrument.asset_class == "index"
        series = _Series(df, k, is_index, cfg["rules"]["score_change"]["lookback"])
        prov = an.provenance(lst, df)
        index_of = {d: i for i, d in enumerate(dates)}
        for t in todo:
            if t < 1:
                continue
            summary["bars_evaluated"] += 1
            events = A.detect(series.snap(t - 1), series.snap(t), cfg, has_volume=not is_index)
            if not events:
                continue
            ihash = an.input_hash(df.iloc[: t + 1])
            for e in events:
                exists = db.scalar(select(m.Alert.id).where(m.Alert.listing_id == lid, m.Alert.key == e["key"],
                                                            m.Alert.bar_date == dates[t]))
                if exists:
                    summary["duplicates"] += 1
                    continue
                prev_date = db.scalar(select(func.max(m.Alert.bar_date)).where(
                    m.Alert.listing_id == lid, m.Alert.key == e["key"], m.Alert.bar_date < dates[t]))
                if prev_date is not None and prev_date in index_of and t - index_of[prev_date] <= cooldown:
                    summary["suppressed_cooldown"] += 1
                    continue
                db.add(m.Alert(listing_id=lid, type=e["type"], key=e["key"], direction=e["direction"],
                               bar_date=dates[t], title=e["title"], details=e["details"], config_hash=chash,
                               input_hash=ihash, source=prov["source"] or "none",
                               is_synthetic=bool(prov["is_synthetic"])))
                db.flush()
                summary["created"] += 1
        if state is None:
            db.add(m.AlertState(listing_id=lid, last_bar_date=dates[last], config_hash=chash))
        else:
            state.last_bar_date, state.config_hash = dates[last], chash
            state.evaluated_at = datetime.now(timezone.utc)
        summary["evaluated_listings"] += 1
    summary["rotation"] = evaluate_rotation(db, cfg, now)
    summary["created"] += summary["rotation"].get("created", 0)
    summary["duplicates"] += summary["rotation"].get("duplicates", 0)
    summary["suppressed_cooldown"] += summary["rotation"].get("suppressed_cooldown", 0)
    row = db.get(m.AppSetting, LAST_EVAL_KEY)
    if row is None:
        db.add(m.AppSetting(key=LAST_EVAL_KEY, value_json=summary))
    else:
        row.value_json = summary
    db.commit()
    return summary


def last_evaluation(db: Session) -> dict | None:
    row = db.get(m.AppSetting, LAST_EVAL_KEY)
    return row.value_json if row else None


# ---------------------------------------------------------------- reading

def unread_count(db: Session) -> int:
    return int(db.scalar(select(func.count(m.Alert.id)).where(m.Alert.read_at.is_(None))) or 0)


def _provenance(rows: list[m.Alert], ev: dict | None) -> dict:
    sources = sorted({r.source for r in rows})
    return {"source": ",".join(sources) or None,
            "is_synthetic": any(r.is_synthetic for r in rows) if rows else None,
            "as_of": ev["at"] if ev else None, "exchange_timezone": "multiple", "is_delayed": False,
            "delay_minutes": None, "stale": False, "mixed_sources": len(sources) > 1,
            "data_type": "end_of_day"}


def alert_dict(a: m.Alert, lst: m.Listing) -> dict:
    return {"id": a.id, "listing": an.listing_dict(lst), "namespace": lst.namespace, "type": a.type,
            "type_label": A.LABELS.get(a.type, a.type), "key": a.key, "direction": a.direction,
            "bar_date": a.bar_date.isoformat(), "created_at": _utc(a.created_at), "title": a.title,
            "details": a.details, "read": a.read_at is not None, "read_at": _utc(a.read_at),
            "source": a.source, "is_synthetic": a.is_synthetic, "config_hash": a.config_hash,
            "input_hash": a.input_hash}


def list_alerts(db: Session, status: str = "all", limit: int = 500) -> dict:
    q = select(m.Alert).order_by(m.Alert.bar_date.desc(), m.Alert.id.desc()).limit(limit)
    if status == "unread":
        q = q.where(m.Alert.read_at.is_(None))
    rows = db.scalars(q).all()
    ev = last_evaluation(db)
    return {"alerts": [alert_dict(a, db.get(m.Listing, a.listing_id)) for a in rows],
            "unread": unread_count(db), "last_evaluation": ev,
            "labels": A.LABELS, "provenance": _provenance(rows, ev)}


def mark_read(db: Session, alert_id: int) -> None:
    a = db.get(m.Alert, alert_id)
    if a is None:
        raise an.NotFound(f"alert {alert_id} not found")
    if a.read_at is None:
        a.read_at = datetime.now(timezone.utc)
        db.commit()


def mark_all_read(db: Session) -> int:
    n = db.execute(update(m.Alert).where(m.Alert.read_at.is_(None)).values(read_at=datetime.now(timezone.utc))).rowcount
    db.commit()
    return int(n or 0)


# ---------------------------------------------------------------- sector rotation signals

ROTATION_STATE_KEY = "alert_rotation_state"
ROTATION_DIRECTION = {"early_opportunity": "bullish", "established": "bullish", "exit_warning": "bearish",
                      "deterioration": "bearish", "neutral": "neutral"}


def _rotation_key(e: dict) -> str:
    if e["kind"] == "quadrant":
        return f"rotation:{e['from']}->{e['to']}"
    if e["kind"] == "momentum_cross":
        return f"rotation:momentum:{e['category']}"
    return "rotation:sma50_down"


def evaluate_rotation(db: Session, cfg: dict, now: datetime | None = None) -> dict:
    """Sector Rotation signals (quadrant transitions, RS-Momentum crossings, SMA 50 breaks) as alerts.

    Uses the same engine and data choice as the Sector Rotation page (data=auto). Closed bars only;
    the first check (or a settings change) creates alerts for the latest closed session only; later
    checks add events dated after the last evaluated session. Dedup and cooldown as for other alerts.
    """
    from research.data.sectors import REGIONS

    rc = cfg["rules"]["sector_rotation"]
    out = {"enabled": rc["enabled"], "created": 0, "duplicates": 0, "suppressed_cooldown": 0, "sectors": 0}
    if not rc["enabled"]:
        return out
    out["regions"] = {}
    for rid in rc["regions"]:
        region = REGIONS[rid]
        bench = rc["benchmark"] if rc["benchmark"] in region.benchmarks else region.default_benchmark
        res = _evaluate_rotation_region(db, cfg, rc, region, bench, now)
        out["regions"][rid] = res
        for k in ("created", "duplicates", "suppressed_cooldown", "sectors"):
            out[k] += res.get(k, 0)
    if "us" in out["regions"]:  # kept for the last-check summary line
        out.update(data=out["regions"]["us"].get("data"), benchmark=out["regions"]["us"].get("benchmark"),
                   timeframe=rc["timeframe"])
    elif out["regions"]:
        first = next(iter(out["regions"].values()))
        out.update(data=first.get("data"), benchmark=first.get("benchmark"), timeframe=rc["timeframe"])
    return out


def _evaluate_rotation_region(db: Session, cfg: dict, rc: dict, region, benchmark: str, now: datetime | None) -> dict:
    from research.engine import rotation as R
    from research.engine import rrg
    from . import sectors

    out = {"created": 0, "duplicates": 0, "suppressed_cooldown": 0, "sectors": 0}
    need = max(rrg.bars_needed(rc["timeframe"]), 200 + sectors.TRAIL_MAX)
    ns, _ = sectors.choose_namespace(db, region, "auto", need)
    u = sectors._analyse_universe(db, region, ns, benchmark, rc["timeframe"])
    out.update(data=ns, benchmark=benchmark, timeframe=rc["timeframe"], status=u["status"])
    if u["status"] != "ok":
        return out
    dates = u["dates"]
    bl = u["benchmark_listing"]
    last_i = len(dates) - 1
    while last_i >= 0 and not is_closed(dates[last_i], bl.exchange, now):
        last_i -= 1
    if last_i < 1:
        return out
    last_closed = dates[last_i]
    chash = A.config_hash({"sector_rotation": rc, "data": ns, "region": region.id, "benchmark": benchmark}, "rotation")
    row = db.get(m.AppSetting, ROTATION_STATE_KEY)
    state = row.value_json if row and isinstance(row.value_json, dict) else {}
    index_of = {d: i for i, d in enumerate(dates)}
    cooldown = cfg["cooldown_bars"]
    for r in u["rows"]:
        if r.get("status") != "ok":
            continue
        out["sectors"] += 1
        st = state.get(r["ticker"])
        if st and st.get("config_hash") == chash:
            since = date.fromisoformat(st["last_date"])
            todo = [e for e in r["events"] if since < date.fromisoformat(e["date"]) <= last_closed]
        else:
            todo = [e for e in r["events"] if date.fromisoformat(e["date"]) == last_closed]
        lst = db.get(m.Listing, r["listing_id"])
        prov = an.provenance(lst, an.load_bars(db, lst.id).df)
        for e in todo:
            if e["category"] not in rc["categories"]:
                continue
            key, d = _rotation_key(e), date.fromisoformat(e["date"])
            if db.scalar(select(m.Alert.id).where(m.Alert.listing_id == lst.id, m.Alert.key == key, m.Alert.bar_date == d)):
                out["duplicates"] += 1
                continue
            prev = db.scalar(select(func.max(m.Alert.bar_date)).where(m.Alert.listing_id == lst.id, m.Alert.key == key,
                                                                      m.Alert.bar_date < d))
            if prev is not None and prev in index_of and index_of[d] - index_of[prev] <= cooldown:
                out["suppressed_cooldown"] += 1
                continue
            db.add(m.Alert(listing_id=lst.id, type="sector_rotation", key=key, direction=ROTATION_DIRECTION[e["category"]],
                           bar_date=d, title=f"{r['sector']} ({r['ticker']}) vs {benchmark}: {e['label']}",
                           details={"category": e["category"], "category_label": R.CATEGORY_LABELS[e["category"]],
                                    "signal": e["label"], "rs_ratio": e["ratio"], "rs_momentum": e["momentum"],
                                    "benchmark": benchmark, "timeframe": rc["timeframe"], "sector": r["sector"],
                                    "region": region.id,
                                    "sector_ticker": r["ticker"], "method": rrg.METHOD_NOTE,
                                    **({"from": e["from"], "to": e["to"]} if e["kind"] == "quadrant" else {})},
                           config_hash=chash, input_hash=an.input_hash(an.load_bars(db, lst.id, d).df),
                           source=prov["source"] or "none", is_synthetic=bool(prov["is_synthetic"])))
            db.flush()
            out["created"] += 1
        state[r["ticker"]] = {"last_date": last_closed.isoformat(), "config_hash": chash}
    if row is None:
        db.add(m.AppSetting(key=ROTATION_STATE_KEY, value_json=state))
    else:
        row.value_json = dict(state)
    db.commit()
    return out
