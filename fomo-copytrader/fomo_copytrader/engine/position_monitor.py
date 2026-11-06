"""Independent position supervision.

Runs on its own timer, regardless of whether the trader ever sells:
* marks positions to market and tracks liquidity
* enforces stop-loss / take-profit / trailing-stop / max-hold policy
* retries exits that previously failed
* alerts on significant price moves and on trader inactivity
* keeps the equity high-water mark used by the drawdown limit
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..models import Position, Trader
from ..notify.telegram import fmt_price, short
from ..risk.engine import exit_reason
from .copy_engine import CopyEngine, _aware

log = logging.getLogger(__name__)


class PositionMonitor:
    def __init__(self, engine: CopyEngine):
        self.engine = engine
        self.last_run: datetime | None = None

    async def run_once(self, now: datetime | None = None) -> None:
        eng = self.engine
        now = now or datetime.now(timezone.utc)
        limits = await eng.state.limits()
        async with eng.sm() as s:
            positions = list((await s.execute(select(Position).where(Position.status == "open"))).scalars())
        for pos in positions:
            price = await eng.market.price_usd(pos.token_mint)
            market = await eng.market.token_market(pos.token_mint)
            async with eng.sm() as s:
                p = await s.get(Position, pos.id)
                if price is not None:
                    p.last_price_usd = price
                    p.peak_price_usd = max(p.peak_price_usd or price, price)
                if market and market.liquidity_usd is not None:
                    p.last_liquidity_usd = market.liquidity_usd
                await s.commit()
                await s.refresh(p)
            pos = p

            # 1. retry a failed exit first
            if pos.pending_exit_fraction:
                await eng.reduce_position(pos.id, pos.pending_exit_fraction, pos.pending_exit_reason or "retry_exit",
                                          key=f"retry:{pos.id}:{pos.exit_attempts}")
                continue

            # 2. independent risk exits
            reason = exit_reason(limits, entry_price=pos.my_entry_price_usd, price=price,
                                 peak_price=pos.peak_price_usd, opened_at=_aware(pos.opened_at), now=now,
                                 trader_last_activity=None)
            if reason:
                await eng.notifier.send("RISK LIMIT REACHED", [
                    ("Token", pos.token_symbol or short(pos.token_mint)), ("Rule", reason),
                    ("Entry (incl. costs)", fmt_price(pos.my_entry_price_usd)), ("Current", fmt_price(price))],
                    footer="Closing copied position under the configured risk policy.")
                await eng.reduce_position(pos.id, 1.0, reason.split(" ")[0], key=f"risk:{pos.id}:{reason.split(' ')[0]}")
                continue

            # 3. price move alerts
            if price and pos.last_alert_price_usd:
                move = 100 * (price - pos.last_alert_price_usd) / pos.last_alert_price_usd
                if abs(move) >= limits.price_move_alert_pct:
                    await eng.notifier.send("SIGNIFICANT PRICE MOVE", [
                        ("Token", pos.token_symbol or short(pos.token_mint)), ("Move", f"{move:+.1f}%"),
                        ("Price", fmt_price(price)),
                        ("Unrealised P/L (before exit costs)", f"${eng.unrealized(pos):,.2f}")])
                    async with eng.sm() as s:
                        (await s.get(Position, pos.id)).last_alert_price_usd = price
                        await s.commit()

        await self._check_inactivity(now, limits.trader_inactive_hours)
        await self._update_peak(limits.total_capital_usd)
        self.last_run = now

    async def _check_inactivity(self, now: datetime, hours: float) -> None:
        eng = self.engine
        st = await eng.state.status()
        if not st.get("monitoring") or st.get("inactive_alert_sent"):
            return
        async with eng.sm() as s:
            t = (await s.execute(select(Trader).where(Trader.active.is_(True)))).scalar_one_or_none()
        if not t:
            return
        ref = _aware(t.last_activity_at) or _aware(t.created_at)
        if ref and now - ref > timedelta(hours=hours):
            await eng.notifier.send("TRADER INACTIVE", [
                ("Trader", t.label or short(t.wallet)), ("Last activity", ref.isoformat(timespec="minutes")),
                ("Threshold", f"{hours:g}h")])
            await eng.state.update_status(inactive_alert_sent=True)

    async def _update_peak(self, capital: float) -> None:
        eng = self.engine
        ps = await eng.portfolio_state()
        eq = ps.equity(capital)
        st = await eng.state.status()
        if eq > float(st.get("equity_peak_usd") or 0):
            await eng.state.update_status(equity_peak_usd=eq)


