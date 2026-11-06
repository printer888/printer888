"""DexScreener public API (documented at https://docs.dexscreener.com/api/reference)."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..schemas import TokenMarket


class DexScreener:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10)

    async def token_market(self, mint: str) -> TokenMarket | None:
        r = await self._client.get(f"{self.base_url}/tokens/v1/solana/{mint}")
        r.raise_for_status()
        pairs = r.json() or []
        return best_pair(mint, pairs)


def best_pair(mint: str, pairs: list[dict]) -> TokenMarket | None:
    """Choose the deepest pool in which ``mint`` is the base token."""
    own = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not own:
        return None
    p = max(own, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
    created = p.get("pairCreatedAt")
    return TokenMarket(
        mint=mint,
        symbol=(p.get("baseToken") or {}).get("symbol"),
        price_usd=float(p["priceUsd"]) if p.get("priceUsd") else None,
        liquidity_usd=float((p.get("liquidity") or {}).get("usd") or 0),
        volume_24h_usd=float((p.get("volume") or {}).get("h24") or 0),
        pair_address=p.get("pairAddress"),
        dex=p.get("dexId"),
        pair_created_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None,
        price_change_h1_pct=(p.get("priceChange") or {}).get("h1"),
    )
