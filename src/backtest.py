"""Point-in-time backtest engine.

Iron rules (from surveyed best practice):
- signal known at close t -> position taken at open t+1 (open_next column)
- flat 1-unit short-horizon event trade held H bars (default 5), no compounding tricks
- costs applied as round-trip bps on notional (5 / 11 / 20 bps grid)
- every event measured against its own exposure-matched control:
  same regime, same symbol, no-signal bars (Quanta72 / Tangirala matched-null design)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def event_returns(df: pd.DataFrame, signal: pd.Series, horizon: int = 5) -> pd.DataFrame:
    """Forward open-to-open returns for each signal bar (PIT-correct)."""
    assert "open_next" in df.columns
    o = df["open"].to_numpy(dtype=float)
    on = df["open_next"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    sig = signal.to_numpy(dtype=bool)
    rows = []
    n = len(df)
    for i in np.where(sig)[0]:
        entry_idx = i + 1
        exit_idx = i + 1 + horizon
        if exit_idx >= n or np.isnan(on[i]) or np.isnan(o[exit_idx]):
            continue
        entry, exit_ = on[i], o[exit_idx]
        if entry <= 0 or exit_ <= 0:
            continue
        # short-flip trade: video studies bearish reversal, so direction = -1
        gross = (entry - exit_) / entry
        rows.append({"t": df["time"].iloc[i], "i": i, "gross": gross})
    return pd.DataFrame(rows)


def apply_costs(gross: pd.Series, bps: float) -> pd.Series:
    return gross - bps / 1e4


def matched_control_returns(df: pd.DataFrame, signal: pd.Series, regime: pd.Series, horizon: int = 5, seed: int = 7) -> pd.DataFrame:
    """Exposure-matched null: for each signal, pick a random no-signal bar
    in the same regime on the same symbol (composition-matched null)."""
    rng = np.random.default_rng(seed)
    sig = signal.to_numpy(dtype=bool)
    reg = regime.to_numpy()
    o = df["open"].to_numpy(dtype=float)
    on = df["open_next"].to_numpy(dtype=float)
    n = len(df)
    pool_by_reg: dict[str, list[int]] = {}
    for i in range(n - horizon - 1):
        if sig[i] or reg[i] == "warmup" or np.isnan(on[i]):
            continue
        pool_by_reg.setdefault(str(reg[i]), []).append(i)
    rows = []
    for i in np.where(sig)[0]:
        pool = pool_by_reg.get(str(reg[i]), [])
        if not pool:
            continue
        j = pool[rng.integers(0, len(pool))]
        entry, exit_ = on[j], o[j + horizon]
        if entry <= 0 or exit_ <= 0 or np.isnan(entry) or np.isnan(exit_):
            continue
        rows.append({"t": df["time"].iloc[j], "i": j, "gross": (entry - exit_) / entry})
    return pd.DataFrame(rows)


def summarise(tr: pd.DataFrame, net: pd.Series) -> dict:
    if tr.empty:
        return {"n": 0, "mean_bps": float("nan"), "win_rate": float("nan"),
                "sharpe_like": float("nan"), "profit_factor": float("nan")}
    w = (net > 0).mean()
    mu, sd = net.mean(), net.std(ddof=1)
    pf = net[net > 0].sum() / abs(net[net < 0].sum()) if (net < 0).any() and (net > 0).any() else float("nan")
    return {"n": int(len(tr)), "mean_bps": float(mu * 1e4),
            "win_rate": float(w),
            "sharpe_like": float(mu / (sd + 1e-12) * (252 ** 0.5)) if sd > 0 else 0.0,
            "profit_factor": float(pf) if pf == pf else float("nan")}
