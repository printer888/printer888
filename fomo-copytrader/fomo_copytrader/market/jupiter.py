"""Jupiter Swap / Price API (documented at https://dev.jup.ag/docs).

Quotes are used for two things: as a real, executable measure of market depth
(price impact for *our* size) and, in live mode, to build the swap transaction.
"""
from __future__ import annotations

import httpx

from ..schemas import Quote


class Jupiter:
    def __init__(self, base_url: str, api_key: str | None = None, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        headers = {"x-api-key": api_key} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=10, headers=headers)

    async def quote(self, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int) -> Quote:
        r = await self._client.get(f"{self.base_url}/swap/v1/quote", params={
            "inputMint": input_mint, "outputMint": output_mint,
            "amount": str(int(amount_raw)), "slippageBps": slippage_bps,
        })
        r.raise_for_status()
        q = r.json()
        return Quote(
            input_mint=input_mint, output_mint=output_mint,
            in_amount_raw=int(q["inAmount"]), out_amount_raw=int(q["outAmount"]),
            price_impact_pct=abs(float(q.get("priceImpactPct") or 0)) * 100,
            slippage_bps=int(q.get("slippageBps", slippage_bps)),
            route_labels=[(s.get("swapInfo") or {}).get("label", "?") for s in q.get("routePlan", [])],
            raw=q,
        )

    async def swap_transaction(self, quote: Quote, user_pubkey: str, priority_fee_lamports: int) -> str:
        """Return a base64 serialized, unsigned VersionedTransaction."""
        r = await self._client.post(f"{self.base_url}/swap/v1/swap", json={
            "quoteResponse": quote.raw,
            "userPublicKey": user_pubkey,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": priority_fee_lamports,
        })
        r.raise_for_status()
        return r.json()["swapTransaction"]

    async def prices_usd(self, mints: list[str]) -> dict[str, float]:
        if not mints:
            return {}
        r = await self._client.get(f"{self.base_url}/price/v3", params={"ids": ",".join(mints)})
        r.raise_for_status()
        out: dict[str, float] = {}
        for mint, v in (r.json() or {}).items():
            if v and v.get("usdPrice") is not None:
                out[mint] = float(v["usdPrice"])
        return out
