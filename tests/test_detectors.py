import pandas as pd
from src.detectors import momentum_score, regime_trend, reversal_3rule_bearish


def _mk(n=60):
    import numpy as np
    o = np.linspace(100, 120, n)
    h = o + 1.0
    l = o - 1.0
    c = o + 0.5
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "time": pd.date_range("2024-01-01", periods=n, tz="UTC")})


def test_no_lookahead_shape():
    df = _mk()
    assert len(regime_trend(df)) == len(df)
    assert len(momentum_score(df)) == len(df)
    assert len(reversal_3rule_bearish(df)) == len(df)


def test_regime_values():
    df = _mk()
    vals = set(regime_trend(df).unique().tolist())
    assert vals <= {"up", "down", "range", "warmup"}
