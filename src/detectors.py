"""Deterministic price-action detectors formalising the video course claims.

Video ontology (Arabic transcript, Part 1):
  C1 bulls-vs-bears tug-of-war: price = net result of two-sided pressure
  C2 candle = one round: body = net displacement, wicks = rejected excursion
  C3 three regimes only: up (HH/HL staircase), down (LH/LL), range (no progress)
  C4 three investigator questions: Q1 who dominates / Q2 how strong (momentum)
      / Q3 is dominance changing (reversal vs rest)
  C5 momentum triad: (a) winner body size, (b) pullback shallowness, (c) consecutiveness
  C6 reversal needs ALL THREE: (i) deeper pullback breaking prior swing,
      (ii) failed advance (upper wicks / no new high hold), (iii) momentum flip
  C7 support/resistance = memory zones (areas, not knife lines); line reveals, never decides
  C8 indicators (MACD/RSI/BB) describe, never predict — benchmarked as controls

Every function is pure, uses only bars <= t (no lookahead), and returns
boolean Series aligned with df (signal known at close t, tradable at open t+1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _o(df): return df["open"].to_numpy(dtype=float)
def _h(df): return df["high"].to_numpy(dtype=float)
def _l(df): return df["low"].to_numpy(dtype=float)
def _c(df): return df["close"].to_numpy(dtype=float)


def candle_features(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = _o(df), _h(df), _l(df), _c(df)
    rng = np.maximum(h - l, 1e-12)
    body = c - o
    out = pd.DataFrame(index=df.index)
    out["body"] = body
    out["range"] = rng
    out["body_frac"] = np.abs(body) / rng          # 1 = clean marubozu-like, 0 = doji
    out["upper_wick"] = (h - np.maximum(o, c)) / rng
    out["lower_wick"] = (np.minimum(o, c) - l) / rng
    out["green"] = (c > o).astype(int)
    out["red"] = (c < o).astype(int)
    out["atr_like"] = pd.Series(rng).rolling(14, min_periods=14).mean().to_numpy()
    return out


def regime_trend(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Q1 — who dominates. Staircase definition from the video:
    up = close above SMA20 and rising swing highs/lows; down = mirror; else range."""
    c = _c(df)
    s = pd.Series(c)
    sma = s.rolling(lookback, min_periods=lookback).mean().to_numpy()
    hh = s.rolling(lookback, min_periods=lookback).max().to_numpy()
    ll = s.rolling(lookback, min_periods=lookback).min().to_numpy()
    # swing slope via linear fit over lookback (positive drift = bulls winning net)
    slope = np.full(len(df), np.nan)
    for i in range(lookback - 1, len(df)):
        y = s.iloc[i - lookback + 1 : i + 1].to_numpy()
        x = np.arange(lookback)
        slope[i] = np.polyfit(x, y, 1)[0] / (np.mean(np.abs(y)) + 1e-12)
    up = (c > sma) & (slope > 0) & (c > np.roll(hh, 5))
    down = (c < sma) & (slope < 0) & (c < np.roll(ll, 5))
    lab = np.array(["range"] * len(df), dtype=object)
    lab[up] = "up"
    lab[down] = "down"
    lab[: lookback + 5] = "warmup"
    return pd.Series(lab, index=df.index, name="regime")


def momentum_score(df: pd.DataFrame, window: int = 10) -> pd.Series:
    """Q2 — how strong. Mean of the video triad, each in [0,1], bulls-positive:
    (a) winner body size, (b) pullback shallowness, (c) consecutiveness."""
    f = candle_features(df)
    c = pd.Series(_c(df))
    ret = c.pct_change().fillna(0).to_numpy()
    # (a) signed body strength
    a = np.sign(f["body"].to_numpy()) * f["body_frac"].to_numpy()
    # (b) pullback shallowness: adverse excursion / range, inverted
    adv = np.where(ret >= 0, f["lower_wick"].to_numpy(), f["upper_wick"].to_numpy())
    b = np.sign(f["body"].to_numpy()) * (1.0 - adv)
    # (c) consecutiveness: rolling mean sign agreement
    sign = np.sign(f["body"].to_numpy())
    consec = pd.Series(sign).rolling(window, min_periods=window).mean().to_numpy()
    score = (pd.Series(a).rolling(window, min_periods=window).mean().to_numpy()
             + pd.Series(b).rolling(window, min_periods=window).mean().to_numpy()
             + consec) / 3.0
    return pd.Series(score, index=df.index, name="momentum").fillna(0.0)


def reversal_3rule_bearish(df: pd.DataFrame, swing: int = 10) -> pd.Series:
    """Q3 — full 3-evidence bearish flip inside an uptrend (tired vs flipped).
    (i)  pullback undercuts prior swing low (deeper than previous rests)
    (ii) failed advance: upper wick > 40% of range and no new 10-bar high hold
    (iii) momentum flip: 10-bar momentum crosses from + to -.
    All three must hold on the SAME bar — the video's core anti-false-alarm rule."""
    c, h, l = _c(df), _h(df), _l(df)
    f = candle_features(df)
    mom = momentum_score(df, 10).to_numpy()
    swing_low = pd.Series(l).rolling(swing, min_periods=swing).min().shift(2).to_numpy()
    (i) = l < swing_low
    prev_high = pd.Series(h).rolling(swing, min_periods=swing).max().shift(1).to_numpy()
    (ii) = (f["upper_wick"].to_numpy() > 0.40) & (h < prev_high + 1e-12)
    (iii) = (np.roll(mom, 1) > 0.05) & (mom < -0.05)
    sig = (i) & (ii) & (iii)
    sig[: swing + 12] = False
    return pd.Series(sig, index=df.index, name="bear_flip_3rule")


def reversal_1rule_placebo(df: pd.DataFrame) -> pd.Series:
    """Placebo: single-evidence alarm (small bodies only) — expected to over-fire."""
    f = candle_features(df)
    sig = (f["body_frac"].to_numpy() < 0.25).astype(bool)
    sig[:15] = False
    return pd.Series(sig, index=df.index, name="bear_flip_1rule")


def support_touches(df: pd.DataFrame, swing: int = 20, tol_atr: float = 0.5) -> pd.Series:
    """C7 — memory zones: rolling swing low; touch = low within tol*ATR of it."""
    l = _l(df)
    f = candle_features(df)
    atr = f["atr_like"].bfill().fillna((pd.Series(_h(df) - _l(df))).mean()).to_numpy()
    zone = pd.Series(l).rolling(swing, min_periods=swing).min().shift(2).to_numpy()
    touch = np.abs(l - zone) < tol_atr * atr
    touch[: swing + 2] = False
    return pd.Series(touch, index=df.index, name="support_touch")


def resistance_touches(df: pd.DataFrame, swing: int = 20, tol_atr: float = 0.5) -> pd.Series:
    h = _h(df)
    f = candle_features(df)
    atr = f["atr_like"].bfill().fillna((pd.Series(_h(df) - _l(df))).mean()).to_numpy()
    zone = pd.Series(h).rolling(swing, min_periods=swing).max().shift(2).to_numpy()
    touch = np.abs(h - zone) < tol_atr * atr
    touch[: swing + 2] = False
    return pd.Series(touch, index=df.index, name="resistance_touch")


# ---- indicator controls (C8): classic retail settings, PIT-correct ----

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    d = series.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = up / (dn + 1e-12)
    return 100 - 100 / (1 + rs)


def macd_bear_cross(df: pd.DataFrame) -> pd.Series:
    c = pd.Series(_c(df))
    macd = c.ewm(span=12, min_periods=26, adjust=False).mean() - c.ewm(span=26, min_periods=26, adjust=False).mean()
    sig = macd.ewm(span=9, min_periods=9, adjust=False).mean()
    cross = (macd.shift(1) > sig.shift(1)) & (macd < sig)
    return cross.fillna(False).rename("macd_bear")


def rsi_overbought(df: pd.DataFrame) -> pd.Series:
    return (rsi(pd.Series(_c(df))) > 70).fillna(False).rename("rsi_ob")
