from datetime import timedelta

import pytest

import pandas as pd

from cryptointel.analysis.derivatives import analyze_derivatives
from cryptointel.analysis.opportunity import NO_TRADE, build_opportunity
from cryptointel.analysis.scoring import ScoringInputs, score
from cryptointel.analysis.sentiment import SentimentReport
from cryptointel.analysis.timeframe import analyze_timeframe
from cryptointel.config import Settings

FREQ = {"15m": "15min", "1h": "h", "4h": "4h", "1d": "D"}


def tfas(synth, drift=0.002, tfs=("15m", "1h", "4h", "1d")):
    out = {}
    for tf in tfs:
        n = 320
        df = synth(n, seed=hash(tf) % 100, drift=drift, vol=0.004, freq=FREQ[tf])
        # place the last candle so it is fresh relative to "now"
        step = pd.Timedelta(FREQ[tf] if FREQ[tf][0].isdigit() else "1" + FREQ[tf])
        df.index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("min") - step, periods=n, freq=FREQ[tf])
        out[tf] = analyze_timeframe(df, tf)
    return out


def empty_inputs(t):
    return ScoringInputs(timeframes=t, primary_tf="1h", derivatives=None, liquidity={}, news=None,
                         calendar_risk=None, sentiment=None, onchain=None)


def test_categories_sum_to_100_maximum(synth):
    card = score(empty_inputs(tfas(synth)), "long")
    assert sum(c.max_points for c in card.categories.values()) == 100
    for c in card.categories.values():
        assert sum(x.max_points for x in c.components) == c.max_points


def test_missing_data_scores_zero(synth):
    card = score(empty_inputs(tfas(synth)), "long")
    for key in ("derivatives", "news_macro", "sentiment"):
        assert card.points(key) == 0
    assert any("funding" in m for m in card.missing)
    assert any("calendar" in c.evidence for c in card.categories["news_macro"].components)


def test_no_timeframes_means_zero_and_no_trade():
    inp = empty_inputs({})
    assert score(inp, "long").total == 0
    opp = build_opportunity("X", inp, Settings(), price=100, funding_rate=0.0001)
    assert opp.status == "NO_TRADE" and opp.headline == NO_TRADE and opp.entry is None


def test_uptrend_scores_long_above_short(synth):
    t = tfas(synth, drift=0.003)
    inp = empty_inputs(t)
    inp.liquidity = {"turnover_24h": 1e9, "spread_bps": 1}
    assert score(inp, "long").total > score(inp, "short").total


def test_full_data_can_produce_signal_with_plan(synth):
    t = tfas(synth, drift=0.003)
    close = t["1h"].snapshot["close"]
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=48, freq="h")
    oi = pd.Series([1000 * (1 + 0.005 * i) for i in range(48)], index=idx)
    px = pd.Series([close * (1 + 0.002 * (i - 47)) for i in range(48)], index=idx)
    deriv = analyze_derivatives(
        ticker={"funding_rate": 0.0001}, funding_hist=None, open_interest=oi, price=px,
        ls_ratio=pd.DataFrame({"buy_ratio": [0.55], "sell_ratio": [0.45]}, index=idx[-1:]),
        book={"bids": [(close * (1 - 0.0001 * i), 500) for i in range(1, 51)],
              "asks": [(close * (1 + 0.0001 * i), 300) for i in range(1, 51)]})
    inp = ScoringInputs(
        timeframes=t, primary_tf="1h", derivatives=deriv, liquidity={"turnover_24h": 1e9, "spread_bps": 1},
        news={"confirmed_count": 0, "avg_sentiment_confirmed": 0, "critical_negative": [], "items": []},
        calendar_risk={"available": True, "high_impact_events": []},
        sentiment=SentimentReport(fear_greed=50, fear_greed_label="Neutral", age="1h"),
        onchain={"metrics": {"stablecoin_supply": {"change_30d_pct": 2.0, "interpretation": "expanding"}}},
    )
    s = Settings(min_score=50)
    opp = build_opportunity("TESTUSDT", inp, s, price=close, funding_rate=0.0001)
    long_card = score(inp, "long")
    assert long_card.total > 50
    if opp.status == "SIGNAL":
        assert opp.stop < opp.entry < opp.take_profits[0] < opp.take_profits[1]
        assert opp.rr_net_blended >= s.min_rr
        assert not opp.simulation["liquidation_before_stop"]
        assert opp.invalidation
    else:  # every rejection must be explained
        assert opp.gate_failures and opp.rejected_plan


def test_macro_event_blocks_trade(synth):
    t = tfas(synth, drift=0.003)
    inp = empty_inputs(t)
    inp.calendar_risk = {"available": True, "high_impact_events": [{"name": "CPI", "in": "3h"}]}
    opp = build_opportunity("X", inp, Settings(min_score=0, min_technical_points=0, min_structure_points=0),
                            price=t["1h"].snapshot["close"], funding_rate=0)
    assert opp.status == "NO_TRADE"
    assert any("macro" in g for g in opp.gate_failures)


def test_stale_primary_blocks_trade(synth):
    t = tfas(synth)
    t["1h"].stale = True
    opp = build_opportunity("X", empty_inputs(t), Settings(), price=100, funding_rate=0)
    assert opp.status == "NO_TRADE"
    assert any("stale" in g for g in opp.gate_failures)


def _tfa(tf, bias, close=100.0, atr=1.0, rsi=60.0):
    from cryptointel.analysis.timeframe import TimeframeAnalysis

    snap = {"close": close, "atr": atr, "rsi": rsi, "macd_hist": 0.1, "stochrsi_k": 60, "stochrsi_d": 50,
            "roc": 1.0, "bb_pct_b": 0.7, "obv_slope": 0.01, "vwap": close * 0.995, "rvol": 1.5,
            "candle_dir": 1.0, "ema50": close * 0.97}
    return TimeframeAnalysis(
        timeframe=tf, sufficient=True, bars=300, stale=False, trend="bullish", bias=bias, adx=28,
        volatility_regime="normal", snapshot=snap,
        structure={"trend": "bullish", "labels": ["HH", "HL"], "bos": "bullish", "choch": None},
        supports=[{"price": close - 1.6 * atr, "touches": 3, "kind": "support"}],
        resistances=[{"price": close + 5 * atr, "touches": 2, "kind": "resistance"},
                     {"price": close + 8 * atr, "touches": 2, "kind": "resistance"}],
        breakout={"type": None}, swing_lows=[close - 3 * atr, close - 1.6 * atr],
        swing_highs=[close + 5 * atr], bullish_evidence=["price above EMA200"], bearish_evidence=[])


def test_deterministic_signal_and_paper_trade():
    from cryptointel.paper.engine import PaperBroker
    from cryptointel.risk.leverage import CostModel

    t = {tf: _tfa(tf, 0.8) for tf in ("15m", "1h", "4h", "1d")}
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=48, freq="h")
    deriv = analyze_derivatives(
        ticker={"funding_rate": 0.0001}, funding_hist=None,
        open_interest=pd.Series([1000 * (1 + 0.01 * i) for i in range(48)], index=idx),
        price=pd.Series([100 * (1 + 0.003 * (i - 47)) for i in range(48)], index=idx),
        ls_ratio=pd.DataFrame({"buy_ratio": [0.55], "sell_ratio": [0.45]}, index=idx[-1:]),
        book={"bids": [(100 - 0.01 * i, 900) for i in range(1, 51)], "asks": [(100 + 0.01 * i, 600) for i in range(1, 51)]})
    inp = ScoringInputs(
        timeframes=t, primary_tf="1h", derivatives=deriv, liquidity={"turnover_24h": 1e9, "spread_bps": 1},
        news={"confirmed_count": 0, "avg_sentiment_confirmed": 0, "critical_negative": [], "items": []},
        calendar_risk={"available": True, "high_impact_events": []},
        sentiment=SentimentReport(fear_greed=50, fear_greed_label="Neutral", age="1h"),
        onchain={"metrics": {"stablecoin_supply": {"change_30d_pct": 2.0, "interpretation": "expanding"}}})
    s = Settings()
    opp = build_opportunity("TESTUSDT", inp, s, price=100.0, funding_rate=0.0001)
    assert opp.status == "SIGNAL", opp.gate_failures
    assert opp.direction == "long" and opp.score >= s.min_score
    assert opp.stop == pytest.approx(100 - 1.6 - 0.25)  # swing low 98.4 minus 0.25 ATR buffer
    assert opp.take_profits[0] == pytest.approx(105 - 0.1)  # in front of resistance
    assert opp.rr_net_blended >= s.min_rr and opp.invalidation and opp.supporting
    b = PaperBroker(10_000, CostModel(), 5)
    tr = b.open(symbol="TESTUSDT", side="long", price=100.0, stop=opp.stop, take_profits=opp.take_profits,
                leverage=s.paper_leverage, risk_pct=s.risk_per_trade)
    assert tr is not None and tr.liq_price < opp.stop
    # Same setup with a short-side bias must not produce a long signal
    t2 = {tf: _tfa(tf, -0.8) for tf in t}
    inp.timeframes = t2
    assert build_opportunity("TESTUSDT", inp, s, price=100.0, funding_rate=0.0001).direction != "long"


def test_price_candle_mismatch_blocks_plan():
    t = {tf: _tfa(tf, 0.8) for tf in ("15m", "1h", "4h", "1d")}
    opp = build_opportunity("X", empty_inputs(t), Settings(), price=110.0, funding_rate=0)
    assert opp.status == "NO_TRADE" and "ATR from the last closed" in opp.gate_failures[0]
