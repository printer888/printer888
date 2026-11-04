"""Machine-learning diagnostic: does a classifier predict forward-return direction
better than naive baselines, out-of-sample?

Design choices
  • Features are causal (indicator values at bar t).
  • Label: sign of the forward return over `horizon` bars, with a dead zone equal to
    round-trip costs (moves smaller than costs are labelled 0 → "no edge").
  • Purged walk-forward: an embargo of `horizon` bars between train and test windows
    prevents label overlap leakage.
  • Baselines: majority class and "always up". The model is only flagged `validated`
    if it beats both on accuracy AND has ROC-AUC meaningfully above 0.5 on average.
  • PyTorch is not used: on tabular features with a few thousand samples, deep nets
    add variance without evidence of benefit. Gradient boosting / logistic regression
    are the justified choices here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import ta


def features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    for n in (1, 3, 6, 12, 24):
        f[f"ret_{n}"] = c.pct_change(n)
    f["rsi"] = ta.rsi(c)
    m = ta.macd(c)
    f["macd_hist_norm"] = m["hist"] / c
    a = ta.adx(df)
    f["adx"] = a["adx"]
    f["di_diff"] = a["plus_di"] - a["minus_di"]
    bb = ta.bollinger(c)
    f["bb_pct_b"] = bb["pct_b"]
    f["bb_width"] = bb["bandwidth"]
    f["atr_pct"] = ta.atr(df) / c
    f["rvol"] = ta.relative_volume(df["volume"])
    for n in (20, 50, 200):
        f[f"dist_ema{n}"] = c / ta.ema(c, n) - 1
    f["hour"] = df.index.hour
    return f


def labels(df: pd.DataFrame, horizon: int, cost: float) -> pd.Series:
    fwd = df["close"].shift(-horizon) / df["close"] - 1
    y = pd.Series(np.where(fwd > cost, 1, np.where(fwd < -cost, -1, 0)), index=df.index, dtype=float)
    y[fwd.isna()] = np.nan
    return y


def evaluate(df: pd.DataFrame, horizon: int = 12, cost: float = 0.0015, n_folds: int = 5,
             model: str = "gbm") -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = features(df)
    y = labels(df, horizon, cost)
    data = X.join(y.rename("y")).dropna()
    data = data[data["y"] != 0]  # only moves larger than costs
    if len(data) < 600:
        return {"validated": False, "error": f"insufficient samples ({len(data)})"}
    Xv, yv = data.drop(columns="y").to_numpy(), (data["y"] > 0).astype(int).to_numpy()
    n = len(data)
    fold_size = n // (n_folds + 1)
    results = []
    last_model = None
    for k in range(1, n_folds + 1):
        train_end = k * fold_size
        test_start = train_end + horizon  # embargo
        test_end = min(test_start + fold_size, n)
        if test_end - test_start < 50:
            break
        Xtr, ytr = Xv[:train_end], yv[:train_end]
        Xte, yte = Xv[test_start:test_end], yv[test_start:test_end]
        if model == "logreg":
            clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=0.5))
        else:
            clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150,
                                                 l2_regularization=1.0, random_state=0)
        clf.fit(Xtr, ytr)
        p = clf.predict_proba(Xte)[:, 1]
        pred = (p > 0.5).astype(int)
        majority = int(ytr.mean() >= 0.5)
        auc = roc_auc_score(yte, p) if len(set(yte)) > 1 else float("nan")
        results.append({
            "fold": k, "n_test": int(len(yte)), "accuracy": float(accuracy_score(yte, pred)),
            "baseline_majority": float((yte == majority).mean()), "baseline_always_up": float(yte.mean()),
            "auc": float(auc), "brier": float(np.mean((p - yte) ** 2)),
        })
        last_model = clf
    if not results:
        return {"validated": False, "error": "not enough data for folds"}
    acc = np.mean([r["accuracy"] for r in results])
    base = max(np.mean([r["baseline_majority"] for r in results]), np.mean([r["baseline_always_up"] for r in results]))
    auc = np.nanmean([r["auc"] for r in results])
    validated = bool(acc > base + 0.01 and auc > 0.53)
    prob_up = None
    if validated and last_model is not None:
        latest = X.dropna().tail(1)
        if len(latest):
            prob_up = float(last_model.predict_proba(latest.to_numpy())[:, 1][0])
    return {
        "model": model, "horizon_bars": horizon, "cost_dead_zone": cost, "folds": results,
        "oos_accuracy": float(acc), "best_baseline_accuracy": float(base), "oos_auc": float(auc),
        "validated": validated, "prob_up": prob_up,
        "conclusion": ("Model beat naive baselines out-of-sample (still modest; may not persist)." if validated
                       else "Model did NOT beat naive baselines out-of-sample — excluded from scoring."),
    }
