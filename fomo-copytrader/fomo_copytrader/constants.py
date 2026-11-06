"""Well-known Solana addresses. These are public, canonical program/mint IDs."""

WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

# Assets we treat as the "quote" side of a swap. Anything else gained/lost is
# treated as the traded token.
QUOTE_MINTS = {WSOL_MINT, USDC_MINT, USDT_MINT}
STABLE_MINTS = {USDC_MINT, USDT_MINT}

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

LAMPORTS_PER_SOL = 1_000_000_000
SOL_DECIMALS = 9
