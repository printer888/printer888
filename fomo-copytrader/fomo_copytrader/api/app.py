"""FastAPI app: REST + WebSocket for the remote dashboard."""
from __future__ import annotations

import asyncio
import hmac
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from ..config import LIVE_ACK_PHRASE, Settings, get_settings
from ..engine.metrics import performance_report_md, portfolio_summary, position_dict
from ..models import CopyOrder, Position, TraderEvent
from ..runtime import Runtime
from ..schemas import RiskLimits
from ..trader.analytics import analyse
from ..trader.monitor import fetch_history

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class TraderIn(BaseModel):
    wallet: str = Field(min_length=32, max_length=44)
    label: str | None = Field(None, max_length=128)
    fomo_profile: str | None = Field(None, max_length=256)
    force: bool = False


class EmergencyIn(BaseModel):
    flatten: bool = False


class ArmIn(BaseModel):
    confirm: str


def _dt(v):
    return v.isoformat() if v else None


def event_dict(e: TraderEvent) -> dict:
    return dict(id=e.id, signature=e.signature, kind=e.kind, token_mint=e.token_mint, token_symbol=e.token_symbol,
                token_amount=e.token_amount, pre=e.token_pre_balance, post=e.token_post_balance,
                quote_mint=e.quote_mint, quote_amount=e.quote_amount, price_usd=e.price_usd,
                notional_usd=e.notional_usd, block_time=_dt(e.block_time), detected_at=_dt(e.detected_at),
                latency_sec=e.latency_sec, copy_status=e.copy_status, copy_note=e.copy_note, error=e.error)


def order_dict(o: CopyOrder) -> dict:
    return dict(id=o.id, side=o.side, reason=o.reason, token_mint=o.token_mint, status=o.status, mode=o.mode,
                requested_usd=o.requested_usd, requested_fraction=o.requested_fraction, token_amount=o.token_amount,
                price_usd=o.price_usd, reference_price_usd=o.reference_price_usd, notional_usd=o.notional_usd,
                fees_usd=o.fees_usd, slippage_usd=o.slippage_usd, price_impact_pct=o.price_impact_pct,
                execution_diff_pct=o.execution_diff_pct, realized_pnl_usd=o.realized_pnl_usd,
                signature=o.signature, error=o.error, trader_signature=o.trader_signature,
                created_at=_dt(o.created_at), completed_at=_dt(o.completed_at), risk_checks=o.risk_checks)


def create_app(runtime: Runtime | None = None, settings: Settings | None = None,
               start_background: bool = True) -> FastAPI:
    settings = settings or get_settings()
    if settings.app_env == "prod" and not settings.dashboard_token:
        raise RuntimeError("DASHBOARD_TOKEN is required in prod")
    rt = runtime or Runtime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await rt.init()
        if start_background:
            rt.start_background()
            await rt.resume_from_state()
        yield
        await rt.shutdown()

    app = FastAPI(title="FOMO Copy Trader", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.rt = rt

    def check_token(tok: str | None) -> None:
        expected = settings.dashboard_token
        if not expected:
            return  # dev mode without auth (refused in prod above)
        if not tok or not hmac.compare_digest(tok, expected):
            raise HTTPException(401, "unauthorised")

    def auth(request: Request) -> None:
        h = request.headers.get("authorization", "")
        check_token(h[7:] if h.lower().startswith("bearer ") else None)

    A = [Depends(auth)]

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/health")
    async def health():
        db_ok = True
        try:
            async with rt.sm() as s:
                await s.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        st = await rt.state.status()
        last = rt.monitor.last_poll_ok
        poll_age = time.time() - last if last else None
        healthy = db_ok and (not st.get("monitoring") or (poll_age is not None and poll_age < settings.watchdog_stale_sec))
        body = dict(ok=healthy, db=db_ok, leader=rt.coord.is_leader, monitoring=st.get("monitoring"), poll_age_sec=poll_age,
                    ws=rt.monitor.ws_status, uptime_sec=time.time() - rt.started_at)
        if not healthy:
            raise HTTPException(503, body)
        return body

    async def status_payload() -> dict:
        st = await rt.state.status()
        limits = await rt.state.limits()
        t = await rt.active_trader()
        fee = await rt.engine.est_network_fee_usd()
        async with rt.sm() as s:
            last_ev = (await s.execute(select(TraderEvent).order_by(TraderEvent.id.desc()).limit(1))).scalar_one_or_none()
        return dict(
            status=st, mode=rt.executor.mode,
            live_permitted=settings.live_execution_permitted,
            trader=dict(wallet=t.wallet, label=t.label, fomo_profile=t.fomo_profile,
                        last_activity_at=_dt(t.last_activity_at), stats=t.stats) if t else None,
            latest_event=event_dict(last_ev) if last_ev else None,
            monitor=dict(running=rt.monitor.running, ws=rt.monitor.ws_status, last_poll_ok=rt.monitor.last_poll_ok,
                         errors=rt.monitor.errors),
            summary=await portfolio_summary(rt.sm, limits.total_capital_usd, fee),
            notifications=rt.notifier.sent[-10:], telegram_enabled=rt.notifier.enabled,
        )

    @app.get("/api/status", dependencies=A)
    async def status():
        return await status_payload()

    @app.get("/api/positions", dependencies=A)
    async def positions(state: str = Query("open", pattern="^(open|closed|all)$"), limit: int = 200):
        fee = await rt.engine.est_network_fee_usd()
        async with rt.sm() as s:
            q = select(Position).order_by(Position.id.desc()).limit(limit)
            if state != "all":
                q = q.where(Position.status == state)
            return [position_dict(p, fee) for p in (await s.execute(q)).scalars()]

    @app.post("/api/positions/{position_id}/close", dependencies=A)
    async def close_position(position_id: int):
        async with rt.sm() as s:
            p = await s.get(Position, position_id)
        if p is None or p.status != "open":
            raise HTTPException(404, "no such open position")
        ok = await rt.engine.reduce_position(position_id, 1.0, "manual_close",
                                             key=f"manual:{position_id}:{time.time_ns()}")
        await rt.state.audit("control", f"manual close of position #{position_id}: {'filled' if ok else 'failed'}")
        return dict(ok=ok)

    @app.get("/api/events", dependencies=A)
    async def events(limit: int = Query(100, le=1000)):
        async with rt.sm() as s:
            rows = (await s.execute(select(TraderEvent).order_by(TraderEvent.id.desc()).limit(limit))).scalars()
            return [event_dict(e) for e in rows]

    @app.get("/api/orders", dependencies=A)
    async def orders(limit: int = Query(100, le=1000)):
        async with rt.sm() as s:
            rows = (await s.execute(select(CopyOrder).order_by(CopyOrder.id.desc()).limit(limit))).scalars()
            return [order_dict(o) for o in rows]

    @app.get("/api/audit", dependencies=A)
    async def audit(limit: int = Query(100, le=1000)):
        return [dict(at=_dt(a.at), level=a.level, category=a.category, message=a.message, data=a.data)
                for a in await rt.state.recent_audit(limit)]

    @app.get("/api/risk", dependencies=A)
    async def get_risk():
        return (await rt.state.limits()).model_dump()

    @app.put("/api/risk", dependencies=A)
    async def put_risk(limits: RiskLimits):
        await rt.state.set_limits(limits)
        await rt.state.audit("control", "risk limits updated", limits.model_dump())
        rt.bus.publish("status")
        return limits.model_dump()

    @app.post("/api/trader", dependencies=A)
    async def set_trader(body: TraderIn):
        async with rt.sm() as s:
            n_open = len(list((await s.execute(select(Position).where(Position.status == "open"))).scalars()))
        if n_open and not body.force:
            raise HTTPException(409, f"{n_open} open copied positions. Close them or resend with force=true; "
                                     "they will then be managed only by independent exit protection.")
        try:
            t = await rt.set_trader(body.wallet, body.label, body.fomo_profile)
        except ValueError as e:
            raise HTTPException(422, f"invalid Solana address: {e}") from e
        rt.bus.publish("status")
        return dict(wallet=t.wallet, label=t.label)

    @app.get("/api/trader/{wallet}/analysis", dependencies=A)
    async def analysis(wallet: str, max_tx: int = Query(300, ge=10, le=2000), latency_penalty_pct: float = 2.0):
        try:
            events = await fetch_history(rt.rpc, wallet, max_tx=max_tx)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"history fetch failed: {e}") from e
        quotes = {m: (await rt.market.price_usd(m)) for m in {e.quote_mint for e in events if e.quote_mint}}
        report = analyse(wallet, events, {k: v for k, v in quotes.items() if v}, latency_penalty_pct)
        return report.to_dict()

    @app.post("/api/control/{action}", dependencies=A)
    async def control(action: str, request: Request):
        body = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
        st = await rt.state.status()
        if action == "start_monitoring":
            try:
                await rt.start_monitoring()
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        elif action == "stop_monitoring":
            await rt.stop_monitoring()
        elif action == "start_copying":
            if st.get("emergency_stop"):
                raise HTTPException(409, "clear the emergency stop first")
            if not st.get("monitoring"):
                await rt.start_monitoring()
            await rt.state.update_status(copying=True, paused=False, suspended_reason=None, consecutive_failures=0)
        elif action == "pause":
            await rt.state.update_status(paused=True, suspended_reason="paused by operator")
        elif action == "resume":
            if st.get("emergency_stop"):
                raise HTTPException(409, "clear the emergency stop first")
            await rt.state.update_status(paused=False, suspended_reason=None, consecutive_failures=0)
        elif action == "stop_copying":
            await rt.state.update_status(copying=False, live_armed=False)
        elif action == "emergency_stop":
            closed = await rt.engine.emergency_stop(flatten=bool(EmergencyIn(**body).flatten))
            await rt.state.update_status(copying=False)
            return dict(ok=True, closed=closed)
        elif action == "clear_emergency":
            await rt.state.update_status(emergency_stop=False, suspended_reason=None)
        elif action == "arm_live":
            if not settings.live_execution_permitted:
                raise HTTPException(403, "live execution is not enabled in server configuration")
            if ArmIn(**body).confirm != LIVE_ACK_PHRASE:
                raise HTTPException(400, "confirmation phrase mismatch")
            if st.get("emergency_stop"):
                raise HTTPException(409, "clear the emergency stop first")
            await rt.state.update_status(live_armed=True)
        elif action == "disarm_live":
            await rt.state.update_status(live_armed=False)
        elif action == "reconcile":
            from ..engine.reconcile import reconcile
            return dict(ok=True, issues=await reconcile(rt.engine))
        else:
            raise HTTPException(404, "unknown action")
        await rt.state.audit("control", f"action: {action}")
        rt.bus.publish("status")
        return dict(ok=True, status=await rt.state.status())

    @app.get("/api/report", dependencies=A)
    async def report():
        limits = await rt.state.limits()
        return await portfolio_summary(rt.sm, limits.total_capital_usd, await rt.engine.est_network_fee_usd())

    @app.get("/api/report.md", dependencies=A, response_class=PlainTextResponse)
    async def report_md():
        limits = await rt.state.limits()
        return await performance_report_md(rt.sm, limits.total_capital_usd,
                                           await rt.engine.est_network_fee_usd(), rt.executor.mode)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        # Browsers cannot set headers on websockets; the token comes as the first message.
        await websocket.accept()
        try:
            first = await asyncio.wait_for(websocket.receive_json(), timeout=10)
            check_token(first.get("token"))
        except Exception:  # noqa: BLE001
            await websocket.close(code=4401)
            return
        q = rt.bus.subscribe()
        try:
            await websocket.send_json({"topic": "status", "data": await status_payload()})
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=10)
                    await websocket.send_json(msg)
                except asyncio.TimeoutError:
                    await websocket.send_json({"topic": "status", "data": await status_payload()})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            rt.bus.unsubscribe(q)

    return app
