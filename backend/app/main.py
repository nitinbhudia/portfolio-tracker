"""Portfolio Tracker API (local only)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models as m
from app.services import benchmarks as BMS
from app.services import entries as E
from app.services import portfolio as P

MAX_UPLOAD = 50 * 1024 * 1024



@asynccontextmanager
async def lifespan(_app):
    m.init_db()
    yield


app = FastAPI(title="Portfolio Tracker", version="0.1.0", lifespan=lifespan)
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
