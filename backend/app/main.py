"""Portfolio Tracker API (local only)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core_env import load_env

load_env()  # .env in the app folder (git-ignored): ANTHROPIC_API_KEY for the assistant

from app import demo as DEMO  # noqa: E402

if DEMO.DEMO:  # the demo copy (port 8002): made-up data only, and every request goes through the demo network guard
    from app.demo import network as _demo_network
    _demo_network.install()

from app.db import models as m  # noqa: E402
from app.services import benchmarks as BMS  # noqa: E402
from app.services import autorefresh as AR  # noqa: E402
from app.services import entries as E  # noqa: E402
from app.services import favorites as FAV  # noqa: E402
from app.services import maintenance as MT  # noqa: E402
from app.services import groups as GS  # noqa: E402
from app.services import history as HS  # noqa: E402
from app.services import assistant as AS  # noqa: E402
from app.services import portfolio as P  # noqa: E402
from app.services import whatif as WS  # noqa: E402
from app.services import risk as RS  # noqa: E402
from app.services import journal as JS  # noqa: E402
from app.services import ideas as IS  # noqa: E402
from app.services import breakeven as BE  # noqa: E402
from app.demo import service as DS  # noqa: E402

MAX_UPLOAD = 50 * 1024 * 1024



@asynccontextmanager
async def lifespan(_app):
    missing = DEMO.DEMO and not (DEMO.TRACKER_DB.exists() and DEMO.RESEARCH_DB.exists())
    m.init_db()
    if missing:  # scripts/dev.sh builds the demo before starting; this is only a fallback
        DS.reset()
    if MT.supervised():  # started by scripts/dev.sh: back up both databases once a day (checked every 3 hours)
        MT.start_daily_backups()
        AR.start()  # automatic daily price refresh (checks every 15 minutes)
    yield


app = FastAPI(title="Portfolio Tracker", version="0.1.0", lifespan=lifespan)

# Research (the former Fibonacci AI app): its own API and database, served under /research/api/…
from research.main import app as research_app  # noqa: E402

app.mount("/research", research_app)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
                   allow_methods=["*"], allow_headers=["*"])


def get_db():
    db = m.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.exception_handler(P.BadRequest)
def _bad(_: Request, e: P.BadRequest):
    return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(e)})


@app.exception_handler(P.NotFound)
def _nf(_: Request, e: P.NotFound):
    return JSONResponse(status_code=404, content={"error": "not_found", "message": str(e)})


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status(db: Session = Depends(get_db)):
    return P.status(db)


@app.post("/api/import")
async def do_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise P.BadRequest("The file is larger than 50 MB.")
    return P.do_import(db, file.filename or "workbook.xlsx", data)


class DecisionIn(BaseModel):
    action: str
    date: str | None = None
    price: float | None = None
    rows: list[int] | None = None
    fields: dict | None = None
    shares: float | None = None
    scope: str | None = None


@app.get("/api/review")
def review(kind: str | None = None, which: str = "pending", db: Session = Depends(get_db)):
    if which not in ("pending", "resolved", "all"):
        raise P.BadRequest("which must be pending, resolved or all")
    return P.review(db, kind, which)


@app.put("/api/review/{key}")
def decide(key: str, body: DecisionIn, db: Session = Depends(get_db)):
    return P.decide(db, key, body.model_dump(exclude_none=True))


@app.delete("/api/review/{key}")
def undo(key: str, db: Session = Depends(get_db)):
    return P.undo(db, key)


class BulkIn(BaseModel):
    kind: str
    action: str


@app.post("/api/review/bulk")
def bulk(body: BulkIn, db: Session = Depends(get_db)):
    return P.bulk(db, body.kind, body.action)


@app.get("/api/stocks")
def stocks(db: Session = Depends(get_db)):
    return P.stocks(db)


class MergeIn(BaseModel):
    name_keys: list[str]
    display_name: str | None = None


@app.post("/api/stocks/merge")
def merge(body: MergeIn, db: Session = Depends(get_db)):
    return P.merge(db, body.name_keys, body.display_name)


class SplitIn(BaseModel):
    name_key: str


@app.post("/api/stocks/split")
def split(body: SplitIn, db: Session = Depends(get_db)):
    return P.split(db, body.name_key)


class RenameIn(BaseModel):
    display_name: str | None = None
    ticker: str | None = None


@app.put("/api/stocks/{group_key}")
def rename(group_key: str, body: RenameIn, db: Session = Depends(get_db)):
    return P.rename(db, group_key, body.display_name, body.ticker)


@app.get("/api/sales")
def sales(year: int | None = None, db: Session = Depends(get_db)):
    return P.sales(db, year)


@app.get("/api/positions")
def positions(db: Session = Depends(get_db)):
    return P.positions(db)


@app.get("/api/check")
def check(db: Session = Depends(get_db)):
    return P.check(db)


@app.post("/api/fx/refresh")
def fx_refresh(db: Session = Depends(get_db)):
    return P.ensure_fx(db, force=True)


# ---------------------------------------------------------------- phase 2: analysis

@app.get("/api/analysis")
def analysis(db: Session = Depends(get_db)):
    return P.analysis(db)


@app.get("/api/by-stock")
def by_stock(db: Session = Depends(get_db)):
    return P.by_stock(db)


@app.get("/api/by-stock/detail")
def stock_detail(pool: str, db: Session = Depends(get_db)):
    return P.stock_detail(db, pool)


class CapitalIn(BaseModel):
    date: str
    amount: float
    currency: str = "USD"
    account: str | None = None
    note: str | None = None


@app.get("/api/capital")
def capital(db: Session = Depends(get_db)):
    return P.capital(db)


@app.post("/api/capital")
def add_capital(body: CapitalIn, db: Session = Depends(get_db)):
    return P.add_capital(db, body.model_dump())


@app.delete("/api/capital/{flow_id}")
def delete_capital(flow_id: int, db: Session = Depends(get_db)):
    return P.delete_capital(db, flow_id)


# ---------------------------------------------------------------- phase 3: trades, fees, dividends, prices

class TradeIn(BaseModel):
    kind: str
    date: str
    name: str
    shares: float
    price: float
    currency: str
    pence: bool = False
    broker: str | None = None
    fee: float = 0.0
    note: str | None = None


def _manual_id(trade_id: str) -> int:
    if not (trade_id.startswith("M") and trade_id[1:].isdigit()):
        raise P.BadRequest("only trades entered in the app (M…) can be edited or deleted; correct sheet trades instead")
    return int(trade_id[1:])


@app.get("/api/trades")
def trades(db: Session = Depends(get_db)):
    return E.trades(db)


@app.post("/api/trades")
def add_trade(body: TradeIn, db: Session = Depends(get_db)):
    return E.add_trade(db, body.model_dump())


@app.put("/api/trades/{trade_id}")
def update_trade(trade_id: str, body: TradeIn, db: Session = Depends(get_db)):
    return E.update_trade(db, _manual_id(trade_id), body.model_dump())


@app.delete("/api/trades/{trade_id}")
def delete_trade(trade_id: str, db: Session = Depends(get_db)):
    return E.delete_trade(db, _manual_id(trade_id))


class FeeIn(BaseModel):
    fee: float


@app.put("/api/trades/{trade_id}/fee")
def set_fee(trade_id: str, body: FeeIn, db: Session = Depends(get_db)):
    return E.set_fee(db, trade_id, body.fee)


class CorrectIn(BaseModel):
    fields: dict


@app.put("/api/trades/{trade_id}/correct")
def correct(trade_id: str, body: CorrectIn, db: Session = Depends(get_db)):
    return E.correct(db, trade_id, body.fields)


class DividendIn(BaseModel):
    date: str
    name: str
    amount: float
    currency: str
    tax: float = 0.0
    note: str | None = None


@app.get("/api/dividends")
def dividends(db: Session = Depends(get_db)):
    return E.dividends(db)


@app.post("/api/dividends")
def add_dividend(body: DividendIn, db: Session = Depends(get_db)):
    return E.add_dividend(db, body.model_dump())


@app.delete("/api/dividends/{div_id}")
def delete_dividend(div_id: int, db: Session = Depends(get_db)):
    return E.delete_dividend(db, div_id)


class PriceIn(BaseModel):
    price: float
    date: str | None = None


@app.get("/api/prices")
def prices(db: Session = Depends(get_db)):
    return E.prices(db)


@app.put("/api/prices")
def set_price(pool: str, body: PriceIn, db: Session = Depends(get_db)):
    return E.set_price(db, pool, body.model_dump(exclude_none=True))


@app.delete("/api/prices/{price_id}")
def delete_price(price_id: int, db: Session = Depends(get_db)):
    return E.delete_price(db, price_id)


@app.post("/api/prices/workbook")
async def prices_from_workbook(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise P.BadRequest("The file is larger than 50 MB.")
    return E.prices_from_workbook(db, file.filename or "workbook.xlsx", data)


# ---------------------------------------------------------------- index comparison

@app.get("/api/benchmarks")
def benchmarks(start: str | None = None, end: str | None = None, range: str | None = None, db: Session = Depends(get_db)):  # noqa: A002
    return BMS.view(db, start, end, range)


@app.get("/api/benchmarks/status")
def benchmarks_status(db: Session = Depends(get_db)):
    return {"indexes": BMS.status(db)}


@app.post("/api/benchmarks/refresh")
def benchmarks_refresh(db: Session = Depends(get_db)):
    return BMS.refresh(db)


@app.post("/api/benchmarks/{index_id}/refresh")
def benchmarks_refresh_one(index_id: str, db: Session = Depends(get_db)):
    return BMS.refresh(db, [index_id])


@app.post("/api/benchmarks/{index_id}/upload")
async def benchmarks_upload(index_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise P.BadRequest("The file is larger than 10 MB.")
    return BMS.upload(db, index_id, data)


class SymbolIn(BaseModel):
    symbol: str
    source: str | None = None


@app.put("/api/benchmarks/{index_id}")
def benchmarks_symbol(index_id: str, body: SymbolIn, db: Session = Depends(get_db)):
    return BMS.set_symbol(db, index_id, body.symbol, body.source)


# ---------------------------------------------------------------- what-if, sectors, assistant

@app.get("/api/whatif")
def whatif_overview(db: Session = Depends(get_db)):
    return WS.overview(db)


class SaleItem(BaseModel):
    pool: str
    shares: float | None = None
    percent: float | None = None


class SaleIn(BaseModel):
    items: list[SaleItem] | None = None
    sector: str | None = None
    everything: bool = False
    percent: float | None = None
    fee_per_sale: float = 0.0


@app.post("/api/whatif/sell")
def whatif_sell(body: SaleIn, db: Session = Depends(get_db)):
    return WS.simulate_sale(db, [i.model_dump() for i in body.items] if body.items else None, body.sector, body.everything,
                            body.percent, body.fee_per_sale)


class RebalanceIn(BaseModel):
    by: str
    targets: dict[str, float]
    whole_shares: bool = True


@app.post("/api/whatif/rebalance")
def whatif_rebalance(body: RebalanceIn, db: Session = Depends(get_db)):
    return WS.simulate_rebalance(db, body.by, body.targets, body.whole_shares)


class AverageDownIn(BaseModel):
    pool: str
    buy_price: float | None = None
    shares: float | None = None
    amount_usd: float | None = None
    target_break_even: float | None = None
    fee: float = 0.0


@app.post("/api/whatif/average-down")
def whatif_average_down(body: AverageDownIn, db: Session = Depends(get_db)):
    return WS.simulate_average_down(db, body.pool, body.buy_price, body.shares, body.amount_usd, body.target_break_even, body.fee)


class BuyZone(BaseModel):
    label: str = ""
    price: float


class BuyZonesIn(BaseModel):
    pool: str
    zones: list[BuyZone]
    shares: float | None = None
    amount_usd: float | None = None
    fee: float = 0.0


@app.post("/api/whatif/buy-zones")
def whatif_buy_zones(body: BuyZonesIn, db: Session = Depends(get_db)):
    return WS.simulate_buy_zones(db, body.pool, [z.model_dump() for z in body.zones], body.shares, body.amount_usd, body.fee)


@app.get("/api/explore/portfolio")
def explore_portfolio(db: Session = Depends(get_db)):
    return WS.portfolio_map(db)


@app.get("/api/sectors")
def sectors(db: Session = Depends(get_db)):
    return WS.sectors(db)


class SectorIn(BaseModel):
    sector: str | None


@app.put("/api/sectors/{group_key}")
def set_sector(group_key: str, body: SectorIn, db: Session = Depends(get_db)):
    return WS.set_sector(db, group_key, body.sector)


@app.post("/api/sectors/confirm-all")
def confirm_sectors(db: Session = Depends(get_db)):
    return WS.confirm_all(db)


@app.post("/api/sectors/suggest")
def suggest_sectors(db: Session = Depends(get_db)):
    return WS.suggest_sectors(db)


@app.get("/api/assistant/status")
def assistant_status():
    return AS.status()


class AskIn(BaseModel):
    question: str
    chat_id: int | None = None


@app.post("/api/assistant/ask")
def assistant_ask(body: AskIn, db: Session = Depends(get_db)):
    return AS.ask(db, body.question, body.chat_id)


@app.get("/api/assistant/chats/{chat_id}")
def assistant_chat(chat_id: int, db: Session = Depends(get_db)):
    return AS.get_chat(db, chat_id)


# ---------------------------------------------------------------- price history and performance

@app.get("/api/performance")
def performance(db: Session = Depends(get_db)):
    return HS.performance(db)


@app.get("/api/price-history")
def price_history(db: Session = Depends(get_db)):
    return HS.status(db)


@app.post("/api/price-history/download")
def price_history_download(wait: bool = False, limit: int | None = None, db: Session = Depends(get_db)):
    if wait:  # run in this request (tests, scripts); the app uses the background download
        return {**HS.run_batch(db, limit), "status": HS.status(db)}
    return HS.start_download(db)


@app.post("/api/price-history/stop")
def price_history_stop(db: Session = Depends(get_db)):
    return HS.stop_download(db)


@app.post("/api/price-history/csv")
async def price_history_csv(pool: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise P.BadRequest("The file is larger than 10 MB.")
    return HS.upload_csv(db, pool, data)


@app.delete("/api/price-history/csv")
def price_history_csv_delete(pool: str, db: Session = Depends(get_db)):
    return HS.delete_csv(db, pool)


class TickerIn(BaseModel):
    ticker: str | None


@app.put("/api/price-history/ticker/{group_key}")
def price_history_ticker(group_key: str, body: TickerIn, db: Session = Depends(get_db)):
    return HS.set_ticker(db, group_key, body.ticker)


class RenameTradesIn(BaseModel):
    ids: list[str]
    name: str


@app.post("/api/trades/rename")
def rename_trades(body: RenameTradesIn, db: Session = Depends(get_db)):
    return HS.rename_trades(db, body.ids, body.name)


class OddIgnoreIn(BaseModel):
    items: list[dict]


@app.post("/api/performance/odd-trades/ignore")
def ignore_odd_trades(body: OddIgnoreIn, db: Session = Depends(get_db)):
    return HS.ignore_odd(db, body.items)


# ---------------------------------------------------------------- your sale groups

@app.get("/api/groups")
def groups(db: Session = Depends(get_db)):
    return GS.view(db)


class GroupAssignIn(BaseModel):
    ids: list[str]
    group: str | None


@app.put("/api/groups/assign")
def groups_assign(body: GroupAssignIn, db: Session = Depends(get_db)):
    return GS.assign(db, body.ids, body.group)


# ---------------------------------------------------------------- shortcuts panel

class FavoritesIn(BaseModel):
    items: list[dict]


@app.get("/api/favorites")
def favorites(db: Session = Depends(get_db)):
    return FAV.get(db)


@app.put("/api/favorites")
def save_favorites(body: FavoritesIn, db: Session = Depends(get_db)):
    return FAV.put(db, body.items)


# ---------------------------------------------------------------- updates and backups

def live_only():
    """Updates and backups work on your real copy only: the demo can't see, restore or replace them."""
    if DEMO.DEMO:
        raise P.BadRequest("Updates & backups are switched off in demo mode. Switch to Live to use them.")


@app.get("/api/maintenance")
def maintenance():
    if DEMO.DEMO:
        return {"version": MT.current_version(), "supervised": False, "backups": [], "backups_folder": None, "demo": True}
    return {"version": MT.current_version(), "supervised": MT.supervised(), "backups": MT.list_backups(),
            "backups_folder": str(MT.backups_dir()), "demo": False}


@app.get("/api/maintenance/check", dependencies=[Depends(live_only)])
def maintenance_check():
    return MT.check()


@app.post("/api/maintenance/update", dependencies=[Depends(live_only)])
def maintenance_update():
    return MT.update()


@app.post("/api/backups", dependencies=[Depends(live_only)])
def backup_now():
    return MT.backup("manual")


@app.delete("/api/backups/{backup_id}", dependencies=[Depends(live_only)])
def backup_delete(backup_id: str):
    return {"backups": MT.delete_backup(backup_id)}


@app.post("/api/backups/{backup_id}/restore", dependencies=[Depends(live_only)])
def backup_restore(backup_id: str):
    return MT.restore(backup_id)


@app.get("/api/backups/{backup_id}/download", dependencies=[Depends(live_only)])
def backup_download(backup_id: str):
    return Response(MT.backup_zip(backup_id), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{backup_id}.zip"'})


# ---------------------------------------------------------------- automatic daily price refresh

class AutoRefreshIn(BaseModel):
    enabled: bool


@app.get("/api/auto-refresh")
def auto_refresh(db: Session = Depends(get_db)):
    return AR.status(db)


@app.put("/api/auto-refresh")
def auto_refresh_set(body: AutoRefreshIn, db: Session = Depends(get_db)):
    return AR.set_enabled(db, body.enabled)


@app.post("/api/auto-refresh/run")
def auto_refresh_run(db: Session = Depends(get_db)):
    AR.run_in_background()
    return {**AR.status(db), "running": True}


# ---------------------------------------------------------------- risk dashboard

@app.get("/api/risk")
def risk(window: str = "1y", db: Session = Depends(get_db)):
    return RS.view(db, window)


# ---------------------------------------------------------------- trade journal

class JournalIn(BaseModel):
    reasons: list[str] | None = None
    target: float | None = None
    stop: float | None = None
    horizon_days: int | None = None
    confidence: int | None = None
    sell_reason: str | None = None
    lesson: str | None = None
    notes: str | None = None
    skipped: bool = False


class JournalSkipIn(BaseModel):
    keys: list[str] = []
    older: bool = False


class JournalTagsIn(BaseModel):
    reasons: list[str] | None = None
    sell_reasons: list[str] | None = None


@app.get("/api/journal")
def journal(db: Session = Depends(get_db)):
    return JS.view(db)


@app.get("/api/journal/stats")
def journal_stats(db: Session = Depends(get_db)):
    return JS.stats(db)


@app.get("/api/journal/export.csv")
def journal_export(db: Session = Depends(get_db)):
    return Response(JS.export_csv(db), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="trade-journal.csv"'})


@app.get("/api/journal/entry")
def journal_entry(key: str, db: Session = Depends(get_db)):
    return JS.detail(db, key)


@app.put("/api/journal/entry")
def journal_save(key: str, body: JournalIn, db: Session = Depends(get_db)):
    return JS.save(db, key, body.model_dump())


@app.post("/api/journal/skip")
def journal_skip(body: JournalSkipIn, db: Session = Depends(get_db)):
    return JS.skip(db, body.keys, body.older)


@app.put("/api/journal/tags")
def journal_tags(body: JournalTagsIn, db: Session = Depends(get_db)):
    return JS.set_tags(db, body.reasons, body.sell_reasons)


class StarIn(BaseModel):
    key: str
    starred: bool = True


@app.put("/api/journal/star")
def journal_star(body: StarIn, db: Session = Depends(get_db)):
    return JS.set_star(db, body.key, body.starred)


class IdeaIn(BaseModel):
    sector: str | None = None
    stock: str | None = None
    ticker: str | None = None
    exchange: str | None = None
    side: str | None = None
    levels: list[dict] | None = None
    near_pct: float | None = None
    reasons: list[str] | None = None
    confidence: int | None = None
    notes: str | None = None
    status: str | None = None
    retry_prices: bool = False


class IdeaBoughtIn(BaseModel):
    key: str


@app.get("/api/journal/ideas")
def ideas(db: Session = Depends(get_db)):
    return IS.view(db)


@app.get("/api/journal/ideas/unseen")
def ideas_unseen(db: Session = Depends(get_db)):
    return {"unseen": IS.unseen(db)}


@app.post("/api/journal/ideas/seen")
def ideas_seen(db: Session = Depends(get_db)):
    return IS.mark_seen(db)


@app.post("/api/journal/ideas")
def idea_create(body: IdeaIn, db: Session = Depends(get_db)):
    return IS.create(db, body.model_dump(exclude_unset=True))


@app.put("/api/journal/ideas/{idea_id}")
def idea_update(idea_id: int, body: IdeaIn, db: Session = Depends(get_db)):
    return IS.update(db, idea_id, body.model_dump(exclude_unset=True))


@app.delete("/api/journal/ideas/{idea_id}")
def idea_delete(idea_id: int, db: Session = Depends(get_db)):
    return IS.remove(db, idea_id)


@app.get("/api/journal/ideas/{idea_id}/buys")
def idea_buys(idea_id: int, db: Session = Depends(get_db)):
    return {"buys": IS.candidates(db, idea_id)}


@app.post("/api/journal/ideas/{idea_id}/bought")
def idea_bought(idea_id: int, body: IdeaBoughtIn, db: Session = Depends(get_db)):
    return IS.bought(db, idea_id, body.key)


# ---------------------------------------------------------------- break-even calculator

class BreakevenIn(BaseModel):
    calcs: list


@app.get("/api/breakeven")
def breakeven(db: Session = Depends(get_db)):
    return BE.get(db)


@app.put("/api/breakeven")
def breakeven_save(body: BreakevenIn, db: Session = Depends(get_db)):
    return BE.put(db, body.calcs)


# ---------------------------------------------------------------- demo mode

@app.get("/api/mode")
def mode(db: Session = Depends(get_db)):
    """Live or demo: the frontend's switch and banner come from this answer (what is really served), not the cookie."""
    return DS.info(db)


@app.post("/api/demo/reset")
def demo_reset(db: Session = Depends(get_db)):
    if not DEMO.DEMO:
        raise P.BadRequest("Reset exists in demo mode only: your real data is never reset.")
    return DS.reset(db)
