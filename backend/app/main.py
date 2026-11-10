"""Portfolio Tracker API (local only)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models as m
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
