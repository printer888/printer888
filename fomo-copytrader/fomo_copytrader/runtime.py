"""Wires components together and runs the background loops."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone


from sqlalchemy import select

from .bus import EventBus
from .chain.rpc import SolanaRpc
from .config import Settings
from .coordination import Coordinator
from .db import init_db, make_engine, make_sessionmaker
from .engine.copy_engine import CopyEngine
from .engine.metrics import portfolio_summary
from .engine.position_monitor import PositionMonitor
from .engine.reconcile import reconcile
from .engine.state import StateStore
from .execution.paper import PaperExecutor
from .market.dexscreener import DexScreener
from .market.jupiter import Jupiter
from .market.provider import LiveMarketData, MarketData
from .models import Trader
from .schemas import RiskLimits
from .notify.telegram import Notifier, fmt_usd, short
from .trader.monitor import TraderMonitor

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings: Settings, *, market: MarketData | None = None, rpc: SolanaRpc | None = None,
                 notifier: Notifier | None = None, executor=None, safety_inspector=None, enable_ws: bool = True):
        self.settings = settings
        self.db_engine = make_engine(settings.database_url)
        self.sm = make_sessionmaker(self.db_engine)
        self.bus = EventBus()
        self.state = StateStore(self.sm)
        self.rpc = rpc or SolanaRpc(settings.solana_rpc_url, timeout=settings.rpc_timeout_sec)
        self.jup = Jupiter(settings.jupiter_base_url, settings.jupiter_api_key)
        self.market = market or LiveMarketData(DexScreener(settings.dexscreener_base_url), self.jup)
        self.notifier = notifier or Notifier(settings.telegram_bot_token, settings.telegram_chat_id)
        fee = settings.base_fee_lamports + settings.priority_fee_lamports
        self.executor = executor or self._make_executor(fee)
        self.engine = CopyEngine(self.sm, self.state, self.market, self.executor, self.notifier, self.bus,
                                 rpc=self.rpc, fee_lamports=fee, safety_inspector=safety_inspector,
                                 funding=settings.funding_mint)
        self.coord = Coordinator(settings.redis_url)
        self.monitor = TraderMonitor(self.rpc, self.sm, self.engine.handle_event,
                                     ws_url=settings.solana_ws_url if enable_ws else None,
                                     poll_interval=settings.rpc_poll_interval_sec, coordinator=self.coord)
        self.positions = PositionMonitor(self.engine)
        self._tasks: list[asyncio.Task] = []
        self.started_at = time.time()
        self.last_loop_ok: dict[str, float] = {}

    def _make_executor(self, fee: int):
        s = self.settings
        if s.execution_mode == "live":
            from .execution.live import LiveExecutor  # only imported when configured

            return LiveExecutor(s, self.rpc, self.jup, self.market, is_armed=lambda: self.state.cached_live_armed)
        return PaperExecutor(self.market, funding=s.funding_mint, extra_slippage_bps=s.paper_extra_slippage_bps,
                             fee_lamports=fee)

    async def init(self) -> None:
        await init_db(self.db_engine)
        st = await self.state.status()
        if not await self.state._get("risk_limits"):  # first boot: persist defaults
            await self.state.set_limits(RiskLimits(total_capital_usd=self.settings.paper_starting_capital_usd))
        if self.settings.initial_trader_wallet and not await self.active_trader():
            await self.set_trader(self.settings.initial_trader_wallet)
        # Live arming never survives a restart: the operator must re-arm.
        if st.get("live_armed"):
            await self.state.update_status(live_armed=False)

    async def active_trader(self) -> Trader | None:
        async with self.sm() as s:
            return (await s.execute(select(Trader).where(Trader.active.is_(True)))).scalar_one_or_none()

    async def set_trader(self, wallet: str, label: str | None = None, profile: str | None = None) -> Trader:
        from solders.pubkey import Pubkey

        Pubkey.from_string(wallet)  # validates base58 address; raises ValueError
        async with self.sm() as s:
            for t in (await s.execute(select(Trader).where(Trader.active.is_(True)))).scalars():
                t.active = False
            t = (await s.execute(select(Trader).where(Trader.wallet == wallet))).scalar_one_or_none()
            if t is None:
                t = Trader(wallet=wallet)
                s.add(t)
            t.active = True
            t.label = label or t.label
            t.fomo_profile = profile or t.fomo_profile
            t.last_signature = None  # look forward from now on
            await s.commit()
            await s.refresh(t)
        await self.state.audit("control", f"selected trader {wallet}")
        self.monitor.wallet = wallet
        if (await self.state.status()).get("monitoring"):
            await self.monitor.start(wallet)
        return t

    async def start_monitoring(self) -> None:
        t = await self.active_trader()
        if not t:
            raise ValueError("select a trader first")
        if not self.coord.is_leader:
            raise ValueError("this instance is on standby (another instance holds the leader lock)")
        await self.monitor.start(t.wallet)
        await self.state.update_status(monitoring=True)

    async def stop_monitoring(self) -> None:
        await self.monitor.stop()
        await self.state.update_status(monitoring=False)

    # ------------------------------------------------------------ loops
    def start_background(self) -> None:
        self._tasks = [
            asyncio.create_task(self._leadership_loop()),
            asyncio.create_task(self._loop("positions", self.settings.position_check_interval_sec,
                                           self.positions.run_once)),
            asyncio.create_task(self._loop("reconcile", self.settings.reconcile_interval_sec, self._reconcile)),
            asyncio.create_task(self._loop("watchdog", 30, self._watchdog)),
            asyncio.create_task(self._loop("daily_report", 60, self._daily_report)),
        ]

    async def resume_from_state(self) -> None:
        st = await self.state.status()
        if st.get("monitoring") and await self.active_trader() and await self.coord.acquire_or_renew():
            await self.start_monitoring()

    async def _leadership_loop(self) -> None:
        """Only the leader monitors/trades. Losing the lock stops the monitor immediately."""
        while True:
            was = self.coord.is_leader
            now = await self.coord.acquire_or_renew()
            if was and not now:
                await self.monitor.stop()
                await self.notifier.send("LEADERSHIP LOST", [("Instance", self.coord.ident)],
                                         footer="This instance stopped monitoring to avoid duplicate orders.")
            elif now and not was:
                await self.resume_from_state()
            await asyncio.sleep(self.coord.ttl_ms / 3000)

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.monitor.stop()
        await self.coord.close()
        await self.db_engine.dispose()

    async def _loop(self, name: str, interval: float, fn) -> None:
        while True:
            try:
                if self.coord.is_leader:
                    await fn()
                self.last_loop_ok[name] = time.time()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("%s loop failed", name)
            await asyncio.sleep(interval)

    async def _reconcile(self) -> None:
        balances = None
        if hasattr(self.executor, "wallet_token_balances"):
            balances = await self.executor.wallet_token_balances()
        await reconcile(self.engine, balances)

    async def _watchdog(self) -> None:
        st = await self.state.status()
        if not st.get("monitoring"):
            return
        stale = self.settings.watchdog_stale_sec
        last = self.monitor.last_poll_ok
        if not self.monitor.running:
            await self.notifier.send("MONITOR DOWN", [("Action", "restarting trader monitor")])
            await self.start_monitoring()
        elif last and time.time() - last > stale:
            await self.notifier.send("MONITOR STALLED", [("Last successful poll", f"{time.time() - last:.0f}s ago")],
                                     footer="Check the RPC provider. Copies may be delayed; stale BUY signals are skipped.")

    async def _daily_report(self) -> None:
        now = datetime.now(timezone.utc)
        st = await self.state.status()
        today = now.date().isoformat()
        if now.hour != self.settings.daily_report_hour_utc or st.get("last_daily_report") == today:
            return
        limits = await self.state.limits()
        summ = await portfolio_summary(self.sm, limits.total_capital_usd, await self.engine.est_network_fee_usd())
        t = await self.active_trader()
        await self.notifier.send("DAILY PERFORMANCE REPORT", [
            ("Mode", self.executor.mode), ("Trader", (t.label or short(t.wallet)) if t else "none"),
            ("Realised today (net)", fmt_usd(summ["today_realized_pnl_usd"], True)),
            ("Realised total (net)", fmt_usd(summ["realized_pnl_usd"], True)),
            ("Unrealised (before exit costs)", fmt_usd(summ["unrealized_pnl_usd"], True)),
            ("Total costs", fmt_usd(summ["total_costs_usd"])),
            ("Open / closed", f"{summ['open_positions']} / {summ['closed_positions']}"),
            ("Equity", fmt_usd(summ["equity_usd"]))])
        await self.state.update_status(last_daily_report=today)


