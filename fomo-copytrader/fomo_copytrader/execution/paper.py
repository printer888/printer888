"""Paper executor: real quotes, simulated fills, explicit cost model.

Each simulated fill uses a live Jupiter quote for the exact size (so depth and
price impact are real), then subtracts an additional latency-slippage haircut
and charges the same network fees a live transaction would pay.
"""
from __future__ import annotations

from ..constants import LAMPORTS_PER_SOL, SOL_DECIMALS, USDC_MINT, WSOL_MINT
from ..market.provider import MarketData
from ..schemas import ExecutionResult, Side


class PaperExecutor:
    mode = "paper"

    def __init__(self, market: MarketData, funding: str = "USDC", extra_slippage_bps: int = 50,
                 fee_lamports: int = 105_000):
        self.market = market
        self.funding_mint = USDC_MINT if funding == "USDC" else WSOL_MINT
        self.funding_decimals = 6 if funding == "USDC" else SOL_DECIMALS
        self.extra_bps = extra_slippage_bps
        self.fee_lamports = fee_lamports

    async def _fee_usd(self) -> float:
        sol = await self.market.price_usd(WSOL_MINT) or 0.0
        return self.fee_lamports / LAMPORTS_PER_SOL * sol

    async def buy(self, mint, decimals, usd_amount, slippage_bps) -> ExecutionResult:
        res = ExecutionResult(False, Side.BUY, self.funding_mint, mint, simulated=True)
        fund_px = await self.market.price_usd(self.funding_mint)
        mid = await self.market.price_usd(mint)
        if not fund_px or not mid:
            res.error = "price unavailable"
            return res
        in_raw = int(usd_amount / fund_px * 10 ** self.funding_decimals)
        q = await self.market.quote(self.funding_mint, mint, in_raw, slippage_bps)
        if q is None or q.out_amount_raw <= 0:
            res.error = "no route / quote"
            return res
        out_raw = int(q.out_amount_raw * (1 - self.extra_bps / 10_000))
        out_ui = out_raw / 10 ** decimals
        notional = q.in_amount_raw / 10 ** self.funding_decimals * fund_px
        res.success = True
        res.in_amount_raw, res.in_amount_ui = q.in_amount_raw, q.in_amount_raw / 10 ** self.funding_decimals
        res.out_amount_raw, res.out_amount_ui = out_raw, out_ui
        res.notional_usd = notional
        res.price_usd = notional / out_ui if out_ui else None
        res.slippage_cost_usd = max(0.0, notional - out_ui * mid)
        res.network_fee_usd = await self._fee_usd()
        res.signature = f"paper-{mint[:6]}-{in_raw}-{out_raw}"
        return res

    async def sell(self, mint, decimals, amount_raw, slippage_bps) -> ExecutionResult:
        res = ExecutionResult(False, Side.SELL, mint, self.funding_mint, simulated=True)
        fund_px = await self.market.price_usd(self.funding_mint)
        mid = await self.market.price_usd(mint)
        if not fund_px:
            res.error = "funding price unavailable"
            return res
        q = await self.market.quote(mint, self.funding_mint, amount_raw, slippage_bps)
        if q is None or q.out_amount_raw <= 0:
            res.error = "no exit route / quote"
            return res
        out_raw = int(q.out_amount_raw * (1 - self.extra_bps / 10_000))
        in_ui = amount_raw / 10 ** decimals
        usd_out = out_raw / 10 ** self.funding_decimals * fund_px
        res.success = True
        res.in_amount_raw, res.in_amount_ui = amount_raw, in_ui
        res.out_amount_raw, res.out_amount_ui = out_raw, out_raw / 10 ** self.funding_decimals
        res.notional_usd = usd_out
        res.price_usd = usd_out / in_ui if in_ui else None
        res.slippage_cost_usd = max(0.0, in_ui * mid - usd_out) if mid else 0.0
        res.network_fee_usd = await self._fee_usd()
        res.signature = f"paper-{mint[:6]}-sell-{amount_raw}"
        return res
