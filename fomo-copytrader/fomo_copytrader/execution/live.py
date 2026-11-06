"""Live executor (DISABLED unless explicitly authorised).

Construction fails unless EXECUTION_MODE=live, LIVE_TRADING_ACK carries the
exact acknowledgement phrase, and a keypair file is configured. The engine
additionally requires the operator to *arm* live trading from the dashboard
at runtime; every call checks that flag again.

Security properties:
* The wallet used here should be a dedicated hot wallet funded only with the
  capital you allocate to copying. It is *not* your FOMO (Privy) wallet.
* The only transactions this module can sign are Jupiter swaps whose input
  and output are between your wallet's own token accounts. There is no
  transfer/withdraw code path.
* The secret key is read from a file (Docker secret), never from the DB,
  never logged, never returned by the API.
* The actual fill is read back from the confirmed transaction's balance
  changes, not assumed from the quote.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable

from ..chain.parser import compute_deltas
from ..chain.rpc import SolanaRpc
from ..config import Settings
from ..constants import SOL_DECIMALS, USDC_MINT, WSOL_MINT
from ..market.jupiter import Jupiter
from ..market.provider import MarketData
from ..schemas import ExecutionResult, Side

log = logging.getLogger(__name__)


class LiveTradingNotAuthorised(RuntimeError):
    pass


def load_keypair(path: str):
    from solders.keypair import Keypair

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Keypair.from_bytes(bytes(data))


class LiveExecutor:
    mode = "live"

    def __init__(self, settings: Settings, rpc: SolanaRpc, jup: Jupiter, market: MarketData,
                 is_armed: Callable[[], bool]):
        if not settings.live_execution_permitted:
            raise LiveTradingNotAuthorised(
                "live execution requires EXECUTION_MODE=live, LIVE_TRADING_ACK and WALLET_KEYPAIR_PATH")
        self._kp = load_keypair(settings.wallet_keypair_path)  # type: ignore[arg-type]
        self.pubkey = str(self._kp.pubkey())
        self.rpc, self.jup, self.market = rpc, jup, market
        self.is_armed = is_armed
        self.priority = settings.priority_fee_lamports
        self.funding_mint = USDC_MINT if settings.funding_mint == "USDC" else WSOL_MINT
        self.funding_decimals = 6 if settings.funding_mint == "USDC" else SOL_DECIMALS

    def _guard(self):
        if not self.is_armed():
            raise LiveTradingNotAuthorised("live trading is not armed")

    async def _swap(self, side: Side, in_mint: str, out_mint: str, in_raw: int, slippage_bps: int,
                    token_mint: str, token_decimals: int) -> ExecutionResult:
        self._guard()
        res = ExecutionResult(False, side, in_mint, out_mint, simulated=False)
        quote = await self.market.quote(in_mint, out_mint, in_raw, slippage_bps)
        if quote is None:
            res.error = "no route / quote"
            return res
        from solders.transaction import VersionedTransaction

        unsigned = VersionedTransaction.from_bytes(base64.b64decode(
            await self.jup.swap_transaction(quote, self.pubkey, self.priority)))
        signed = VersionedTransaction(unsigned.message, [self._kp])
        self._guard()  # re-check right before broadcasting
        sig = await self.rpc.send_raw_transaction(base64.b64encode(bytes(signed)).decode())
        res.signature = sig
        tx = await self._await_confirmation(sig)
        if tx is None:
            res.error = "not confirmed within timeout (may have expired)"
            return res
        if (tx.get("meta") or {}).get("err") is not None:
            res.error = f"on-chain error: {tx['meta']['err']}"
            return res
        deltas, fee_sol = compute_deltas(tx, self.pubkey)
        by_mint = {d.mint: d for d in deltas}
        sol_px = await self.market.price_usd(WSOL_MINT) or 0.0
        fund_px = await self.market.price_usd(self.funding_mint) or 0.0
        mid = await self.market.price_usd(token_mint) or 0.0
        tok, fund = by_mint.get(token_mint), by_mint.get(self.funding_mint)
        if not tok or not fund:
            res.error = "could not read fill from confirmed transaction"
            return res
        tok_ui, fund_ui = abs(tok.delta_ui), abs(fund.delta_ui)
        res.success = True
        res.network_fee_usd = fee_sol * sol_px
        if side == Side.BUY:
            res.in_amount_ui, res.out_amount_ui = fund_ui, tok_ui
            res.in_amount_raw, res.out_amount_raw = abs(fund.delta_raw), abs(tok.delta_raw)
            res.notional_usd = fund_ui * fund_px
            res.slippage_cost_usd = max(0.0, res.notional_usd - tok_ui * mid)
        else:
            res.in_amount_ui, res.out_amount_ui = tok_ui, fund_ui
            res.in_amount_raw, res.out_amount_raw = abs(tok.delta_raw), abs(fund.delta_raw)
            res.notional_usd = fund_ui * fund_px
            res.slippage_cost_usd = max(0.0, tok_ui * mid - res.notional_usd)
        res.price_usd = res.notional_usd / tok_ui if tok_ui else None
        return res

    async def _await_confirmation(self, sig: str, timeout: float = 75.0) -> dict | None:
        waited = 0.0
        while waited < timeout:
            st = (await self.rpc.get_signature_statuses([sig]) or [None])[0]
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return await self.rpc.get_transaction(sig)
            await asyncio.sleep(2)
            waited += 2
        return None

    async def buy(self, mint, decimals, usd_amount, slippage_bps) -> ExecutionResult:
        fund_px = await self.market.price_usd(self.funding_mint)
        if not fund_px:
            return ExecutionResult(False, Side.BUY, self.funding_mint, mint, simulated=False,
                                   error="funding price unavailable")
        in_raw = int(usd_amount / fund_px * 10 ** self.funding_decimals)
        return await self._swap(Side.BUY, self.funding_mint, mint, in_raw, slippage_bps, mint, decimals)

    async def sell(self, mint, decimals, amount_raw, slippage_bps) -> ExecutionResult:
        return await self._swap(Side.SELL, mint, self.funding_mint, amount_raw, slippage_bps, mint, decimals)

    async def wallet_token_balances(self) -> dict[str, int]:
        """Raw balances by mint, used by reconciliation."""
        from ..constants import TOKEN_2022_PROGRAM, TOKEN_PROGRAM

        out: dict[str, int] = {WSOL_MINT: await self.rpc.get_balance(self.pubkey)}
        for prog in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            for acc in await self.rpc.get_token_accounts_by_owner(self.pubkey, prog):
                info = acc["account"]["data"]["parsed"]["info"]
                out[info["mint"]] = out.get(info["mint"], 0) + int(info["tokenAmount"]["amount"])
        return out


