"""Backtest runs (PHASE_7_TASK.md §4): load stored daily bars, run the engine, store the result."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from research.core.hashing import stable_hash
from research.db import models as m
from research.engine import backtest as B
from research.engine import rotation_backtest as RB
from research.engine import swings

from . import analysis as an


def _utc(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def strategies() -> dict:
    return {"strategies": [{"id": s.id, "name": s.name, "description": s.description, "params": s.params,
                            "grid_size": len(s.grid())} for s in B.STRATEGIES.values()],
            "defaults": {"commission_bps": B.Costs().commission_bps, "slippage_bps": B.Costs().slippage_bps,
                         "holdout_pct": 0.2, "folds": 3, "mode": "single"},
            "warmup_bars": B.WARMUP, "version": B.BACKTEST_VERSION, "disclaimer": B.DISCLAIMER}


def _notes(lst: m.Listing, prov: dict, result: dict) -> list[str]:
    notes = []
    if prov.get("is_synthetic"):
        notes.append("SYNTHETIC data: these prices are generated, so the results say nothing about real markets.")
    elif prov.get("price_adjustment") == "split_dividend":
        notes.append("Prices are adjusted for splits and dividends: right for returns, but past price levels differ from what was quoted then.")
    notes.append("Only instruments stored in this app can be tested (survivorship bias): instruments that were delisted are missing.")
    if result["main"]["few_trades"] or result["holdout"]["few_trades"]:
        notes.append("Fewer than 10 trades in a period: too few to tell skill from luck.")
    if lst.instrument.asset_class == "index":
        notes.append("Indices can't be bought directly; an index fund or ETF would add its own costs and tracking error.")
    return notes


def run(db: Session, listing_id: int, strategy: str, mode: str, params: dict | None, commission_bps: float,
        slippage_bps: float, holdout_pct: float, folds: int, sensitivity: str) -> dict:
    bars = an.load_bars(db, listing_id)
    lst, df = bars.listing, bars.df
    if df.empty:
        raise an.BadRequest(f"{lst.ticker} has no price history yet.")
    if not (0 <= commission_bps <= 200 and 0 <= slippage_bps <= 200):
        raise an.BadRequest("commission and slippage must each be between 0 and 200 basis points")
    is_index = lst.instrument.asset_class == "index"
    ctx = B.Context(list(df["date"]), df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(),
                    df["close"].to_numpy(), df["volume"].to_numpy(), atr_multiple=swings.resolve_k(sensitivity),
                    has_volume=not is_index)
    try:
        result = B.run(ctx, strategy, mode, params, B.Costs(commission_bps, slippage_bps), holdout_pct, folds)
    except ValueError as e:
        raise an.BadRequest(str(e)) from e
    request = {"listing_id": listing_id, "strategy": strategy, "mode": mode, "params": params,
               "commission_bps": commission_bps, "slippage_bps": slippage_bps, "holdout_pct": holdout_pct,
               "folds": folds if mode == "walk_forward" else None, "sensitivity": sensitivity}
    prov = an.provenance(lst, df)
    row = m.BacktestRun(listing_id=listing_id, strategy=strategy, mode=mode, request=request, result=result,
                        version=B.BACKTEST_VERSION, params_hash=stable_hash(request), input_hash=an.input_hash(df))
    row.result = {**result, "notes": _notes(lst, prov, result), "provenance": prov}
    db.add(row)
    db.commit()
    return run_dict(db, row)


# ---------------------------------------------------------------- rotation backtest (ROTATION_BACKTEST_TASK.md)

def rotation_strategies() -> dict:
    from research.data.sectors import REGIONS
    return {"strategies": [{"id": s.id, "name": s.name, "description": s.description, "params": s.params,
                            "grid_size": len(s.grid())} for s in RB.STRATEGIES.values()],
            "regions": [{"id": r.id, "name": r.name, "benchmarks": list(r.benchmarks), "default_benchmark": r.default_benchmark,
                         "sectors": len(r.etfs)} for r in REGIONS.values()],
            "defaults": {"commission_bps": B.Costs().commission_bps, "slippage_bps": B.Costs().slippage_bps,
                         "holdout_pct": 0.2, "folds": 2, "mode": "single", "region": "us", "data": "auto"},
            "version": RB.ROTATION_BACKTEST_VERSION, "disclaimer": B.DISCLAIMER}


def _rotation_notes(h: dict, result: dict) -> list[str]:
    notes = []
    if h["provenance"].get("is_synthetic"):
        notes.append("SYNTHETIC data: these prices are generated, so the results say nothing about real markets.")
    elif h["provenance"].get("price_adjustment") == "split_dividend":
        notes.append("Prices are adjusted for splits and dividends, so returns include dividends.")
    notes.append(f"One region ({h['region'].name}) and only the sector ETFs this app tracks today (survivorship bias): "
                 "sector funds that closed or changed are missing.")
    if h["excluded"]:
        notes.append("Left out for too little history: " + ", ".join(f"{x['ticker']} ({x['bars_available']} bars)" for x in h["excluded"]) + ".")
    notes.append("Uses this app's RRG-inspired approximation (not the proprietary JdK RS-Ratio/RS-Momentum) and the "
                 "default Rotation Signal Score weights.")
    if result["main"]["few_trades"] or result["holdout"]["few_trades"]:
        notes.append("Fewer than 10 trades in a period: too few to tell skill from luck.")
    notes.append("Equal-weight sectors is held throughout with no rebalancing; it shows what being in sectors at all "
                 "would have done, without picking.")
    return notes


def run_rotation(db: Session, region: str, benchmark: str | None, data: str, strategy: str, mode: str,
                 params: dict | None, commission_bps: float, slippage_bps: float, holdout_pct: float, folds: int) -> dict:
    from . import sectors as S
    if strategy not in RB.STRATEGIES:
        raise an.BadRequest(f"unknown rotation strategy '{strategy}'")
    if not (0 <= commission_bps <= 200 and 0 <= slippage_bps <= 200):
        raise an.BadRequest("commission and slippage must each be between 0 and 200 basis points")
    strat = RB.STRATEGIES[strategy]
    tfs = [validate_tf(strat, params)] if mode == "single" else sorted({g["timeframe"] for g in strat.grid()})
    need = RB.warmup_for(tfs) + 100
    h = S.aligned_history(db, region, benchmark, data, need)
    bl = h["benchmark_listing"]
    if len(h["sectors"]) < 3:
        raise an.BadRequest(f"Only {len(h['sectors'])} sector ETFs have {need}+ days of {h['namespace']} price history; "
                            "a rotation backtest needs at least 3.")
    u = RB.Universe(h["dates"], h["bench_open"], h["bench_close"], h["sectors"], bl.ticker)
    try:
        result = RB.run(u, strategy, mode, params, B.Costs(commission_bps, slippage_bps), holdout_pct, folds)
    except ValueError as e:
        raise an.BadRequest(str(e)) from e
    request = {"kind": "rotation", "region": region, "benchmark": bl.ticker, "data": data, "namespace": h["namespace"],
               "strategy": strategy, "mode": mode, "params": params, "commission_bps": commission_bps,
               "slippage_bps": slippage_bps, "holdout_pct": holdout_pct, "folds": folds if mode == "walk_forward" else None}
    result.update(region={"id": h["region"].id, "name": h["region"].name}, namespace=h["namespace"],
                  excluded_sectors=h["excluded"], aligned_bars=len(h["dates"]),
                  notes=_rotation_notes(h, result), provenance=h["provenance"])
    row = m.BacktestRun(listing_id=bl.id, strategy=result["strategy"], mode=mode, request=request, result=result,
                        version=RB.ROTATION_BACKTEST_VERSION, params_hash=stable_hash(request), input_hash=h["input_hash"])
    db.add(row)
    db.commit()
    return run_dict(db, row)


def validate_tf(strat, params: dict | None) -> str:
    try:
        return RB.validate_params(strat, params)["timeframe"]
    except ValueError as e:
        raise an.BadRequest(str(e)) from e


def run_dict(db: Session, row: m.BacktestRun) -> dict:
    lst = db.get(m.Listing, row.listing_id)
    return {"id": row.id, "created_at": _utc(row.created_at), "listing": an.listing_dict(lst), "request": row.request,
            "result": row.result, "version": row.version, "params_hash": row.params_hash, "input_hash": row.input_hash,
            "provenance": row.result.get("provenance")}


def get(db: Session, run_id: int) -> dict:
    row = db.get(m.BacktestRun, run_id)
    if row is None:
        raise an.NotFound(f"backtest {run_id} not found")
    return run_dict(db, row)


def delete(db: Session, run_id: int) -> None:
    row = db.get(m.BacktestRun, run_id)
    if row is None:
        raise an.NotFound(f"backtest {run_id} not found")
    db.delete(row)
    db.commit()


def list_runs(db: Session, limit: int = 100) -> dict:
    rows = db.scalars(select(m.BacktestRun).order_by(m.BacktestRun.id.desc()).limit(limit)).all()
    out = []
    for r in rows:
        lst = db.get(m.Listing, r.listing_id)
        res = r.result
        rot = res.get("kind") == "rotation"
        out.append({"id": r.id, "created_at": _utc(r.created_at), "kind": res.get("kind", "single"),
                    "ticker": f"{lst.ticker} sectors" if rot else lst.ticker, "listing_id": lst.id,
                    "namespace": lst.namespace, "strategy": r.strategy, "strategy_name": res.get("strategy_name"),
                    "mode": r.mode, "final_params": res.get("final_params"),
                    "combinations_tested": res.get("combinations_tested"),
                    "main_return_pct": res["main"]["metrics"]["total_return_pct"],
                    "main_buy_hold_pct": res["main"]["buy_hold"]["total_return_pct"],
                    "holdout_return_pct": res["holdout"]["metrics"]["total_return_pct"],
                    "holdout_buy_hold_pct": res["holdout"]["buy_hold"]["total_return_pct"],
                    "main_equal_weight_pct": res["main"]["equal_weight"]["total_return_pct"] if rot else None,
                    "holdout_equal_weight_pct": res["holdout"]["equal_weight"]["total_return_pct"] if rot else None,
                    "is_synthetic": bool(res.get("provenance", {}).get("is_synthetic"))})
    syn = [x["is_synthetic"] for x in out]
    return {"runs": out, "disclaimer": B.DISCLAIMER,
            "provenance": {"source": "stored backtests", "is_synthetic": any(syn) if syn else None, "as_of": None,
                           "exchange_timezone": None, "is_delayed": None, "delay_minutes": None, "stale": False}}
