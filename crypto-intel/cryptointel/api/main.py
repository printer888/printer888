"""REST API + static dashboard.

Run:  uvicorn cryptointel.api.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .. import DISCLAIMER, __version__
from ..backtest.engine import BacktestConfig, run_backtest
from ..backtest.strategies import PARAM_GRIDS, STRATEGIES
from ..backtest.walkforward import holdout_test, walk_forward
from ..config import Settings, get_settings
from ..data.freshness import utcnow
from ..db.repository import _clean
from ..indicators import ta
from ..logging_setup import setup_logging
from ..ml.model import evaluate as ml_evaluate
from ..risk.leverage import LEVERAGE_LEVELS, CostModel, compare_leverage
from ..services.monitor import IntelligenceService

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class LeverageRequest(BaseModel):
    equity: float = Field(10_000, gt=0)
    side: Literal["long", "short"] = "long"
    entry: float = Field(..., gt=0)
    stop: float = Field(..., gt=0)
    targets: list[float] = Field(..., min_length=1, max_length=5)
    risk_pct: float = Field(0.01, gt=0, le=0.1)
    margin_fraction: float = Field(0.1, gt=0, le=1)
    funding_rate: float = Field(0.0001, ge=-0.01, le=0.01)
    funding_intervals: float = Field(3, ge=0, le=1000)
    levels: list[float] = Field(default_factory=lambda: list(LEVERAGE_LEVELS))
    mmr: float | None = Field(None, gt=0, lt=0.5)

    @model_validator(mode="after")
    def _check(self):
        d = 1 if self.side == "long" else -1
        if d * (self.entry - self.stop) <= 0:
            raise ValueError("stop must be below entry for longs / above entry for shorts")
        if any(d * (t - self.entry) <= 0 for t in self.targets):
            raise ValueError("targets must be beyond entry in the trade direction")
        if any(l < 1 or l > 100 for l in self.levels):
            raise ValueError("leverage levels must be within 1–100")
        return self


class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    timeframe: Literal["15m", "1h", "4h", "1d"] = "1h"
    strategy: str = "trend_pullback"
    mode: Literal["single", "walk_forward", "holdout"] = "walk_forward"
    days: int = Field(365, ge=30, le=1500)
    params: dict = Field(default_factory=dict)
    use_funding_history: bool = True


def create_app(service: IntelligenceService | None = None, autostart: bool | None = None,
               settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    autostart = (os.environ.get("CI_AUTOSTART", "1") == "1") if autostart is None else autostart
    state: dict = {"service": service}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state["service"] is None:
            state["service"] = IntelligenceService(settings)
        task = asyncio.create_task(state["service"].run_forever()) if autostart else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="CryptoIntel", version=__version__, lifespan=lifespan,
                  description="Crypto market intelligence & simulation. " + DISCLAIMER)

    def svc() -> IntelligenceService:
        if state["service"] is None:
            raise HTTPException(503, "service not initialised")
        return state["service"]

    @app.get("/api/health")
    def health():
        s = state["service"]
        return {"status": "ok", "version": __version__, "disclaimer": DISCLAIMER,
                "last_scan_at": s.last_scan_at.isoformat() if s and s.last_scan_at else None,
                "recent_errors": s.errors[-10:] if s else []}

    @app.get("/api/config")
    def config():
        return _clean(settings.redacted())

    @app.get("/api/overview")
    def overview():
        s = svc()
        if not s.overview:
            return {"ready": False, "message": "first scan not completed yet", "errors": s.errors[-5:]}
        return {"ready": True, **s.overview, "paper": _clean(s.broker.performance()), "disclaimer": DISCLAIMER}

    @app.get("/api/opportunities")
    def opportunities(status: Literal["SIGNAL", "NO_TRADE"] | None = None):
        opps = list(svc().opportunities.values())
        if status:
            opps = [o for o in opps if o["status"] == status]
        opps.sort(key=lambda o: (o["status"] != "SIGNAL", -o["score"]))
        return {"as_of": svc().last_scan_at.isoformat() if svc().last_scan_at else None, "items": opps,
                "disclaimer": DISCLAIMER}

    @app.get("/api/opportunities/history")
    def opportunity_history(limit: int = Query(100, le=1000), status: str | None = None):
        return svc().repo.recent_opportunities(limit, status)

    @app.get("/api/analysis/{symbol}")
    def analysis(symbol: str):
        a = svc().analyses.get(symbol.upper())
        if not a:
            raise HTTPException(404, f"{symbol} not analysed (not in universe or scan pending)")
        return a

    @app.get("/api/candles/{symbol}")
    def candles(symbol: str, tf: Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"] = "1h",
                limit: int = Query(300, ge=50, le=1000)):
        try:
            df = svc().klines(symbol.upper(), tf, limit)
        except Exception as e:
            raise HTTPException(502, f"Bybit data unavailable: {e}")
        if df.empty:
            raise HTTPException(404, "no candles")
        out = df.copy()  # indicators use full history, then trim to `limit`
        for n in (20, 50, 200):
            out[f"ema{n}"] = ta.ema(out["close"], n)
        bb = ta.bollinger(out["close"])
        out["bb_upper"], out["bb_lower"] = bb["upper"], bb["lower"]
        out["rsi"] = ta.rsi(out["close"])
        out["t"] = out.index.as_unit("s").asi8
        out = out.tail(limit)
        return {"symbol": symbol.upper(), "timeframe": tf, "closed_candles_only": True,
                "rows": _clean(out.reset_index(drop=True).to_dict(orient="records"))}

    @app.post("/api/leverage/simulate")
    def leverage(req: LeverageRequest):
        costs = CostModel(settings.taker_fee, settings.maker_fee, settings.slippage_bps, req.mmr or settings.default_mmr)
        return _clean(compare_leverage(
            req.levels, equity=req.equity, side=req.side, entry=req.entry, stop=req.stop, targets=req.targets,
            risk_pct=req.risk_pct, margin_fraction=req.margin_fraction, funding_rate=req.funding_rate,
            funding_intervals=req.funding_intervals, costs=costs))

    @app.get("/api/paper/trades")
    def paper_trades(status: Literal["open", "closed"] | None = None):
        b = svc().broker
        trades = b.open_trades() if status == "open" else b.closed_trades() if status == "closed" else list(b.trades.values())
        return _clean([t.to_dict() for t in sorted(trades, key=lambda t: t.id, reverse=True)])

    @app.get("/api/paper/performance")
    def paper_perf():
        b = svc().broker
        return _clean({**b.performance(), "equity_history": b.equity_history[-1000:]})

    @app.post("/api/paper/close-all")
    def paper_close_all():
        s = svc()
        evs = s.broker.close_all()
        for t in s.broker.trades.values():
            s._persist_trade(t.to_dict())
        return _clean(evs)

    @app.post("/api/backtest")
    async def backtest(req: BacktestRequest):
        if req.strategy not in STRATEGIES:
            raise HTTPException(400, f"unknown strategy; choose from {list(STRATEGIES)}")
        s = svc()

        def work():
            end = utcnow()
            start = end - timedelta(days=req.days)
            df = s.client.klines_range(req.symbol.upper(), req.timeframe, int(start.timestamp() * 1000),
                                       int(end.timestamp() * 1000))
            if len(df) < 600:
                raise HTTPException(422, f"only {len(df)} bars available")
            funding = None
            if req.use_funding_history:
                try:
                    funding = s.client.funding_history(req.symbol.upper(), 200, int(start.timestamp() * 1000),
                                                       int(end.timestamp() * 1000))
                except Exception:
                    funding = None
            cfg = BacktestConfig(timeframe=req.timeframe, initial_equity=settings.paper_starting_equity,
                                 risk_per_trade=settings.risk_per_trade, max_leverage=settings.paper_leverage,
                                 taker_fee=settings.taker_fee, maker_fee=settings.maker_fee,
                                 slippage_bps=settings.slippage_bps, funding_series=funding)
            cls = STRATEGIES[req.strategy]
            if req.mode == "single":
                bt = run_backtest(df, cls(**req.params), cfg, trade_start=250)
                res, eq = bt.summary(), bt.equity
                res["equity"] = [{"t": t.isoformat(), "v": float(v)} for t, v in eq.iloc[:: max(1, len(eq) // 500)].items()]
                res["warning"] = ("Single in-sample run with fixed parameters — use walk_forward or holdout to judge "
                                  "robustness.")
            elif req.mode == "walk_forward":
                n = len(df)
                train = max(int((n - 250) * 0.5), 300)
                test = max(int((n - 250 - train) / 4), 100)
                res = walk_forward(df, cls, PARAM_GRIDS[req.strategy], cfg, train, test)
            else:
                res = holdout_test(df, cls, PARAM_GRIDS[req.strategy], cfg)
            res["data"] = {"bars": len(df), "from": df.index[0].isoformat(), "to": df.index[-1].isoformat(),
                           "funding": "historical series" if funding is not None and len(funding) else
                           f"assumed constant {cfg.funding_rate_per_interval * 100:.3f}%/8h"}
            res = _clean(res)
            s.repo.save_backtest(req.mode, req.strategy, req.symbol.upper(), req.timeframe, req.params, res)
            return res

        try:
            return await asyncio.to_thread(work)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"backtest failed: {e}")

    @app.get("/api/backtests")
    def backtests(limit: int = 20):
        return svc().repo.backtests(limit)

    @app.get("/api/ml/{symbol}")
    async def ml(symbol: str, tf: Literal["15m", "1h", "4h"] = "1h", horizon: int = Query(12, ge=1, le=96)):
        s = svc()

        def work():
            df = s.client.klines(symbol.upper(), tf, limit=1000)
            return _clean(ml_evaluate(df, horizon=horizon, cost=2 * (settings.taker_fee + settings.slippage_bps / 1e4)))

        try:
            return await asyncio.to_thread(work)
        except Exception as e:
            raise HTTPException(502, f"ML evaluation failed: {e}")

    @app.get("/api/news")
    def news(limit: int = Query(60, le=500)):
        s = svc()
        items = [e.to_dict() for e in s.news[:limit]] or s.repo.recent_news(limit)
        return {"items": _clean(items), "sources": settings.news_feeds,
                "note": "Reuters/Bloomberg/FT require licensed feeds and are not ingested."}

    @app.get("/api/alerts")
    def alerts(limit: int = Query(100, le=500)):
        return svc().repo.alerts(limit)

    @app.post("/api/scan")
    async def scan_now():
        s = svc()
        await asyncio.to_thread(s.scan)
        return {"ok": True, "last_scan_at": s.last_scan_at.isoformat() if s.last_scan_at else None,
                "errors": s.errors[-5:]}

    @app.exception_handler(ValueError)
    async def value_error(_, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app() if os.environ.get("CI_NO_APP") != "1" else None
