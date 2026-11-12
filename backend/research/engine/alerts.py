"""Alert conditions (PHASE_6_TASK.md §1). Pure functions, no I/O.

Every alert is a *transition* between two consecutive closed bars, ``prev`` (t-1) and
``now`` (t), so a condition that simply persists does not alert again. A snapshot is::

    {"close": float, "ind": {name: float | None}, "fib": <fibonacci.analyse result>,
     "scores": {horizon: total | None}, "scores_ago": {horizon: total | None},
     "triggered": [setup ids]}

An alert is a condition to research, never a trade signal.
"""
from __future__ import annotations

import copy
import math

from research.core.hashing import stable_hash

from . import setups

ALERTS_VERSION = "alerts-v1"
SMA_CHOICES = (10, 20, 50, 100, 200)
HORIZONS = ("short", "medium", "long")

DEFAULT_CONFIG: dict = {
    "scope": "holdings_and_watchlist",  # or "all"
    "cooldown_bars": 5,
    "rules": {
        "fib_cross": {"enabled": True},
        "fib_approach": {"enabled": True, "atr": 0.5},
        "sma_cross": {"enabled": True, "periods": [50, 200]},
        "golden_death_cross": {"enabled": True},
        "rsi": {"enabled": True, "overbought": 70.0, "oversold": 30.0},
        "macd_cross": {"enabled": True},
        "relvol_spike": {"enabled": True, "min": 2.0},
        "score_change": {"enabled": True, "points": 10.0, "lookback": 5},
        "setup_new": {"enabled": True},
        # Sector Rotation module signals for all sector ETFs (independent of the holdings/watchlist scope)
        "sector_rotation": {"enabled": True, "timeframe": "3m", "benchmark": "SPY", "regions": ["us", "eu"],
                            "categories": ["early_opportunity", "established", "exit_warning", "deterioration"]},
    },
}
ROTATION_CATEGORIES = ("early_opportunity", "established", "exit_warning", "deterioration", "neutral")

LABELS = {
    "fib_cross": "Fibonacci level crossed",
    "fib_approach": "Approaching a Fibonacci level",
    "sma_cross": "Moving-average cross",
    "golden_death_cross": "Golden / death cross",
    "rsi": "RSI overbought / oversold",
    "macd_cross": "MACD crossover",
    "relvol_spike": "Relative-volume spike",
    "score_change": "Material score change",
    "setup_new": "New setup triggered",
    "sector_rotation": "Sector rotation",
}

# (key, type, lo, hi) numeric bounds for validation
_BOUNDS = {
    ("fib_approach", "atr"): (0.05, 5.0),
    ("rsi", "overbought"): (50.0, 99.0),
    ("rsi", "oversold"): (1.0, 50.0),
    ("relvol_spike", "min"): (1.1, 20.0),
    ("score_change", "points"): (1.0, 100.0),
    ("score_change", "lookback"): (1, 60),
}


def validate_config(cfg: dict) -> dict:
    """Merge ``cfg`` over the defaults and validate. Raises ValueError with a clear message."""
    out = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(cfg, dict):
        raise ValueError("config must be an object")
    unknown = set(cfg) - set(out)
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    if "scope" in cfg:
        if cfg["scope"] not in ("holdings_and_watchlist", "all"):
            raise ValueError("scope must be 'holdings_and_watchlist' or 'all'")
        out["scope"] = cfg["scope"]
    if "cooldown_bars" in cfg:
        cd = cfg["cooldown_bars"]
        if not isinstance(cd, int) or isinstance(cd, bool) or not 0 <= cd <= 250:
            raise ValueError("cooldown_bars must be a whole number from 0 to 250")
        out["cooldown_bars"] = cd
    for rid, rc in (cfg.get("rules") or {}).items():
        if rid not in out["rules"]:
            raise ValueError(f"unknown alert rule '{rid}'")
        if not isinstance(rc, dict):
            raise ValueError(f"rules.{rid} must be an object")
        for k, v in rc.items():
            if k not in out["rules"][rid]:
                raise ValueError(f"unknown setting rules.{rid}.{k}")
            if k == "enabled":
                if not isinstance(v, bool):
                    raise ValueError(f"rules.{rid}.enabled must be true or false")
            elif k == "periods":
                if not isinstance(v, list) or any(p not in SMA_CHOICES for p in v):
                    raise ValueError(f"rules.sma_cross.periods must be a list of {list(SMA_CHOICES)}")
                v = sorted(set(v))
            elif rid == "sector_rotation":
                v = _validate_rotation(k, v)
            else:
                lo, hi = _BOUNDS[(rid, k)]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                    raise ValueError(f"rules.{rid}.{k} must be between {lo} and {hi}")
                if k == "lookback" and not isinstance(v, int):
                    raise ValueError("rules.score_change.lookback must be a whole number")
            out["rules"][rid][k] = v
    r = out["rules"]["rsi"]
    if r["oversold"] >= r["overbought"]:
        raise ValueError("RSI oversold must be below overbought")
    return out


def _validate_rotation(k: str, v):
    from research.data.sectors import US
    from .rrg import TIMEFRAMES
    if k == "timeframe":
        if v not in TIMEFRAMES:
            raise ValueError(f"rules.sector_rotation.timeframe must be one of {list(TIMEFRAMES)}")
    elif k == "benchmark":
        if v not in US.benchmarks:
            raise ValueError(f"rules.sector_rotation.benchmark must be one of {list(US.benchmarks)}")
    elif k == "regions":
        from research.data.sectors import REGIONS
        if not isinstance(v, list) or any(r not in REGIONS for r in v):
            raise ValueError(f"rules.sector_rotation.regions must be a list of {list(REGIONS)}")
        v = [r for r in REGIONS if r in v]
    elif k == "categories":
        if not isinstance(v, list) or any(c not in ROTATION_CATEGORIES for c in v):
            raise ValueError(f"rules.sector_rotation.categories must be a list of {list(ROTATION_CATEGORIES)}")
        v = [c for c in ROTATION_CATEGORIES if c in v]
    return v


def config_hash(cfg: dict, sensitivity: str) -> str:
    return stable_hash({"version": ALERTS_VERSION, "setups": setups.SETUPS_VERSION,
                        "sensitivity": sensitivity, "config": cfg})


# ---------------------------------------------------------------- helpers

def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


def _event(type_: str, key: str, direction: str, title: str, **details) -> dict:
    return {"type": type_, "key": key, "direction": direction, "title": title, "details": details}


def _cross(a0, b0, a1, b1) -> str | None:
    """'up' if a went from <= b to > b, 'down' if from >= b to < b, else None."""
    if None in (a0, b0, a1, b1):
        return None
    if a0 <= b0 and a1 > b1:
        return "up"
    if a0 >= b0 and a1 < b1:
        return "down"
    return None


def _ratio(r: float) -> str:
    return f"{r * 100:.1f}".rstrip("0").rstrip(".") + "%"


# ---------------------------------------------------------------- rules

def _fib_cross(prev, now, _rc) -> list[dict]:
    fib = prev["fib"]
    if not fib or fib.get("status") != "ok":
        return []
    out = []
    c0, c1 = prev["close"], now["close"]
    for lv in fib["levels"]:
        d = _cross(c0, lv["price"], c1, lv["price"])
        if d:
            out.append(_event("fib_cross", f"fib_cross:{lv['ratio']}:{d}", "bullish" if d == "up" else "bearish",
                              f"Closed {'above' if d == 'up' else 'below'} the {_ratio(lv['ratio'])} Fibonacci {lv['kind']}",
                              level_ratio=lv["ratio"], level_kind=lv["kind"], level_price=lv["price"],
                              prev_close=c0, close=c1, swing_direction=fib["direction"]))
    return out


def _fib_approach(prev, now, rc) -> list[dict]:
    f1, f0 = now["fib"], prev["fib"]
    if not f1 or f1.get("status") != "ok" or f1["nearest"]["distance_atr"] is None:
        return []
    n1, lim = f1["nearest"], rc["atr"]
    if n1["distance_atr"] > lim:
        return []
    if f0 and f0.get("status") == "ok" and f0["nearest"]["distance_atr"] is not None:
        n0 = f0["nearest"]
        if n0["distance_atr"] <= lim and n0["ratio"] == n1["ratio"] and abs(n0["price"] - n1["price"]) < 1e-9:
            return []  # already this close to the same level yesterday
    side = "above" if n1["price_above_level"] else "below"
    return [_event("fib_approach", f"fib_approach:{n1['ratio']}", "neutral",
                   f"Within {lim:g} ATR {side} the {_ratio(n1['ratio'])} Fibonacci {n1['kind']}",
                   level_ratio=n1["ratio"], level_price=n1["price"], distance_atr=n1["distance_atr"],
                   threshold_atr=lim, close=now["close"], price_above_level=n1["price_above_level"])]


def _sma_cross(prev, now, rc) -> list[dict]:
    out = []
    for p in rc["periods"]:
        k = f"sma{p}"
        d = _cross(prev["close"], prev["ind"].get(k), now["close"], now["ind"].get(k))
        if d:
            out.append(_event("sma_cross", f"sma_cross:{k}:{d}", "bullish" if d == "up" else "bearish",
                              f"Closed {'above' if d == 'up' else 'below'} SMA {p}",
                              period=p, prev_close=prev["close"], prev_sma=prev["ind"][k],
                              close=now["close"], sma=now["ind"][k]))
    return out


def _golden(prev, now, _rc) -> list[dict]:
    a0, b0, a1, b1 = (prev["ind"].get("sma50"), prev["ind"].get("sma200"), now["ind"].get("sma50"), now["ind"].get("sma200"))
    d = _cross(a0, b0, a1, b1)
    if not d:
        return []
    name = "Golden cross" if d == "up" else "Death cross"
    return [_event("golden_death_cross", "golden_cross" if d == "up" else "death_cross",
                   "bullish" if d == "up" else "bearish", f"{name}: SMA 50 crossed {'above' if d == 'up' else 'below'} SMA 200",
                   prev_sma50=a0, prev_sma200=b0, sma50=a1, sma200=b1)]


def _rsi(prev, now, rc) -> list[dict]:
    r0, r1 = prev["ind"].get("rsi14"), now["ind"].get("rsi14")
    if r0 is None or r1 is None:
        return []
    ob, os_ = rc["overbought"], rc["oversold"]
    if r0 < ob <= r1:
        return [_event("rsi", "rsi:overbought", "bearish", f"RSI 14 entered overbought (≥ {ob:g})",
                       prev_rsi=r0, rsi=r1, threshold=ob)]
    if r0 > os_ >= r1:
        return [_event("rsi", "rsi:oversold", "bullish", f"RSI 14 entered oversold (≤ {os_:g})",
                       prev_rsi=r0, rsi=r1, threshold=os_)]
    return []


def _macd(prev, now, _rc) -> list[dict]:
    p, n = prev["ind"], now["ind"]
    d = _cross(p.get("macd_line"), p.get("macd_signal"), n.get("macd_line"), n.get("macd_signal"))
    if not d:
        return []
    return [_event("macd_cross", f"macd_cross:{d}", "bullish" if d == "up" else "bearish",
                   f"MACD line crossed {'above' if d == 'up' else 'below'} its signal line",
                   prev_macd_line=p["macd_line"], prev_macd_signal=p["macd_signal"],
                   macd_line=n["macd_line"], macd_signal=n["macd_signal"])]


def _relvol(prev, now, rc) -> list[dict]:
    v0, v1, lim = prev["ind"].get("relvol20"), now["ind"].get("relvol20"), rc["min"]
    if v0 is None or v1 is None or not (v0 < lim <= v1):
        return []
    up = now["close"] >= prev["close"]
    return [_event("relvol_spike", "relvol_spike", "bullish" if up else "bearish",
                   f"Volume {v1:.1f}× its 20-day average on an {'up' if up else 'down'} day",
                   prev_relvol=v0, relvol=v1, threshold=lim, prev_close=prev["close"], close=now["close"])]


def _score(prev, now, rc) -> list[dict]:
    out, lim, lb = [], rc["points"], rc["lookback"]
    for h in HORIZONS:
        s1, a1 = now["scores"].get(h), now["scores_ago"].get(h)
        if s1 is None or a1 is None:
            continue
        ch1 = s1 - a1
        if abs(ch1) < lim:
            continue
        s0, a0 = prev["scores"].get(h), prev["scores_ago"].get(h)
        if s0 is not None and a0 is not None and abs(s0 - a0) >= lim and (s0 - a0) * ch1 > 0:
            continue  # already a material change in the same direction yesterday
        d = "up" if ch1 > 0 else "down"
        out.append(_event("score_change", f"score_change:{h}:{d}", "bullish" if d == "up" else "bearish",
                          f"{h.capitalize()}-term score {'rose' if d == 'up' else 'fell'} {abs(ch1):.1f} points in {lb} bars",
                          horizon=h, score=s1, score_before=a1, change=ch1, threshold=lim, lookback_bars=lb))
    return out


def _setup_new(prev, now, _rc) -> list[dict]:
    out = []
    for sid in now["triggered"]:
        if sid in prev["triggered"]:
            continue
        name, direction, _ = setups.SETUPS[sid]
        out.append(_event("setup_new", f"setup_new:{sid}", direction, f"New setup: {name}",
                          setup_id=sid, setup_name=name, setups_version=setups.SETUPS_VERSION))
    return out


RULES = {
    "fib_cross": _fib_cross,
    "fib_approach": _fib_approach,
    "sma_cross": _sma_cross,
    "golden_death_cross": _golden,
    "rsi": _rsi,
    "macd_cross": _macd,
    "relvol_spike": _relvol,
    "score_change": _score,
    "setup_new": _setup_new,
}


def detect(prev: dict, now: dict, cfg: dict, has_volume: bool = True) -> list[dict]:
    """All alert events for the transition prev (t-1) -> now (t)."""
    events = []
    for rid, fn in RULES.items():
        rc = cfg["rules"][rid]
        if not rc["enabled"] or (rid == "relvol_spike" and not has_volume):
            continue
        events.extend(fn(prev, now, rc))
    # A level that was crossed doesn't also need an "approaching" alert on the same bar.
    crossed = {e["details"]["level_ratio"] for e in events if e["type"] == "fib_cross"}
    return [e for e in events if not (e["type"] == "fib_approach" and e["details"]["level_ratio"] in crossed)]
