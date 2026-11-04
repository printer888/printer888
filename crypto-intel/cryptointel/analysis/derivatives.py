"""Derivatives-market analysis: funding, open interest, positioning, orderbook, liquidations.

Interpretations are *conditional observations*, not predictions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Funding thresholds per 8h interval (Bybit default interval). Rates are scaled for
# symbols with different funding intervals.
FUNDING_CROWDED_LONG = 0.0005   # 0.05% / 8h  (~55% annualised)
FUNDING_CROWDED_SHORT = -0.0003  # -0.03% / 8h


@dataclass
class DerivativesReport:
    available: dict[str, bool] = field(default_factory=dict)
    funding_rate: float | None = None
    funding_8h_equiv: float | None = None
    funding_percentile: float | None = None
    funding_annualised_pct: float | None = None
    oi_change_pct: dict[str, float] = field(default_factory=dict)
    price_change_pct: dict[str, float] = field(default_factory=dict)
    oi_regime: str | None = None
    long_short_ratio: float | None = None
    orderbook: dict = field(default_factory=dict)
    liquidations: dict = field(default_factory=dict)
    trade_flow: dict = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    long_supportive: list[str] = field(default_factory=list)
    short_supportive: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def orderbook_metrics(book: dict, bands_pct: tuple[float, ...] = (0.5, 1.0)) -> dict:
    bids, asks = book.get("bids") or [], book.get("asks") or []
    if not bids or not asks:
        return {"available": False}
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2
    out = {"available": True, "mid": mid, "spread_bps": (best_ask - best_bid) / mid * 1e4}
    deepest_bid, deepest_ask = bids[-1][0], asks[-1][0]
    for b in bands_pct:
        lo, hi = mid * (1 - b / 100), mid * (1 + b / 100)
        bid_usd = sum(p * q for p, q in bids if p >= lo)
        ask_usd = sum(p * q for p, q in asks if p <= hi)
        tot = bid_usd + ask_usd
        key = str(b).replace(".", "_")
        out[f"bid_depth_usd_{key}"] = bid_usd
        out[f"ask_depth_usd_{key}"] = ask_usd
        out[f"imbalance_{key}"] = (bid_usd - ask_usd) / tot if tot else None
        # The 50-level book may not reach the band; mark coverage explicitly.
        out[f"band_covered_{key}"] = deepest_bid <= lo and deepest_ask >= hi
    return out


def _pct_change_over(s: pd.Series, hours: int) -> float | None:
    if s is None or s.empty:
        return None
    end = s.index[-1]
    past = s[s.index <= end - pd.Timedelta(hours=hours)]
    if past.empty or past.iloc[-1] == 0:
        return None
    return float((s.iloc[-1] / past.iloc[-1] - 1) * 100)


def analyze_derivatives(
    *,
    ticker: dict | None,
    funding_hist: pd.Series | None,
    funding_interval_minutes: int = 480,
    open_interest: pd.Series | None,
    price: pd.Series | None,
    ls_ratio: pd.DataFrame | None,
    book: dict | None,
    liquidations: dict | None = None,
    trade_flow: dict | None = None,
) -> DerivativesReport:
    r = DerivativesReport()
    obs, L, S, W = r.observations, r.long_supportive, r.short_supportive, r.warnings

    # ---- funding
    fr = ticker.get("funding_rate") if ticker else None
    r.available["funding"] = fr is not None and np.isfinite(fr)
    if r.available["funding"]:
        scale = 480 / max(funding_interval_minutes, 1)
        r.funding_rate = fr
        r.funding_8h_equiv = fr * scale
        r.funding_annualised_pct = fr * (525_600 / funding_interval_minutes) * 100
        if funding_hist is not None and len(funding_hist) >= 30:
            r.funding_percentile = float((funding_hist < fr).mean() * 100)
        f8 = r.funding_8h_equiv
        txt = f"funding {fr * 100:.4f}% per {funding_interval_minutes // 60}h (~{r.funding_annualised_pct:.1f}%/yr)"
        if f8 >= FUNDING_CROWDED_LONG:
            W.append(txt + " — longs crowded/paying heavily; long-squeeze risk")
            S.append("elevated positive funding (contrarian: crowded longs)")
        elif f8 <= FUNDING_CROWDED_SHORT:
            W.append(txt + " — shorts crowded; short-squeeze risk")
            L.append("negative funding (contrarian: crowded shorts)")
        else:
            obs.append(txt + " — neutral range")
            L.append("funding not crowded on the long side")
            S.append("funding not crowded on the short side")

    # ---- open interest vs price
    r.available["open_interest"] = open_interest is not None and len(open_interest) >= 5
    if r.available["open_interest"] and price is not None and len(price):
        for h in (4, 24):
            oi_c, px_c = _pct_change_over(open_interest, h), _pct_change_over(price, h)
            if oi_c is not None:
                r.oi_change_pct[f"{h}h"] = oi_c
            if px_c is not None:
                r.price_change_pct[f"{h}h"] = px_c
        oi4, px4 = r.oi_change_pct.get("4h"), r.price_change_pct.get("4h")
        if oi4 is not None and px4 is not None:
            if oi4 > 2 and px4 > 0.5:
                r.oi_regime = "new_longs"
                L.append(f"OI +{oi4:.1f}% with price +{px4:.1f}% (4h): new positions supporting the advance")
            elif oi4 > 2 and px4 < -0.5:
                r.oi_regime = "new_shorts"
                S.append(f"OI +{oi4:.1f}% with price {px4:.1f}% (4h): new shorts pressing the decline")
            elif oi4 < -2 and px4 > 0.5:
                r.oi_regime = "short_covering"
                obs.append(f"OI {oi4:.1f}% while price +{px4:.1f}%: rally driven by short covering (often less durable)")
            elif oi4 < -2 and px4 < -0.5:
                r.oi_regime = "long_liquidation"
                obs.append(f"OI {oi4:.1f}% while price {px4:.1f}%: longs closing/liquidated (deleveraging)")
            else:
                r.oi_regime = "neutral"
            if oi4 > 8 and abs(px4) > 3:
                W.append(f"OI rising sharply (+{oi4:.1f}%) during a {px4:+.1f}% move — leverage building, "
                         "elevated risk of a violent reversal/liquidation cascade")

    # ---- long/short account ratio
    r.available["long_short"] = ls_ratio is not None and not ls_ratio.empty
    if r.available["long_short"]:
        buy = float(ls_ratio["buy_ratio"].iloc[-1])
        sell = float(ls_ratio["sell_ratio"].iloc[-1])
        r.long_short_ratio = buy / sell if sell else None
        if r.long_short_ratio is not None:
            txt = f"account long/short ratio {r.long_short_ratio:.2f} ({buy * 100:.0f}% long)"
            if r.long_short_ratio >= 2.5:
                W.append(txt + " — retail heavily long (crowding)")
                S.append("crowded long accounts (contrarian)")
            elif r.long_short_ratio <= 0.7:
                W.append(txt + " — retail heavily short (crowding)")
                L.append("crowded short accounts (contrarian)")
            else:
                obs.append(txt)

    # ---- orderbook
    if book:
        ob = orderbook_metrics(book)
        r.orderbook = ob
        r.available["orderbook"] = ob.get("available", False)
        imb = ob.get("imbalance_0_5")
        if imb is not None:
            txt = f"orderbook imbalance ±0.5%: {imb:+.2f}"
            if imb > 0.25:
                L.append(txt + " (bid-heavy)")
            elif imb < -0.25:
                S.append(txt + " (ask-heavy)")
            else:
                obs.append(txt + " (balanced)")
            obs.append("note: visible book can be spoofed/pulled; imbalance is weak evidence")
    else:
        r.available["orderbook"] = False

    # ---- liquidations (WebSocket-derived; incomplete until the window is fully observed)
    r.available["liquidations"] = bool(liquidations and liquidations.get("complete"))
    if liquidations:
        r.liquidations = liquidations
        if liquidations.get("complete"):
            ll, sl = liquidations["long_liquidations_usd"], liquidations["short_liquidations_usd"]
            if ll + sl > 0:
                obs.append(f"liquidations (last {liquidations['lookback_seconds'] // 60}m): "
                           f"longs ${ll:,.0f} / shorts ${sl:,.0f}")
        else:
            obs.append("liquidation stream warming up — not used")

    r.available["trade_flow"] = bool(trade_flow and trade_flow.get("complete") and trade_flow.get("n_trades", 0) > 50)
    if trade_flow:
        r.trade_flow = trade_flow
        if r.available["trade_flow"] and trade_flow.get("delta_ratio") is not None:
            d = trade_flow["delta_ratio"]
            txt = f"aggressor volume delta {d:+.2f} ({trade_flow['n_trades']} trades)"
            if d > 0.15:
                L.append(txt + " — net market buying")
            elif d < -0.15:
                S.append(txt + " — net market selling")
            else:
                obs.append(txt)
    return r
