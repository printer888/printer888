"""Minimal async Solana JSON-RPC client (documented methods only).

https://solana.com/docs/rpc
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class RpcError(RuntimeError):
    pass


class SolanaRpc:
    def __init__(self, url: str, timeout: float = 15.0, max_retries: int = 4,
                 client: httpx.AsyncClient | None = None):
        self.url = url
        self.max_retries = max_retries
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._ids = itertools.count(1)

    async def close(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, params: list | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or []}
        delay = 0.5
        for attempt in range(self.max_retries + 1):
            try:
                r = await self._client.post(self.url, json=payload)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                body = r.json()
                if "error" in body:
                    raise RpcError(f"{method}: {body['error']}")
                return body.get("result")
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if attempt == self.max_retries:
                    raise RpcError(f"{method} failed after retries: {e}") from e
                log.warning("RPC %s attempt %d failed: %s", method, attempt + 1, e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8)

    # --- documented RPC methods -------------------------------------------
    async def get_signatures_for_address(self, address: str, limit: int = 100,
                                         before: str | None = None, until: str | None = None,
                                         commitment: str = "confirmed") -> list[dict]:
        cfg: dict[str, Any] = {"limit": limit, "commitment": commitment}
        if before:
            cfg["before"] = before
        if until:
            cfg["until"] = until
        return await self.call("getSignaturesForAddress", [address, cfg]) or []

    async def get_transaction(self, signature: str, commitment: str = "confirmed") -> dict | None:
        return await self.call("getTransaction", [signature, {
            "encoding": "jsonParsed", "commitment": commitment, "maxSupportedTransactionVersion": 0}])

    async def get_account_info(self, address: str) -> dict | None:
        res = await self.call("getAccountInfo", [address, {"encoding": "jsonParsed"}])
        return (res or {}).get("value")

    async def get_token_largest_accounts(self, mint: str) -> list[dict]:
        res = await self.call("getTokenLargestAccounts", [mint])
        return (res or {}).get("value", [])

    async def get_token_supply(self, mint: str) -> dict:
        res = await self.call("getTokenSupply", [mint])
        return (res or {}).get("value", {})

    async def get_balance(self, address: str) -> int:
        res = await self.call("getBalance", [address])
        return int((res or {}).get("value", 0))

    async def get_token_accounts_by_owner(self, owner: str, program_id: str) -> list[dict]:
        res = await self.call("getTokenAccountsByOwner", [owner, {"programId": program_id},
                                                          {"encoding": "jsonParsed"}])
        return (res or {}).get("value", [])

    async def get_signature_statuses(self, sigs: list[str]) -> list[dict | None]:
        res = await self.call("getSignatureStatuses", [sigs, {"searchTransactionHistory": True}])
        return (res or {}).get("value", [])

    async def send_raw_transaction(self, b64_tx: str) -> str:
        return await self.call("sendTransaction", [b64_tx, {
            "encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed", "maxRetries": 3}])
