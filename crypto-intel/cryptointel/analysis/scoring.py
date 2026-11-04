"""Transparent multi-factor scoring (0–100) for a long or short scenario.

Category budget:
  Technical conditions        25
  Market structure            20
  Volume & liquidity          15
  Derivatives data            15
  News & macro conditions     15
  Sentiment & on-chain        10

Every component reports points, its maximum, whether its data was available and a
plain-language evidence line. Unavailable or stale data scores ZERO points and is
listed under `missing` — absence of data is never treated as supportive evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .derivatives import FUNDING_CROWDED_LONG, FUNDING_CROWDED_SHORT, DerivativesReport
from .sentiment import SentimentReport
from .timeframe import TimeframeAnalysis

HIGHER_TFS = {"15m": ["1h", "4h"], "1h": ["4h", "1d"], "4h": ["1d", "1w"], "1d": ["1w"]}
TRIGGER_TF = {"1h": "15m", "4h": "1h", "15m": "5m", "1d": "4h"}


@dataclass
class Component:
    name: str
    points: float
    max_points: float
    available: bool
    evidence: str

    def to_dict(self) -> dict:
        return {"name": self.name, "points": round(self.points, 2), "max": self.max_points,
                "available": self.available, "evidence": self.evidence}


@dataclass
class CategoryScore:
    name: str
    max_points: float
    components: list[Component] = field(default_factory=list)

    @property
    def points(self) -> float:
        return min(sum(c.points for c in self.components), self.max_points)

    def add(self, name: str, points: float, max_points: float, available: bool, evidence: str) -> None:
        pts = float(np.clip(points, 0, max_points)) if available else 0.0
        self.components.append(Component(name, pts, max_points, available, evidence))

    def to_dict(self) -> dict:
        return {"name": self.name, "points": round(self.points, 2), "max": self.max_points,
                "components": [c.to_dict() for c in self.components]}


@dataclass
class ScoreCard:
    direction: str
    categories: dict[str, CategoryScore]

    @property
    def total(self) -> float:
        return round(sum(c.points for c in self.categories.values()), 1)

    @property
    def missing(self) -> list[str]:
        return [f"{cat.name}: {c.name}" for cat in self.categories.values() for c in cat.components if not c.available]

    def points(self, key: str) -> float:
        return self.categories[key].points

    def explanation(self) -> list[str]:
        lines = [f"{self.direction.upper()} score {self.total}/100"]
        for cat in self.categories.values():
            lines.append(f"• {cat.name}: {cat.points:.1f}/{cat.max_points:g}")
            for c in cat.components:
                flag = "" if c.available else " [DATA MISSING → 0]"
                lines.append(f"    – {c.name} {c.points:.1f}/{c.max_points:g}: {c.evidence}{flag}")
        return lines

    def to_dict(self) -> dict:
        return {"direction": self.direction, "total": self.total,
                "categories": {k: v.to_dict() for k, v in self.categories.items()},
                "missing": self.missing}


@dataclass
class ScoringInputs:
    timeframes: dict[str, TimeframeAnalysis]
    primary_tf: str
    derivatives: DerivativesReport | None
    liquidity: dict  # turnover_24h, spread_bps
    news: dict | None  # asset_news_assessment(...) or None when feeds unavailable
    calendar_risk: dict | None  # Calendar.event_risk(...) or None
    sentiment: SentimentReport | None
    onchain: dict | None
    ml: dict | None = None
    use_ml: bool = False


def _usable(tfa: TimeframeAnalysis | None) -> bool:
    return tfa is not None and tfa.sufficient and not tfa.stale


def _clip01(x: float) -> float:
    return float(np.clip(x, 0, 1))


def score(inp: ScoringInputs, direction: str) -> ScoreCard:
    d = 1 if direction == "long" else -1
    word = "bullish" if d > 0 else "bearish"
    cats = {
        "technical": CategoryScore("Technical conditions", 25),
        "structure": CategoryScore("Market structure", 20),
        "liquidity": CategoryScore("Volume & liquidity", 15),
        "derivatives": CategoryScore("Derivatives data", 15),
        "news_macro": CategoryScore("News & macro", 15),
        "sentiment": CategoryScore("Sentiment & on-chain", 10),
    }
    tfs = inp.timeframes
    p = tfs.get(inp.primary_tf)
    p_ok = _usable(p)
    s = p.snapshot if p_ok else {}
    highers = HIGHER_TFS.get(inp.primary_tf, [])
    trig = tfs.get(TRIGGER_TF.get(inp.primary_tf, ""))

    # ------------------------------------------------------------ technical (25)
    T = cats["technical"]
    T.add(f"{inp.primary_tf} trend", 5 * _clip01(d * p.bias / 0.7) if p_ok else 0, 5, p_ok,
          f"{inp.primary_tf} trend {p.trend} (bias {p.bias:+.2f})" if p_ok else "primary timeframe unavailable/stale")
    for tf in highers:
        h = tfs.get(tf)
        ok = _usable(h)
        T.add(f"{tf} trend alignment", 2.5 * _clip01(d * h.bias / 0.7) if ok else 0, 2.5, ok,
              f"{tf} trend {h.trend} (bias {h.bias:+.2f})" if ok else f"{tf} data unavailable/stale")
    mom_max = 5.0 if (inp.use_ml and inp.ml and inp.ml.get("validated")) else 8.0
    if p_ok and s.get("rsi") is not None:
        r = s["rsi"]
        rsi_pts = (3 if 50 <= r < 70 else 1 if 70 <= r < 75 else 0) if d > 0 else \
                  (3 if 30 < r <= 50 else 1 if 25 < r <= 30 else 0)
        macd_pts = 2 if s.get("macd_hist") is not None and d * s["macd_hist"] > 0 else 0
        k, dd = s.get("stochrsi_k"), s.get("stochrsi_d")
        st_pts = 1.5 if k is not None and dd is not None and (
            (d > 0 and k > dd and k < 80) or (d < 0 and k < dd and k > 20)) else 0
        roc_pts = 1.5 if s.get("roc") is not None and d * s["roc"] > 0 else 0
        pts = (rsi_pts + macd_pts + st_pts + roc_pts) * mom_max / 8
        k_txt = f"{k:.0f}" if k is not None else "n/a"
        T.add("momentum", pts, mom_max, True,
              f"RSI {r:.0f}, MACD hist {s.get('macd_hist') or 0:+.4g}, StochRSI K {k_txt}, ROC {s.get('roc') or 0:+.2f}%")
    else:
        T.add("momentum", 0, mom_max, False, "momentum indicators unavailable")
    if mom_max < 8:
        prob = inp.ml.get("prob_up", 0.5)
        edge = (prob - 0.5) * d
        T.add("ML model (validated out-of-sample)", 3 * _clip01(edge / 0.1), 3, True,
              f"P(up)={prob:.2f}; OOS AUC {inp.ml.get('oos_auc', float('nan')):.3f}")
    if p_ok:
        reg = p.volatility_regime
        vol_pts = {"normal": 2, "low": 1, "high": 0}.get(reg, 0)
        pb = s.get("bb_pct_b")
        stretch_ok = pb is not None and ((d > 0 and pb < 1.05) or (d < 0 and pb > -0.05))
        T.add("volatility conditions", vol_pts + (2 if stretch_ok else 0), 4, reg != "unknown",
              f"volatility regime {reg}; Bollinger %B {pb if pb is None else round(pb, 2)}"
              + ("" if stretch_ok else " (stretched beyond band — chase risk)"))
        obv_ok = s.get("obv_slope") is not None and d * s["obv_slope"] > 0
        vwap_ok = s.get("vwap") is not None and d * (s["close"] - s["vwap"]) > 0
        T.add("volume confirmation", 1.5 * obv_ok + 1.5 * vwap_ok, 3, True,
              f"OBV slope {'aligned' if obv_ok else 'not aligned'}; price {'on the right side of' if vwap_ok else 'against'} VWAP")
    else:
        T.add("volatility conditions", 0, 4, False, "primary timeframe unavailable")
        T.add("volume confirmation", 0, 3, False, "primary timeframe unavailable")

    # ------------------------------------------------------------ structure (20)
    S = cats["structure"]
    if p_ok:
        st = p.structure.get("trend")
        S.add(f"{inp.primary_tf} structure", 6 if st == word else 0, 6, True,
              f"{inp.primary_tf} structure {st} ({'/'.join(p.structure.get('labels', [])) or 'n/a'})")
    else:
        S.add(f"{inp.primary_tf} structure", 0, 6, False, "primary timeframe unavailable")
    h1 = tfs.get(highers[0]) if highers else None
    if _usable(h1):
        st = h1.structure.get("trend")
        S.add(f"{highers[0]} structure", 4 if st == word else 1 if st == "range" else 0, 4, True,
              f"{highers[0]} structure {st}")
    else:
        S.add("higher-TF structure", 0, 4, False, "higher timeframe unavailable")
    if p_ok and s.get("atr"):
        levels = p.resistances if d > 0 else p.supports
        close, atr_v = s["close"], s["atr"]
        if levels:
            dist = abs(levels[0]["price"] - close) / atr_v
            S.add("room to next opposing level", 4 if dist >= 2 else 2 if dist >= 1 else 0, 4, True,
                  f"nearest {'resistance' if d > 0 else 'support'} {levels[0]['price']:.6g} is {dist:.1f} ATR away")
        else:
            S.add("room to next opposing level", 3, 4, True,
                  "no opposing swing level in lookback (price discovery — targets less certain)")
    else:
        S.add("room to next opposing level", 0, 4, False, "levels unavailable")
    if p_ok:
        conf = []
        if p.structure.get("bos") == word:
            conf.append(f"{word} break of structure")
        if p.structure.get("choch") == word:
            conf.append(f"{word} change of character")
        bt = p.breakout.get("type")
        if (d > 0 and bt == "breakout") or (d < 0 and bt == "breakdown"):
            conf.append("volume-confirmed range break")
        if p.divergence == word:
            conf.append(f"{word} RSI divergence")
        if any(pt["bias"] == word for pt in p.patterns):
            conf.append("candlestick " + ",".join(pt["pattern"] for pt in p.patterns if pt["bias"] == word))
        close = s["close"]
        if any(g["type"] == word and ((d > 0 and g["top"] <= close) or (d < 0 and g["bottom"] >= close))
               for g in p.fvgs[-3:]):
            conf.append(f"unfilled {word} FVG behind price")
        S.add("confluence signals", len(conf), 3, True, "; ".join(conf) if conf else "no additional confluence")
    else:
        S.add("confluence signals", 0, 3, False, "primary timeframe unavailable")
    if _usable(trig):
        S.add(f"{trig.timeframe} trigger alignment", 3 * _clip01(d * trig.bias / 0.6), 3, True,
              f"{trig.timeframe} trend {trig.trend} (bias {trig.bias:+.2f})")
    else:
        S.add("trigger timeframe alignment", 0, 3, False, "trigger timeframe unavailable")

    # ------------------------------------------------------------ liquidity (15)
    L = cats["liquidity"]
    to = inp.liquidity.get("turnover_24h")
    L.add("24h turnover", 4 if to and to >= 5e8 else 3 if to and to >= 1e8 else 2 if to else 0, 4, bool(to),
          f"${to:,.0f}" if to else "unavailable")
    sp = inp.liquidity.get("spread_bps")
    ok = sp is not None and np.isfinite(sp)
    L.add("bid/ask spread", 3 if ok and sp <= 2 else 2 if ok and sp <= 5 else 1 if ok and sp <= 10 else 0, 3, ok,
          f"{sp:.2f} bps" if ok else "unavailable")
    ob = (inp.derivatives.orderbook if inp.derivatives else {}) or {}
    if ob.get("available"):
        depth = min(ob.get("bid_depth_usd_0_5", 0), ob.get("ask_depth_usd_0_5", 0))
        L.add("depth within ±0.5%", 4 if depth >= 2e6 else 3 if depth >= 5e5 else 1 if depth >= 1e5 else 0, 4, True,
              f"thinner side ${depth:,.0f}" + ("" if ob.get("band_covered_0_5") else " (50-level book may not cover full band)"))
    else:
        L.add("depth within ±0.5%", 0, 4, False, "orderbook unavailable")
    if p_ok and s.get("rvol") is not None:
        rv, cd = s["rvol"], s.get("candle_dir", 0)
        pts = 4 if rv >= 1.2 and cd * d > 0 else 0 if rv >= 1.2 and cd * d < 0 else 1 if rv < 0.8 else 2
        L.add(f"{inp.primary_tf} relative volume", pts, 4, True,
              f"RVOL {rv:.2f} on a {'bullish' if cd > 0 else 'bearish' if cd < 0 else 'neutral'} candle")
    else:
        L.add("relative volume", 0, 4, False, "unavailable")

    # ------------------------------------------------------------ derivatives (15)
    D = cats["derivatives"]
    dv = inp.derivatives
    if dv and dv.available.get("funding"):
        f8 = dv.funding_8h_equiv
        if d > 0:
            pts = 0 if f8 >= FUNDING_CROWDED_LONG else 5 if f8 <= FUNDING_CROWDED_SHORT else 4
        else:
            pts = 0 if f8 <= FUNDING_CROWDED_SHORT else 5 if f8 >= FUNDING_CROWDED_LONG else 4
        D.add("funding positioning", pts, 5, True, f"funding {f8 * 100:.4f}%/8h-equivalent")
    else:
        D.add("funding positioning", 0, 5, False, "funding unavailable")
    if dv and dv.available.get("open_interest") and dv.oi_regime:
        table = {1: {"new_longs": 5, "short_covering": 2, "neutral": 2, "long_liquidation": 1, "new_shorts": 0},
                 -1: {"new_shorts": 5, "long_liquidation": 2, "neutral": 2, "short_covering": 1, "new_longs": 0}}
        D.add("OI / price regime", table[d][dv.oi_regime], 5, True,
              f"{dv.oi_regime.replace('_', ' ')} (OI 4h {dv.oi_change_pct.get('4h', 0):+.1f}%, "
              f"price 4h {dv.price_change_pct.get('4h', 0):+.1f}%)")
    else:
        D.add("OI / price regime", 0, 5, False, "open interest unavailable")
    if dv and dv.available.get("long_short") and dv.long_short_ratio:
        r = dv.long_short_ratio
        pts = (2 if r <= 1.5 else 1 if r <= 2.5 else 0) if d > 0 else (2 if r >= 1.0 else 1 if r >= 0.7 else 0)
        D.add("account long/short ratio", pts, 2, True, f"{r:.2f}")
    else:
        D.add("account long/short ratio", 0, 2, False, "unavailable")
    flow_pts, flow_txt, flow_av = 0.0, [], False
    if dv and dv.available.get("orderbook") and ob.get("imbalance_0_5") is not None:
        flow_av = True
        imb = ob["imbalance_0_5"]
        flow_pts += 1.5 if d * imb > 0.1 else 0
        flow_txt.append(f"book imbalance {imb:+.2f}")
    if dv and dv.available.get("trade_flow"):
        flow_av = True
        dr = dv.trade_flow.get("delta_ratio") or 0
        flow_pts += 1.5 if d * dr > 0.1 else 0
        flow_txt.append(f"aggressor delta {dr:+.2f}")
    D.add("order flow", flow_pts, 3, flow_av, "; ".join(flow_txt) or "orderbook/trade-flow unavailable")

    # ------------------------------------------------------------ news & macro (15)
    N = cats["news_macro"]
    if inp.calendar_risk and inp.calendar_risk.get("available"):
        ev = inp.calendar_risk.get("high_impact_events", [])
        N.add("macro event risk (24h)", 0 if ev else 6, 6, True,
              ("high-impact event(s): " + ", ".join(f"{e['name']} ({e['in']})" for e in ev)) if ev
              else "no high-impact scheduled event in the next 24h (per loaded calendar)")
    else:
        N.add("macro event risk (24h)", 0, 6, False, "economic calendar not loaded — event risk unknown")
    if inp.news is not None:
        sent = inp.news.get("avg_sentiment_confirmed", 0.0)
        n = inp.news.get("confirmed_count", 0)
        N.add("asset/market news flow", 2.5 + 2.5 * d * sent if n else 2.5, 5, True,
              f"{n} confirmed relevant items, avg lexicon sentiment {sent:+.2f} (weak evidence)" if n
              else "no material confirmed news in 72h (neutral)")
        crit = inp.news.get("critical_negative", [])
        if d > 0:
            N.add("shock events (hack/insolvency)", 0 if crit else 4, 4, True,
                  ("negative shock: " + "; ".join(crit[:2])) if crit else "none detected in 72h")
        else:
            N.add("shock events (hack/insolvency)", 4 if crit else 2, 4, True,
                  ("negative shock: " + "; ".join(crit[:2])) if crit else "none detected in 72h")
    else:
        N.add("asset/market news flow", 0, 5, False, "news feeds unavailable")
        N.add("shock events (hack/insolvency)", 0, 4, False, "news feeds unavailable")

    # ------------------------------------------------------------ sentiment & on-chain (10)
    E = cats["sentiment"]
    sr = inp.sentiment
    if sr and sr.fear_greed is not None:
        fg = sr.fear_greed
        pts = (0 if fg >= 80 else 2 if fg >= 65 else 3 if fg > 25 else 4) if d > 0 else \
              (0 if fg <= 20 else 2 if fg <= 35 else 3 if fg < 75 else 4)
        E.add("Fear & Greed (contrarian-aware)", pts, 4, True, f"{fg} ({sr.fear_greed_label}), age {sr.age}")
    else:
        E.add("Fear & Greed (contrarian-aware)", 0, 4, False, "unavailable or stale")
    sc = (inp.onchain or {}).get("metrics", {}).get("stablecoin_supply")
    if sc:
        ch = sc["change_30d_pct"]
        pts = (3 if ch > 1 else 1.5 if ch >= -1 else 0) if d > 0 else (3 if ch < -1 else 1.5 if ch <= 1 else 0)
        E.add("stablecoin supply trend", pts, 3, True, f"30d {ch:+.2f}% ({sc['interpretation']})")
    else:
        E.add("stablecoin supply trend", 0, 3, False, "unavailable")
    if sr and sr.fear_greed is not None:
        divs = sr.divergences
        bull_div = [x for x in divs if x.startswith("Fear")]
        bear_div = [x for x in divs if x.startswith("Greed")]
        mine, theirs = (bull_div, bear_div) if d > 0 else (bear_div, bull_div)
        pts = 3 if mine else 0 if theirs else 1.5
        E.add("sentiment/price divergence", pts, 3, True,
              (mine or theirs or ["no sentiment/price divergence"])[0])
    else:
        E.add("sentiment/price divergence", 0, 3, False, "sentiment unavailable")
    return ScoreCard(direction, cats)
