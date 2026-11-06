# Step 1 — FOMO integration investigation

_Researched November 2026. Re-check before going live; the platform may change._

## Findings

| Question | Finding |
|---|---|
| Does FOMO (fomo.family, FOMO Labs Inc.) publish a developer API? | **No.** No public API, SDK, WebSocket feed or API docs are published. API directories (API Evangelist) and Bitquery's FOMO page both state this. |
| Is there an official copy-trading feature or API? | **No.** FOMO is *social* trading: you see what others trade and decide yourself. Reviewers stress it is not automated copy trading. |
| How are FOMO accounts held? | Each account gets a **self-custodial wallet created through Privy** (embedded wallet). Trades settle **on-chain** (Solana). |
| Third-party "Fomo API" services (e.g. getfomoapi.fun) | Exist, but are **unofficial**: independent services scraping/indexing FOMO data, with their own rate limits and an explicit warning that data may be delayed or inaccurate. |
| Unofficial MCP servers / scripts using `prod-api.fomo.family` | They re-use the session token from a logged-in browser against **undocumented internal endpoints**. That is not a supported integration: it can break at any time, may breach FOMO's terms, and requires handing over your session credentials. **Not used.** |
| Can the selected trader be monitored reliably? | **Yes, legitimately, via the blockchain.** A FOMO trader's wallet address is public, and every trade they make is a public Solana transaction. Standard Solana RPC (`logsSubscribe`, `getSignaturesForAddress`, `getTransaction`) gives every confirmed transaction with validator-computed balance changes. |
| Can trades be executed on my FOMO account? | **Not through any supported method.** FOMO's Privy wallet can only be signed through FOMO's app. Automating it would mean reverse-engineering their private API or extracting the embedded wallet key, and neither is supported. |

## Decision: legitimate alternative

1. **Monitoring:** read the trader's public Solana wallet directly from the chain. This uses documented
   Solana JSON-RPC methods only. Websocket push plus polling fallback; transactions are verified by fetching
   them at `confirmed` commitment.
2. **Trade detection:** protocol-agnostic. The bot diffs the trader wallet's `pre/postTokenBalances` and
   `pre/postBalances`, so it works no matter which DEX or aggregator FOMO routes through.
3. **Market data:** DexScreener public API (liquidity, volume, pool age) and Jupiter Price API.
4. **Execution (disabled by default):** Jupiter Swap API (public, documented). It builds a swap that you sign
   with a **dedicated hot wallet you control**, not your FOMO wallet. Fund it only with the capital
   you allocate to copying. The key needs no withdrawal permission, and the code has no transfer path.
5. **Your FOMO account:** keep using it manually. Copied positions live in the dedicated wallet. You can
   import that wallet into any Solana wallet app to see or manage it.

## Residual limitations (stated plainly)

* **Latency.** A copy lands after the trader's transaction: detection takes ~1–5 s with a good RPC provider, plus
  execution. For fast-moving memecoins the price can differ materially, so the risk engine rejects copies whose price
  has drifted too far.
* **Exit prices cannot be replicated.** When the trader sells into thin liquidity first, our exit is worse.
* **Hidden intent.** A trader may move tokens to another wallet and sell there. Transfers are detected and alerted, but
  not treated as sells. Independent stop-loss rules cover this case.
* **History pricing.** USD values of historical SOL-quoted trades use the current SOL price (historical prices are not on-chain).
* **Chain coverage.** Only Solana is implemented. If FOMO trades a token on another chain (e.g. an EVM chain), an equivalent
  chain adapter would be needed.

## Sources
* API Evangelist provider listing for fomo — https://providers.apievangelist.com/providers/fomo/
* Bitquery, "FOMO API" (on-chain Solana data, not affiliated) — https://docs.bitquery.io/docs/blockchain/Solana/fomo-api/
* Datawallet, "Fomo app explained" (Privy wallet, social trading) — https://www.datawallet.com/de/krypto/fomo-app-explained
* DEV Community guides on the unofficial "Fomo API" — https://dev.to/voren_tai_24467d3051ef996/what-is-the-fomo-api-a-guide-to-programmatic-access-2nkd
* Glama MCP listing using internal endpoints — https://glama.ai/mcp/servers/ColinEdw/fomo-mcp/schema
* Solana RPC docs — https://solana.com/docs/rpc · Jupiter docs — https://dev.jup.ag/docs · DexScreener API — https://docs.dexscreener.com/api/reference
