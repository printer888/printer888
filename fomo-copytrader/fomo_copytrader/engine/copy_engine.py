"""Copy engine: turns verified trader events into risk-checked copy orders.

Flow for every trader transaction:
  1. Persist the event. The unique constraint on (signature, mint, kind)
     makes processing idempotent: websocket + polling + restarts can deliver
     the same transaction many times, it is only ever acted on once.
  2. Price it in USD and notify.
  3. BUY  -> size, gather market/contract/route data, run risk checks,
             create a CopyOrder (unique idempotency key), execute, record.
     SELL -> compute the trader's sold fraction from on-chain pre/post
             balances, reduce our position by the same fraction, record
             realised P/L net of all costs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..bus import EventBus
from ..chain.rpc import SolanaRpc
from ..constants import LAMPORTS_PER_SOL, STABLE_MINTS, USDC_MINT, WSOL_MINT
from ..execution.base import Executor
from ..market.provider import MarketData
from ..market.token_safety import inspect_token
from ..models import CopyOrder, Position, Trader, TraderEvent, utcnow
from ..notify.telegram import Notifier, fmt_price, fmt_usd, short
from ..risk.engine import BuyContext, PortfolioState, check_buy, portfolio_halt_reasons, size_buy
from ..schemas import EventKind, ExecutionResult, Side, SwapEvent, TokenSafety
from .state import StateStore

log = logging.getLogger(__name__)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class CopyEngine:
    def __init__(self, sm: async_sessionmaker, state: StateStore, market: MarketData, executor: Executor,
                 notifier: Notifier, bus: EventBus, rpc: SolanaRpc | None = None,
                 fee_lamports: int = 105_000, safety_inspector=None, funding: str = "USDC"):
        self.sm = sm
        self.state = state
        self.market = market
        self.executor = executor
        self.notifier = notifier
        self.bus = bus
        self.rpc = rpc
        self.fee_lamports = fee_lamports
        self._inspect = safety_inspector or (lambda mint: inspect_token(self.rpc, mint))
        self.funding_mint = USDC_MINT if funding == "USDC" else WSOL_MINT

    # ------------------------------------------------------------------ utils
    async def est_network_fee_usd(self) -> float:
        sol = await self.market.price_usd(WSOL_MINT) or 0.0
        return self.fee_lamports / LAMPORTS_PER_SOL * sol

    async def trader_label(self, wallet: str) -> str:
        async with self.sm() as s:
            t = (await s.execute(select(Trader).where(Trader.wallet == wallet))).scalar_one_or_none()
        return (t.label if t and t.label else short(wallet))

    async def portfolio_state(self, mint: str | None = None) -> PortfolioState:
        st = await self.state.status()
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.sm() as s:
            open_pos = list((await s.execute(select(Position).where(Position.status == "open"))).scalars())
            realized_total = (await s.execute(select(func.coalesce(func.sum(Position.realized_pnl_usd), 0.0)))).scalar()
        realized_today = await self.realized_since(today)
        unreal = sum(self.unrealized(p) for p in open_pos)
        return PortfolioState(
            open_positions=len(open_pos),
            allocated_usd=sum(p.my_cost_basis_usd for p in open_pos),
            realized_pnl_total_usd=float(realized_total or 0),
            realized_pnl_today_usd=realized_today,
            unrealized_pnl_usd=unreal,
            equity_peak_usd=float(st.get("equity_peak_usd") or 0),
            consecutive_failures=int(st.get("consecutive_failures") or 0),
            emergency_stop=bool(st.get("emergency_stop")),
            paused=bool(st.get("paused")) or not st.get("copying"),
            holding_mint=any(p.token_mint == mint for p in open_pos) if mint else False,
        )

    async def realized_since(self, since: datetime) -> float:
        """Realised P/L (net of all costs) booked by SELL orders completed since ``since``."""
        async with self.sm() as s:
            v = (await s.execute(select(func.coalesce(func.sum(CopyOrder.realized_pnl_usd), 0.0)).where(
                CopyOrder.side == "SELL", CopyOrder.status == "filled", CopyOrder.completed_at >= since))).scalar()
            return float(v or 0)

    @staticmethod
    def unrealized(p: Position) -> float:
        if p.last_price_usd is None:
            return 0.0
        return p.my_amount * p.last_price_usd - p.my_cost_basis_usd

    async def _usd_price_of_event(self, ev: SwapEvent) -> tuple[float | None, float | None]:
        """(price_usd per token, notional_usd) of the trader's trade."""
        if ev.quote_mint and ev.price_in_quote is not None:
            qpx = 1.0 if ev.quote_mint in STABLE_MINTS else await self.market.price_usd(ev.quote_mint)
            if qpx:
                return ev.price_in_quote * qpx, ev.quote_amount * qpx
        if ev.token_mint:
            px = await self.market.price_usd(ev.token_mint)
            if px:
                return px, px * ev.token_amount
        return None, None

    # ----------------------------------------------------------- entry point
    async def handle_event(self, ev: SwapEvent) -> TraderEvent | None:
        now = datetime.now(timezone.utc)
        price_usd, notional = (None, None)
        if ev.kind not in (EventKind.FAILED, EventKind.OTHER):
            price_usd, notional = await self._usd_price_of_event(ev)
        symbol = None
        if ev.token_mint:
            m = await self.market.token_market(ev.token_mint)
            symbol = m.symbol if m else None
        rec = TraderEvent(
            trader_wallet=ev.wallet, signature=ev.signature, slot=ev.slot, block_time=ev.block_time,
            kind=ev.kind.value, token_mint=ev.token_mint or "", token_symbol=symbol,
            token_amount=ev.token_amount, token_pre_balance=ev.token_pre_balance,
            token_post_balance=ev.token_post_balance, quote_mint=ev.quote_mint, quote_amount=ev.quote_amount,
            price_usd=price_usd, notional_usd=notional, error=ev.error,
            latency_sec=(now - ev.block_time).total_seconds() if ev.block_time else None,
        )
        async with self.sm() as s:
            s.add(rec)
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                dup = (await s.execute(select(TraderEvent.id).where(
                    TraderEvent.signature == ev.signature, TraderEvent.token_mint == (ev.token_mint or ""),
                    TraderEvent.kind == ev.kind.value))).first()
                if dup is None:
                    raise
                log.info("duplicate event ignored: %s %s", ev.signature, ev.kind)
                return None
            t = (await s.execute(select(Trader).where(Trader.wallet == ev.wallet))).scalar_one_or_none()
            if t and ev.kind != EventKind.OTHER:
                t.last_activity_at = ev.block_time or now
                await s.commit()
        if ev.kind != EventKind.OTHER:
            await self.state.update_status(inactive_alert_sent=False)
        self.bus.publish("trader_event", {"id": rec.id, "kind": rec.kind, "symbol": symbol})

        label = await self.trader_label(ev.wallet)
        tok = symbol or short(ev.token_mint)
        if ev.kind == EventKind.BUY:
            await self.notifier.send("TRADER BUY", [
                ("Trader", label), ("Token", tok), ("Amount", f"{ev.token_amount:,.4f}"),
                ("Value", fmt_usd(notional)), ("Price", fmt_price(price_usd)), ("Tx", short(ev.signature))])
            await self._copy_buy(ev, rec, price_usd, notional, symbol)
        elif ev.kind in (EventKind.SELL_FULL, EventKind.SELL_PARTIAL):
            pct = 100 * (1.0 if ev.kind == EventKind.SELL_FULL else ev.sell_fraction)
            await self.notifier.send("TRADER SELL", [
                ("Trader", label), ("Token", tok), ("Sold", f"{pct:.1f}% of position"),
                ("Value", fmt_usd(notional)), ("Price", fmt_price(price_usd)), ("Tx", short(ev.signature))])
            await self._copy_sell(ev, rec, price_usd)
        elif ev.kind == EventKind.FAILED:
            await self._set_event(rec.id, "ignored", f"trader transaction failed on-chain: {ev.error}")
        elif ev.kind in (EventKind.TRANSFER_IN, EventKind.TRANSFER_OUT):
            await self._handle_transfer(ev, rec)
        else:
            await self._set_event(rec.id, "ignored", "no token balance change for this wallet")
        return rec

    async def _set_event(self, event_id: int, status: str, note: str | None) -> None:
        async with self.sm() as s:
            e = await s.get(TraderEvent, event_id)
            e.copy_status, e.copy_note = status, note
            await s.commit()
        self.bus.publish("trader_event_update", {"id": event_id, "status": status})

    async def _open_position(self, wallet: str, mint: str) -> Position | None:
        async with self.sm() as s:
            return (await s.execute(select(Position).where(
                Position.trader_wallet == wallet, Position.token_mint == mint,
                Position.status == "open"))).scalar_one_or_none()

    # --------------------------------------------------------------- buying
    async def _copy_buy(self, ev: SwapEvent, rec: TraderEvent, trader_px: float | None,
                        trader_notional: float | None, symbol: str | None) -> None:
        st = await self.state.status()
        if not st.get("copying"):
            return await self._set_event(rec.id, "ignored", "copying is off (monitor only)")
        limits = await self.state.limits()
        pstate = await self.portfolio_state(ev.token_mint)
        halt = portfolio_halt_reasons(limits, pstate)
        if halt:
            return await self._skip(rec, ev, symbol, halt)

        sizing = size_buy(limits, pstate, trader_notional)
        if not sizing.approved:
            return await self._skip(rec, ev, symbol, sizing.reasons)

        market = await self.market.token_market(ev.token_mint)
        safety: TokenSafety | None = await self._inspect(ev.token_mint)
        cur_px = await self.market.price_usd(ev.token_mint)
        fund_px = await self.market.price_usd(self.funding_mint)
        fund_dec = 6 if self.funding_mint == USDC_MINT else 9
        quote = None
        if fund_px:
            quote = await self.market.quote(self.funding_mint, ev.token_mint,
                                            int(sizing.size_usd / fund_px * 10 ** fund_dec), limits.max_slippage_bps)
        age = (datetime.now(timezone.utc) - ev.block_time).total_seconds() if ev.block_time else None
        ctx = BuyContext(token_mint=ev.token_mint, trader_price_usd=trader_px, trader_notional_usd=trader_notional,
                         current_price_usd=cur_px, signal_age_sec=age, market=market, safety=safety, quote=quote,
                         est_network_fee_usd=await self.est_network_fee_usd())
        decision = check_buy(limits, pstate, ctx, sizing.size_usd)
        decision.checks.update(sizing.checks)
        if not decision.approved:
            return await self._skip(rec, ev, symbol, decision.reasons, decision.checks)

        order = await self._create_order(f"{ev.signature}:{ev.token_mint}:BUY", Side.BUY, "copy_buy",
                                         ev.token_mint, ev.signature, requested_usd=sizing.size_usd,
                                         reference_price=trader_px, checks=decision.checks,
                                         impact=quote.price_impact_pct if quote else None)
        if order is None:
            return await self._set_event(rec.id, "ignored", "duplicate order prevented")
        res = await self._execute(order, lambda: self.executor.buy(
            ev.token_mint, ev.token_decimals or 0, sizing.size_usd, limits.max_slippage_bps))
        if not res.success:
            await self._set_event(rec.id, "failed", res.error)
            return
        pos = await self._apply_buy(ev, res, trader_px, symbol)
        diff = (100 * (res.price_usd - trader_px) / trader_px) if (trader_px and res.price_usd) else None
        await self._finish_order(order.id, res, pos.id, diff)
        await self._set_event(rec.id, "copied", f"order #{order.id}")
        await self.notifier.send("COPY TRADE ALERT", [
            ("Trader", await self.trader_label(ev.wallet)), ("Action", "BUY"),
            ("Token", f"{symbol or short(ev.token_mint)}"),
            ("Original entry", fmt_price(trader_px)), ("My execution", fmt_price(res.price_usd)),
            ("Size", fmt_usd(res.notional_usd)), ("Costs", fmt_usd(res.network_fee_usd + res.slippage_cost_usd)),
            ("Status", "Executed" + (" (paper)" if res.simulated else "")),
            ("Execution difference", f"{diff:+.2f}%" if diff is not None else "n/a")])

    async def _skip(self, rec: TraderEvent, ev: SwapEvent, symbol: str | None, reasons: list[str],
                    checks: dict | None = None) -> None:
        note = "; ".join(reasons)
        await self._set_event(rec.id, "skipped", note)
        await self.state.audit("risk", f"BUY {symbol or ev.token_mint} skipped: {note}", checks)
        await self.notifier.send("COPY SKIPPED", [
            ("Token", symbol or short(ev.token_mint)), ("Reason", note)], footer="Risk checks rejected this copy.")

    async def _apply_buy(self, ev: SwapEvent, res: ExecutionResult, trader_px: float | None,
                         symbol: str | None) -> Position:
        async with self.sm() as s:
            pos = (await s.execute(select(Position).where(
                Position.trader_wallet == ev.wallet, Position.token_mint == ev.token_mint,
                Position.status == "open"))).scalar_one_or_none()
            if pos is None:
                pos = Position(trader_wallet=ev.wallet, token_mint=ev.token_mint, token_symbol=symbol,
                               token_decimals=ev.token_decimals or 0, mode=self.executor.mode,
                               trader_entry_price_usd=trader_px, my_amount=0.0, my_amount_raw="0",
                               my_cost_basis_usd=0.0, my_invested_usd=0.0, realized_pnl_usd=0.0,
                               fees_usd=0.0, slippage_usd=0.0, trader_initial_amount=0.0, exit_attempts=0)
                s.add(pos)
            elif trader_px and pos.trader_entry_price_usd and pos.trader_initial_amount:
                w0, w1 = pos.trader_initial_amount, ev.token_amount
                pos.trader_entry_price_usd = (pos.trader_entry_price_usd * w0 + trader_px * w1) / (w0 + w1)
            cost = res.notional_usd + res.network_fee_usd  # all entry costs go into basis
            pos.my_amount += res.out_amount_ui
            pos.my_amount_raw = str(int(pos.my_amount_raw) + res.out_amount_raw)
            pos.my_cost_basis_usd += cost
            pos.my_invested_usd += cost
            pos.my_entry_price_usd = pos.my_cost_basis_usd / pos.my_amount if pos.my_amount else None
            pos.fees_usd += res.network_fee_usd + res.platform_fee_usd
            pos.slippage_usd += res.slippage_cost_usd
            pos.trader_initial_amount += ev.token_amount
            pos.trader_current_amount = ev.token_post_balance
            pos.trader_last_action, pos.trader_last_action_at = "BUY", ev.block_time
            pos.last_price_usd = res.price_usd
            pos.peak_price_usd = max(pos.peak_price_usd or 0, res.price_usd or 0) or None
            pos.last_alert_price_usd = res.price_usd
            await s.commit()
            await s.refresh(pos)
        self.bus.publish("position", {"id": pos.id})
        return pos

    # -------------------------------------------------------------- selling
    async def _copy_sell(self, ev: SwapEvent, rec: TraderEvent, trader_px: float | None) -> None:
        pos = await self._open_position(ev.wallet, ev.token_mint)
        st = await self.state.status()
        if pos is None:
            return await self._set_event(rec.id, "ignored", "no copied position in this token")
        fraction = 1.0 if ev.kind == EventKind.SELL_FULL else ev.sell_fraction
        async with self.sm() as s:
            p = await s.get(Position, pos.id)
            p.trader_current_amount = ev.token_post_balance
            p.trader_last_action = ev.kind.value
            p.trader_last_action_at = ev.block_time
            await s.commit()
        if not st.get("copying"):
            return await self._set_event(rec.id, "ignored",
                                         "copying stopped: position left to independent exit protection")
        await self.reduce_position(pos.id, fraction, reason="copy_sell", key=f"{ev.signature}:{ev.token_mint}:SELL",
                                   trader_sig=ev.signature, reference_price=trader_px, event_id=rec.id)

    async def reduce_position(self, position_id: int, fraction: float, reason: str, key: str,
                              trader_sig: str | None = None, reference_price: float | None = None,
                              event_id: int | None = None) -> bool:
        """Sell ``fraction`` of our position. Never blocked by portfolio limits (risk-reducing)."""
        limits = await self.state.limits()
        async with self.sm() as s:
            pos = await s.get(Position, position_id)
        if pos is None or pos.status != "open":
            return False
        held_raw = int(pos.my_amount_raw)
        fraction = max(0.0, min(1.0, fraction))
        sell_raw = held_raw if fraction >= 0.999 else int(held_raw * fraction)
        if sell_raw <= 0:
            if event_id:
                await self._set_event(event_id, "ignored", "computed sell size is zero")
            return False
        order = await self._create_order(key, Side.SELL, reason, pos.token_mint, trader_sig,
                                         requested_fraction=fraction, reference_price=reference_price,
                                         position_id=pos.id)
        if order is None:
            if event_id:
                await self._set_event(event_id, "ignored", "duplicate order prevented")
            return False
        res = await self._execute(order, lambda: self.executor.sell(
            pos.token_mint, pos.token_decimals, sell_raw, limits.max_exit_slippage_bps))
        if not res.success:
            async with self.sm() as s:
                p = await s.get(Position, pos.id)
                p.pending_exit_fraction = fraction
                p.pending_exit_reason = reason
                p.exit_attempts = (p.exit_attempts or 0) + 1
                await s.commit()
            if event_id:
                await self._set_event(event_id, "failed", f"exit failed, will retry: {res.error}")
            return False
        pnl, closed, pos = await self._apply_sell(pos.id, res, sell_raw, reason)
        diff = (100 * (res.price_usd - reference_price) / reference_price) if (reference_price and res.price_usd) else None
        await self._finish_order(order.id, res, pos.id, diff, realized=pnl)
        if event_id:
            await self._set_event(event_id, "copied", f"order #{order.id}")
        await self.notifier.send("COPY TRADE CLOSED" if closed else "COPY POSITION REDUCED", [
            ("Trader", await self.trader_label(pos.trader_wallet)), ("Action", f"SELL ({reason})"),
            ("Token", pos.token_symbol or short(pos.token_mint)),
            ("Sold", f"{100 * fraction:.1f}%"), ("Exit price", fmt_price(res.price_usd)),
            ("Trader exit", fmt_price(reference_price)),
            ("My position", "Closed" if closed else f"{pos.my_amount:,.4f} remaining"),
            ("Net P/L (this sale)", fmt_usd(pnl, signed=True)),
            ("Position net P/L", fmt_usd(pos.realized_pnl_usd, signed=True)),
            ("Status", "Completed" + (" (paper)" if res.simulated else ""))],
            footer="P/L is after entry fees, exit fees, network fees and slippage.")
        return True

    async def _apply_sell(self, position_id: int, res: ExecutionResult, sold_raw: int,
                          reason: str) -> tuple[float, bool, Position]:
        async with self.sm() as s:
            pos = await s.get(Position, position_id)
            held_raw = int(pos.my_amount_raw)
            actual_raw = min(held_raw, res.in_amount_raw or sold_raw)
            portion = actual_raw / held_raw if held_raw else 1.0
            basis_out = pos.my_cost_basis_usd * portion
            proceeds = res.notional_usd - res.network_fee_usd - res.platform_fee_usd
            pnl = proceeds - basis_out
            pos.my_cost_basis_usd -= basis_out
            pos.my_amount_raw = str(held_raw - actual_raw)
            pos.my_amount = int(pos.my_amount_raw) / 10 ** pos.token_decimals if pos.token_decimals else \
                pos.my_amount * (1 - portion)
            pos.realized_pnl_usd += pnl
            pos.fees_usd += res.network_fee_usd + res.platform_fee_usd
            pos.slippage_usd += res.slippage_cost_usd
            pos.last_price_usd = res.price_usd or pos.last_price_usd
            pos.pending_exit_fraction = None
            pos.pending_exit_reason = None
            closed = int(pos.my_amount_raw) <= 0
            if closed:
                pos.status, pos.closed_at, pos.exit_reason = "closed", utcnow(), reason
                pos.my_cost_basis_usd = 0.0
                pos.my_amount = 0.0
            await s.commit()
            await s.refresh(pos)
        self.bus.publish("position", {"id": pos.id})
        return pnl, closed, pos

    async def _handle_transfer(self, ev: SwapEvent, rec: TraderEvent) -> None:
        pos = await self._open_position(ev.wallet, ev.token_mint) if ev.token_mint else None
        if pos and ev.kind == EventKind.TRANSFER_OUT:
            async with self.sm() as s:
                p = await s.get(Position, pos.id)
                p.trader_current_amount = ev.token_post_balance
                p.trader_last_action, p.trader_last_action_at = "TRANSFER_OUT", ev.block_time
                await s.commit()
            await self.notifier.send("TRADER MOVED TOKENS", [
                ("Token", pos.token_symbol or short(pos.token_mint)),
                ("Amount", f"{ev.token_amount:,.4f}"), ("Remaining with trader", f"{ev.token_post_balance:,.4f}")],
                footer="Not a sale (no quote leg). Not mirrored; the trader may sell from another wallet. "
                       "Independent exit protection remains active.")
            return await self._set_event(rec.id, "ignored", "token transfer (not a trade); alert sent")
        await self._set_event(rec.id, "ignored", f"{ev.kind.value.lower()} not mirrored")

    # ---------------------------------------------------------- order plumbing
    async def _create_order(self, key: str, side: Side, reason: str, mint: str, trader_sig: str | None,
                            requested_usd: float | None = None, requested_fraction: float | None = None,
                            reference_price: float | None = None, checks: dict | None = None,
                            impact: float | None = None, position_id: int | None = None) -> CopyOrder | None:
        async with self.sm() as s:
            o = CopyOrder(idempotency_key=key, side=side.value, reason=reason, token_mint=mint,
                          trader_signature=trader_sig, status="pending", mode=self.executor.mode,
                          requested_usd=requested_usd, requested_fraction=requested_fraction,
                          reference_price_usd=reference_price, risk_checks=checks,
                          price_impact_pct=impact, position_id=position_id)
            s.add(o)
            try:
                await s.commit()
            except IntegrityError:
                await self.state.audit("dedupe", f"duplicate order blocked: {key}", level="WARNING")
                return None
            await s.refresh(o)
            return o

    async def _execute(self, order: CopyOrder, fn) -> ExecutionResult:
        st = await self.state.status()
        if st.get("emergency_stop") and order.side == "BUY":
            res = ExecutionResult(False, Side.BUY, "", order.token_mint, error="emergency stop active")
        else:
            try:
                res = await fn()
            except Exception as e:  # noqa: BLE001
                log.exception("execution error")
                res = ExecutionResult(False, Side(order.side), "", order.token_mint, error=f"{type(e).__name__}: {e}")
        if not res.success:
            async with self.sm() as s:
                o = await s.get(CopyOrder, order.id)
                o.status, o.error, o.completed_at = "failed", res.error, utcnow()
                o.signature = res.signature
                await s.commit()
            fails = int(st.get("consecutive_failures") or 0) + 1
            await self.state.update_status(consecutive_failures=fails)
            limits = await self.state.limits()
            await self.state.audit("execution", f"{order.side} {order.token_mint} failed: {res.error}",
                                   {"order_id": order.id}, level="WARNING")
            await self.notifier.send("TRANSACTION FAILED", [
                ("Order", f"#{order.id} {order.side} ({order.reason})"), ("Token", short(order.token_mint)),
                ("Error", res.error or "unknown"), ("Consecutive failures", str(fails))])
            if fails >= limits.max_consecutive_failures and not st.get("paused"):
                await self.suspend(f"{fails} consecutive execution failures")
            self.bus.publish("order", {"id": order.id})
        else:
            await self.state.update_status(consecutive_failures=0)
        return res

    async def _finish_order(self, order_id: int, res: ExecutionResult, position_id: int,
                            diff: float | None, realized: float | None = None) -> None:
        async with self.sm() as s:
            o = await s.get(CopyOrder, order_id)
            o.status, o.completed_at, o.position_id = "filled", utcnow(), position_id
            o.token_amount = res.out_amount_ui if res.side == Side.BUY else res.in_amount_ui
            o.price_usd, o.notional_usd = res.price_usd, res.notional_usd
            o.fees_usd = res.network_fee_usd + res.platform_fee_usd
            o.slippage_usd = res.slippage_cost_usd
            o.execution_diff_pct = diff
            o.signature = res.signature
            o.realized_pnl_usd = realized
            await s.commit()
        self.bus.publish("order", {"id": order_id})

    # ------------------------------------------------------------- controls
    async def suspend(self, reason: str) -> None:
        await self.state.update_status(paused=True, suspended_reason=reason)
        await self.state.audit("control", f"copy trading suspended: {reason}", level="WARNING")
        await self.notifier.send("COPY TRADING SUSPENDED", [("Reason", reason)],
                                 footer="No new positions will be opened. Exits continue. Resume from the dashboard.")
        self.bus.publish("status", None)

    async def emergency_stop(self, flatten: bool, reason: str = "operator") -> int:
        await self.state.update_status(emergency_stop=True, paused=True, live_armed=False,
                                       suspended_reason=f"emergency stop: {reason}")
        await self.state.audit("control", f"EMERGENCY STOP ({reason}), flatten={flatten}", level="WARNING")
        closed = 0
        if flatten:
            async with self.sm() as s:
                ids = [p.id for p in (await s.execute(select(Position).where(Position.status == "open"))).scalars()]
            for pid in ids:
                if await self.reduce_position(pid, 1.0, "emergency_exit", f"emergency:{pid}:{utcnow().isoformat()}"):
                    closed += 1
        await self.notifier.send("EMERGENCY STOP", [
            ("Reason", reason), ("Live trading", "disarmed"),
            ("Positions closed", f"{closed}" if flatten else "not requested")])
        self.bus.publish("status", None)
        return closed
