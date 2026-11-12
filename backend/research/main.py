import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from research.api.routes import router
from research.broker.base import BrokerError
from research.market_data.tiingo import MarketDataError
from research.services.analysis import BadRequest, NotFound
from research.services.portfolio import FxMissing

log = logging.getLogger("fibonacci_ai")

app = FastAPI(title="Fibonacci AI", version="0.1.0",
              description="Personal investment research tool. Not investment advice. "
                          "Phase 1 uses SYNTHETIC data only.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["GET", "PUT", "POST", "DELETE"], allow_headers=["*"])
app.include_router(router)


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error_code": code, "message": message})


@app.exception_handler(NotFound)
async def _nf(_: Request, e: NotFound):
    return _err(404, "not_found", str(e))


@app.exception_handler(BadRequest)
async def _br(_: Request, e: BadRequest):
    return _err(400, "bad_request", str(e))


@app.exception_handler(FxMissing)
async def _fx(_: Request, e: FxMissing):
    return _err(422, "fx_missing", str(e))


@app.exception_handler(BrokerError)
async def _broker(_: Request, e: BrokerError):
    status = 429 if e.code == "cooldown" else 400 if e.code == "not_configured" else 502
    return _err(status, e.code, e.message)


@app.exception_handler(MarketDataError)
async def _md(_: Request, e: MarketDataError):
    status = {"not_configured": 400, "bad_symbol": 400, "not_found": 404, "unsupported_exchange": 400,
              "budget": 429, "rate_limited": 429, "plan_limit": 429, "auth": 401, "synthetic": 400}.get(e.code, 502)
    return _err(status, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def _val(_: Request, e: RequestValidationError):
    msgs = "; ".join(f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in e.errors())
    return _err(422, "validation_error", msgs)


@app.exception_handler(Exception)
async def _any(_: Request, e: Exception):
    # Never echo internals to the client.
    log.exception("unhandled error")  # server-side only; no request bodies or env logged
    return _err(500, "internal_error", "An internal error occurred. See server log.")
