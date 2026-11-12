"""Technical score v1 (PHASE_1_TASK.md §7). Deterministic and fully explainable.

Every component returns its inputs, the individual rule outcomes and its points,
so the UI can render exactly how the score was produced.
"""
from __future__ import annotations

import math

SCORE_VERSION = "v1"
WEIGHTS = {"trend": 0.40, "momentum": 0.30, "fibonacci": 0.15, "volume": 0.15}
BULLISH_MIN, BEARISH_MAX = 60.0, 40.0
HORIZONS = ("short", "medium", "long")

TREND_RULES = {
    "short": [("close", "sma10"), ("close", "sma20"), ("sma10", "sma20")],
    "medium": [("close", "sma50"), ("sma20", "sma50"), ("sma50", "sma100")],
    "long": [("close", "sma200"), ("sma50", "sma200"), ("sma100", "sma200")],
}


def _missing(*vals) -> bool:
    return any(v is None or (isinstance(v, float) and math.isnan(v)) for v in vals)


def _trend(h: str, x: dict) -> dict | None:
    rules = []
    for a, b in TREND_RULES[h]:
        if _missing(x.get(a), x.get(b)):
            return None
        bull = x[a] > x[b]
        rules.append({"rule": f"{a} > {b}", "left": x[a], "right": x[b],
                      "result": bull, "points": 100.0 if bull else 0.0})
    return {"points": sum(r["points"] for r in rules) / len(rules), "rules": rules}


def _rsi_points(r: float) -> tuple[float, str]:
    if r < 30:
        return 0.0, "RSI < 30 (oversold: no bullish credit)"
    if r <= 50:
        return 50.0, "30 <= RSI <= 50"
    if r <= 70:
        return 100.0, "50 < RSI <= 70"
    return 50.0, "RSI > 70 (stretched)"


def _momentum(h: str, x: dict) -> dict | None:
    rules = []
    if h == "short":
        if _missing(x.get("rsi14"), x.get("macd_hist")):
            return None
        p, why = _rsi_points(x["rsi14"])
        rules.append({"rule": why, "left": x["rsi14"], "right": None, "result": None, "points": p})
        bull = x["macd_hist"] > 0
        rules.append({"rule": "macd_hist > 0", "left": x["macd_hist"], "right": 0.0,
                      "result": bull, "points": 100.0 if bull else 0.0})
    elif h == "medium":
        if _missing(x.get("macd_line"), x.get("macd_signal")):
            return None
        for name, a, b in (("macd_line > macd_signal", x["macd_line"], x["macd_signal"]),
                           ("macd_line > 0", x["macd_line"], 0.0)):
            rules.append({"rule": name, "left": a, "right": b, "result": a > b,
                          "points": 100.0 if a > b else 0.0})
    else:
        if _missing(x.get("roc60"), x.get("rsi14")):
            return None
        for name, a, b in (("roc60 > 0", x["roc60"], 0.0), ("rsi14 > 50", x["rsi14"], 50.0)):
            rules.append({"rule": name, "left": a, "right": b, "result": a > b,
                          "points": 100.0 if a > b else 0.0})
    return {"points": sum(r["points"] for r in rules) / len(rules), "rules": rules}


def _fibonacci(fib: dict | None) -> dict:
    if not fib or fib.get("status") != "ok" or fib["nearest"]["distance_atr"] is None:
        status = (fib or {}).get("status", "unavailable")
        return {"points": 50.0, "status": status,
                "rules": [{"rule": f"no Fibonacci context ({status}) -> neutral", "points": 50.0}]}
    n = fib["nearest"]
    near = n["distance_atr"] <= 1.0
    if near and fib["direction"] == "up" and n["price_above_level"]:
        p, why = 70.0, "within 1 ATR above nearest level in up swing (support nearby)"
    elif near and fib["direction"] == "down" and not n["price_above_level"]:
        p, why = 30.0, "within 1 ATR below nearest level in down swing (resistance overhead)"
    else:
        p, why = 50.0, "no nearby support/resistance condition"
    return {"points": p, "status": "ok",
            "rules": [{"rule": why, "direction": fib["direction"], "nearest_ratio": n["ratio"],
                       "distance_atr": n["distance_atr"], "price_above_level": n["price_above_level"],
                       "points": p}]}


def _volume(x: dict) -> dict | None:
    if _missing(x.get("relvol20"), x.get("close"), x.get("prev_close")):
        return None
    rv, up, down = x["relvol20"], x["close"] > x["prev_close"], x["close"] < x["prev_close"]
    if rv >= 1.5 and up:
        p, why = 80.0, "relvol >= 1.5 on up day"
    elif rv >= 1.5 and down:
        p, why = 20.0, "relvol >= 1.5 on down day"
    else:
        p, why = 50.0, "no volume signal"
    return {"points": p, "rules": [{"rule": why, "relvol20": rv, "close": x["close"],
                                     "prev_close": x["prev_close"], "points": p}]}


def classify(total: float) -> str:
    if total >= BULLISH_MIN:
        return "bullish"
    if total <= BEARISH_MAX:
        return "bearish"
    return "neutral"


def score(horizon: str, inputs: dict, fib: dict | None) -> dict:
    comps = {
        "trend": _trend(horizon, inputs),
        "momentum": _momentum(horizon, inputs),
        "fibonacci": _fibonacci(fib),
        "volume": _volume(inputs),
    }
    excluded = [k for k, v in comps.items() if v is None]
    used_w = sum(WEIGHTS[k] for k in comps if k not in excluded)
    base = {"horizon": horizon, "score_version": SCORE_VERSION, "weights": dict(WEIGHTS),
            "excluded_components": excluded, "inputs": inputs}
    if used_w < 0.5 - 1e-12:
        return {**base, "status": "insufficient_data", "total": None, "classification": None,
                "components": {k: v for k, v in comps.items() if v is not None}}
    components = {}
    total = 0.0
    for k, v in comps.items():
        if v is None:
            continue
        eff_w = WEIGHTS[k] / used_w
        contrib = v["points"] * eff_w
        total += contrib
        components[k] = {**v, "weight": WEIGHTS[k], "effective_weight": eff_w, "contribution": contrib}
    total = round(total, 1)
    return {**base, "status": "ok", "total": total, "classification": classify(total),
            "components": components}
