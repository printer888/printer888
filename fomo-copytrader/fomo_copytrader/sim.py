"""Simulation toolkit: realistic getTransaction payload builders, a deterministic market and a fake RPC.

Used by the test-suite and by `python -m fomo_copytrader.cli simulate`. Never used in live mode.
"""
from __future__ import annotations

import itertools
import time
from datetime import datetime, timezone

from fomo_copytrader.constants import USDC_MINT, WSOL_MINT
from fomo_copytrader.schemas import Quote, TokenMarket, TokenSafety

TRADER = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
OTHER = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
TOKEN = "BONKmintXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"[:44]
TOKEN2 = "WIFmintYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY"[:44]
_sig = itertools.count(1)


def sig() -> str:
    return f"sig{next(_sig):06d}" + "x" * 80


def tb(idx: int, mint: str, owner: str, raw: int, decimals: int) -> dict:
    return {"accountIndex": idx, "mint": mint, "owner": owner,
            "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "uiTokenAmount": {"amount": str(raw), "decimals": decimals,
                              "uiAmount": raw / 10 ** decimals, "uiAmountString": str(raw / 10 ** decimals)}}


def make_tx(*, wallet: str = TRADER, signature: str | None = None, sol_pre: int = 10_000_000_000,
            sol_post: int | None = None, fee: int = 5000, tokens: list[tuple[str, int, int | None, int | None]] = (),
            err=None, block_time: float | None = None, slot: int = 300_000_000, fee_payer: bool = True,
            encoding: str = "jsonParsed") -> dict:
    """tokens: (mint, decimals, pre_raw|None, post_raw|None) for the wallet's accounts."""
    signature = signature or sig()
    sol_post = sol_pre - fee if sol_post is None else sol_post
    keys = [wallet, POOL] if fee_payer else [OTHER, wallet, POOL]
    wi = keys.index(wallet)
    pre_bal = [0] * len(keys)
    post_bal = [0] * len(keys)
    pre_bal[wi], post_bal[wi] = sol_pre, sol_post
    pre_tb, post_tb = [], []
    for n, (mint, dec, pre, post) in enumerate(tokens):
        if pre is not None:
            pre_tb.append(tb(10 + n, mint, wallet, pre, dec))
        if post is not None:
            post_tb.append(tb(10 + n, mint, wallet, post, dec))
        # pool side moves opposite (owned by someone else, must be ignored)
        pre_tb.append(tb(20 + n, mint, POOL, 10**15, dec))
        post_tb.append(tb(20 + n, mint, POOL, 10**15 - ((post or 0) - (pre or 0)), dec))
    if encoding == "jsonParsed":
        account_keys = [{"pubkey": k, "signer": i == 0, "writable": True, "source": "transaction"}
                        for i, k in enumerate(keys)]
    else:
        account_keys = keys
    return {
        "slot": slot, "blockTime": int(block_time or time.time()),
        "meta": {"err": err, "fee": fee, "preBalances": pre_bal, "postBalances": post_bal,
                 "preTokenBalances": pre_tb, "postTokenBalances": post_tb, "logMessages": []},
        "transaction": {"signatures": [signature], "message": {"accountKeys": account_keys, "instructions": []}},
        "version": 0,
    }


def buy_with_sol(sol_spent: float, tokens_out: int, decimals: int = 6, mint: str = TOKEN, pre_tokens: int | None = None,
                 **kw) -> dict:
    lam = int(sol_spent * 1e9)
    return make_tx(sol_pre=10_000_000_000, sol_post=10_000_000_000 - lam - 5000,
                   tokens=[(mint, decimals, pre_tokens, (pre_tokens or 0) + tokens_out)], **kw)


def sell_for_sol(sol_received: float, pre_tokens: int, tokens_in: int, decimals: int = 6, mint: str = TOKEN, **kw) -> dict:
    lam = int(sol_received * 1e9)
    return make_tx(sol_pre=5_000_000_000, sol_post=5_000_000_000 + lam - 5000,
                   tokens=[(mint, decimals, pre_tokens, pre_tokens - tokens_in)], **kw)


class FakeMarket:
    """Deterministic market: price impact ~ trade size / pool depth (constant product, small trades)."""

    def __init__(self):
        self.prices = {WSOL_MINT: 150.0, USDC_MINT: 1.0}
        self.markets: dict[str, TokenMarket] = {}
        self.decimals = {WSOL_MINT: 9, USDC_MINT: 6}
        self.quote_fail: set[str] = set()

    def add_token(self, mint: str, price: float, liquidity: float = 500_000, volume: float = 2_000_000,
                  decimals: int = 6, symbol: str = "TKN", age_hours: float = 48):
        self.prices[mint] = price
        self.decimals[mint] = decimals
        self.markets[mint] = TokenMarket(mint, symbol, price, liquidity, volume, "pair", "raydium",
                                         datetime.fromtimestamp(time.time() - age_hours * 3600, tz=timezone.utc))

    def set_price(self, mint: str, price: float):
        self.prices[mint] = price
        if mint in self.markets:
            self.markets[mint].price_usd = price

    async def token_market(self, mint):
        return self.markets.get(mint)

    async def price_usd(self, mint):
        return self.prices.get(mint)

    async def quote(self, input_mint, output_mint, amount_raw, slippage_bps):
        if input_mint in self.quote_fail or output_mint in self.quote_fail:
            return None
        in_usd = amount_raw / 10 ** self.decimals[input_mint] * self.prices[input_mint]
        tok = output_mint if input_mint in (USDC_MINT, WSOL_MINT) else input_mint
        liq = self.markets[tok].liquidity_usd if tok in self.markets else 1e9
        impact = in_usd / (liq / 2)
        out_usd = in_usd * (1 - impact)
        out_raw = int(out_usd / self.prices[output_mint] * 10 ** self.decimals[output_mint])
        return Quote(input_mint, output_mint, amount_raw, out_raw, impact * 100, slippage_bps)


def safe_token(mint: str) -> TokenSafety:
    return TokenSafety(mint, 6, "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", None, None, 25.0)


class FakeRpc:
    def __init__(self):
        self.txs: dict[str, dict] = {}
        self.order: list[str] = []  # oldest -> newest
        self.missing_once: set[str] = set()

    def push(self, tx: dict) -> str:
        s = tx["transaction"]["signatures"][0]
        self.txs[s] = tx
        self.order.append(s)
        return s

    async def get_signatures_for_address(self, address, limit=100, before=None, until=None, commitment="confirmed"):
        newest_first = list(reversed(self.order))
        if before:
            newest_first = newest_first[newest_first.index(before) + 1:]
        out = []
        for s in newest_first:
            if s == until:
                break
            out.append({"signature": s, "err": self.txs[s]["meta"]["err"]})
        return out[:limit]

    async def get_transaction(self, signature, commitment="confirmed"):
        if signature in self.missing_once:
            self.missing_once.discard(signature)
            return None
        return self.txs.get(signature)

    async def get_signature_statuses(self, sigs):
        return [None for _ in sigs]
