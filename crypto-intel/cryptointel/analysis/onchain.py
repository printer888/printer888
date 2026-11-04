"""On-chain data.

Free & reliable: aggregate stablecoin supply (DefiLlama).
Exchange flows, whale transactions, wallet concentration and token distribution
require paid data (Glassnode, CryptoQuant, Nansen, Whale Alert). Those providers are
exposed as explicit "unavailable" results until credentials are configured —
the system never invents values for them.
"""
from __future__ import annotations

import logging
import os

import httpx
import pandas as pd

from ..data.freshness import Stamped

log = logging.getLogger(__name__)

DEFILLAMA_STABLES = "https://stablecoins.llama.fi/stablecoincharts/all"

PAID_METRICS = {
    "exchange_flows": ("GLASSNODE_API_KEY", "Glassnode / CryptoQuant"),
    "whale_transactions": ("WHALE_ALERT_API_KEY", "Whale Alert"),
    "wallet_concentration": ("GLASSNODE_API_KEY", "Glassnode / Nansen"),
    "network_activity": ("GLASSNODE_API_KEY", "Glassnode"),
}


def fetch_stablecoin_supply(client: httpx.Client | None = None) -> Stamped[pd.Series] | None:
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        r = client.get(DEFILLAMA_STABLES)
        r.raise_for_status()
        rows = r.json()
        s = pd.Series(
            [float(x["totalCirculatingUSD"]["peggedUSD"]) for x in rows],
            index=pd.to_datetime([int(x["date"]) for x in rows], unit="s", utc=True),
            name="stablecoin_supply_usd",
        ).sort_index()
        if s.empty:
            return None
        return Stamped(s, "DefiLlama stablecoins (USD-pegged circulating)", s.index[-1].to_pydatetime())
    except Exception as e:
        log.warning("Stablecoin supply fetch failed: %s", e)
        return None
    finally:
        if own:
            client.close()


def analyze_onchain(stables: Stamped[pd.Series] | None) -> dict:
    out: dict = {"metrics": {}, "unavailable": {}}
    if stables is not None and len(stables.value) > 31 and not stables.is_stale(3 * 86400):
        s = stables.value
        ch7 = float((s.iloc[-1] / s.iloc[-8] - 1) * 100)
        ch30 = float((s.iloc[-1] / s.iloc[-31] - 1) * 100)
        out["metrics"]["stablecoin_supply"] = {
            "value_usd": float(s.iloc[-1]), "change_7d_pct": ch7, "change_30d_pct": ch30,
            "as_of": stables.as_of.isoformat(), "age": stables.describe_age(), "source": stables.source,
            "interpretation": (
                "expanding stablecoin supply = more dry powder entering crypto (supportive liquidity backdrop)"
                if ch30 > 1 else
                "contracting stablecoin supply = liquidity leaving crypto (headwind)"
                if ch30 < -1 else "stablecoin supply roughly flat"
            ),
        }
    else:
        out["unavailable"]["stablecoin_supply"] = "fetch failed or data stale"
    for metric, (env, provider) in PAID_METRICS.items():
        if not os.environ.get(env):
            out["unavailable"][metric] = f"requires {provider} API ({env} not configured)"
    return out
