"""REST API consumed by the PWA. Run: uvicorn app.api.main:app --port 8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import DEFAULT_SYMBOLS, NIFTY_50, settings
from app.data.feed import INTERVAL_MINUTES, YFinanceFeed
from app.engine.backtest import run_backtest
from app.live.service import TradingService
from app.predict.scanner import PROMOTE_IC_MARGIN, PROMOTE_MIN_CANDLES, Scanner
from app.storage.db import Store
from app.strategies import REGISTRY

logging.basicConfig(level=logging.INFO)

store = Store(settings.db_path)
feed = YFinanceFeed(settings)
scanner = Scanner(feed, NIFTY_50, store=store)
service = TradingService(feed, store, scanner, settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    service.start()
    yield
    service.stop()


app = FastAPI(title="TradeBot API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(401, "Invalid or missing API key (set it in Settings)")


def bad_request(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


# ---------- status ----------
@app.get("/api/health")
def health():
    return {"ok": True, **service.status()}


@app.get("/api/status")
def status():
    return {**service.status(), "scanner_refreshing": scanner.refreshing, "scanner_error": scanner.error,
            "scanner_generated_at": (scanner.result or {}).get("generated_at")}


# ---------- scanner / predictions ----------
@app.get("/api/scanner")
def get_scanner(limit: int = 5):
    r = scanner.result
    if not r:
        return {"ready": False, "refreshing": scanner.refreshing, "error": scanner.error, "stocks": []}
    amount = service.bot.amount_per_trade
    stocks = [{**s, "predicted_profit": round(amount * s["predicted_return_pct"] / 100, 2),
               "held": s["symbol"] in service.broker.positions}
              for s in r["stocks"][:limit]]
    return {"ready": True, "refreshing": scanner.refreshing, "error": scanner.error,
            **{k: v for k, v in r.items() if k != "stocks"}, "stocks": stocks}


@app.get("/api/model/accuracy")
def model_accuracy(days: int | None = None, model: str | None = None):
    """Live forecast accuracy (scored 1h later), per-trade accuracy, model leaderboard, retrain history."""
    champ = scanner.champion
    return {"champion": champ, "live": scanner.live_accuracy(days, model), "trades": service.trade_accuracy(),
            "leaderboard": scanner.leaderboard(),
            "promotion_rule": {"min_candles": PROMOTE_MIN_CANDLES, "ic_margin": PROMOTE_IC_MARGIN},
            "backtest_history": store.model_runs(200, champ),
            "current_model": (scanner.result or {}).get("model")}


class ChampionRequest(BaseModel):
    model: str


@app.post("/api/model/champion", dependencies=[Depends(require_key)])
def set_champion(req: ChampionRequest):
    try:
        scanner.set_champion(req.model)
    except ValueError as e:
        raise bad_request(e) from e
    scanner.refresh_async()  # re-rank picks with the new champion
    return {"champion": scanner.champion}


@app.get("/api/futures")
def futures():
    return service.futures()


@app.post("/api/scanner/refresh", dependencies=[Depends(require_key)])
def refresh_scanner():
    scanner.refresh_async()
    return {"refreshing": True}


# ---------- portfolio ----------
@app.get("/api/portfolio")
def portfolio():
    return service.portfolio()


@app.get("/api/trades")
def trades(source: str | None = None, limit: int = 200):
    return list(reversed(service.trades(source)))[:limit]


@app.get("/api/equity")
def equity():
    return store.equity(service.run_id)


@app.get("/api/activity")
def activity(limit: int = 50):
    return store.events(service.run_id, limit)


class OrderRequest(BaseModel):
    symbol: str
    side: str = "BUY"                 # BUY | SELL (short)
    amount: float | None = None       # Rs to invest; or give qty
    qty: int | None = None
    stop_loss_pct: float | None = None
    target_pct: float | None = None
    lots: int | None = None           # index futures: number of lots


@app.post("/api/orders", dependencies=[Depends(require_key)])
async def place_order(req: OrderRequest):
    if req.side.upper() not in ("BUY", "SELL"):
        raise HTTPException(400, "side must be BUY or SELL")
    try:
        return await run_in_threadpool(service.manual_order, req.symbol, req.side, req.amount, req.qty,
                                       req.stop_loss_pct, req.target_pct, req.lots)
    except ValueError as e:
        raise bad_request(e) from e


@app.post("/api/positions/{symbol}/close", dependencies=[Depends(require_key)])
async def close_position(symbol: str):
    try:
        return await run_in_threadpool(service.close, symbol)
    except ValueError as e:
        raise bad_request(e) from e


# ---------- bot settings ----------
@app.get("/api/bot")
def get_bot():
    from dataclasses import asdict
    return asdict(service.bot)


@app.put("/api/bot", dependencies=[Depends(require_key)])
def update_bot(patch: dict):
    from dataclasses import asdict
    import threading
    was_on, was_fut = service.bot.auto_enabled, service.bot.futures_auto_enabled
    try:
        bot = service.update_settings(patch)
    except TypeError as e:
        raise bad_request(e) from e
    if (bot.auto_enabled and not was_on) or (bot.futures_auto_enabled and not was_fut):
        # Act on the current picks right away instead of waiting for the next candle.
        threading.Thread(target=lambda: service.auto_enter(service.clock()), daemon=True).start()
    return asdict(bot)


class ResetRequest(BaseModel):
    capital: float = Field(100_000, gt=1000)


@app.post("/api/account/reset", dependencies=[Depends(require_key)])
def reset_account(req: ResetRequest):
    service.reset(req.capital)
    return service.portfolio()


# ---------- strategy lab (backtests) ----------
@app.get("/api/meta")
def meta():
    return {
        "strategies": [{"name": c.name, "description": c.description, "default_params": c.default_params}
                       for c in REGISTRY.values()],
        "intervals": list(INTERVAL_MINUTES),
        "default_symbols": DEFAULT_SYMBOLS,
        "universe": NIFTY_50,
        "settings": {k: getattr(settings, k) for k in (
            "initial_capital", "slippage_bps", "risk_per_trade_pct", "max_position_pct",
            "max_open_positions", "max_daily_loss_pct", "default_stop_loss_pct",
            "default_take_profit_pct", "allow_short", "margin_rate")},
        "auth_required": bool(settings.api_key),
    }


class BacktestRequest(BaseModel):
    strategy: str = "ema_crossover"
    symbols: list[str] = Field(default_factory=lambda: DEFAULT_SYMBOLS[:5])
    interval: str = "15m"
    period: str = "60d"
    params: dict = Field(default_factory=dict)
    initial_capital: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


@app.post("/api/backtests", dependencies=[Depends(require_key)])
async def create_backtest(req: BacktestRequest):
    if req.strategy not in REGISTRY:
        raise HTTPException(400, f"Unknown strategy {req.strategy}")
    if req.interval not in INTERVAL_MINUTES:
        raise HTTPException(400, f"Interval must be one of {list(INTERVAL_MINUTES)}")
    s = settings.with_overrides(initial_capital=req.initial_capital,
                                default_stop_loss_pct=req.stop_loss_pct,
                                default_take_profit_pct=req.take_profit_pct)
    try:
        res = await run_in_threadpool(run_backtest, feed, req.strategy, req.symbols,
                                      req.interval, req.period, req.params, s)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Backtest failed: {e}") from e
    if res.metrics["trading_days"] == 0:
        raise HTTPException(422, "No market data returned. Check symbols, or shorten the period "
                                 "(15m data only goes back 60 days).")
    run_id = store.create_run("backtest", req.strategy, [x.upper() for x in req.symbols], req.interval,
                              req.period, req.params, s.initial_capital, "done")
    store.update_run(run_id, metrics=res.metrics)
    store.add_trades(run_id, res.trades)
    store.add_equity(run_id, res.equity)
    store.add_events(run_id, res.events[-500:])
    return {"run_id": run_id, "metrics": res.metrics, "symbols_without_data": res.symbols_without_data}


@app.get("/api/runs")
def list_runs(kind: str | None = "backtest", limit: int = 50):
    return store.list_runs(kind, limit)


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    run.pop("state", None)
    return run


@app.get("/api/runs/{run_id}/trades")
def run_trades(run_id: int):
    return store.trades(run_id)


@app.get("/api/runs/{run_id}/equity")
def run_equity(run_id: int):
    return store.equity(run_id)
