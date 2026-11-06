"""On-chain token contract checks via documented RPC methods."""
from __future__ import annotations

import logging

from ..chain.rpc import SolanaRpc
from ..constants import TOKEN_2022_PROGRAM
from ..schemas import TokenSafety

log = logging.getLogger(__name__)

# Token-2022 extensions that let a third party take or tax holder funds.
RISKY_EXTENSIONS = {"permanentDelegate", "transferFeeConfig", "transferHook", "defaultAccountState",
                    "nonTransferable", "pausableConfig"}


async def inspect_token(rpc: SolanaRpc, mint: str) -> TokenSafety:
    try:
        info = await rpc.get_account_info(mint)
        if not info:
            return TokenSafety(mint, None, None, None, None, None, error="mint account not found")
        program = info.get("owner")
        parsed = ((info.get("data") or {}).get("parsed") or {}).get("info") or {}
        exts = [e.get("extension") for e in parsed.get("extensions", []) if isinstance(e, dict)]
        top_pct = None
        try:
            largest = await rpc.get_token_largest_accounts(mint)
            supply = await rpc.get_token_supply(mint)
            total = float(supply.get("uiAmount") or 0)
            if total > 0:
                top = sum(float(a.get("uiAmount") or 0) for a in largest[:10])
                top_pct = 100.0 * top / total
        except Exception as e:  # noqa: BLE001 - holder data is best effort
            log.info("holder concentration unavailable for %s: %s", mint, e)
        return TokenSafety(
            mint=mint, decimals=parsed.get("decimals"), program=program,
            mint_authority=parsed.get("mintAuthority"), freeze_authority=parsed.get("freezeAuthority"),
            top10_holder_pct=top_pct, is_token_2022=(program == TOKEN_2022_PROGRAM),
            risky_extensions=[e for e in exts if e in RISKY_EXTENSIONS],
        )
    except Exception as e:  # noqa: BLE001
        return TokenSafety(mint, None, None, None, None, None, error=str(e))
