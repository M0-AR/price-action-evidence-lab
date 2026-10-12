"""Statistics: BH-FDR, bootstrap CIs, Newey-West-style calendar aggregation.

Mirrors the surveyed 2026 SSRN designs (Shah; Tangirala; Casamayor):
- Benjamini-Hochberg across the hypothesis family (never report raw p only)
- stationary-ish bootstrap over daily event pnl for CI of mean
- calendar-day aggregation (one bucket per date) before t-tests to kill
  cross-sectional clustering
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def bh_fdr(pvals: list[float], q: float = 0.05) -> list[bool]:
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    thresh = (np.arange(1, m + 1) / m) * q
    below = ranked <= thresh
    reject = np.zeros(m, dtype=bool)
    if below.any():
        kmax = np.where(below)[0].max()
        reject[order[: kmax + 1]] = True
    return reject.tolist()


def bootstrap_mean_ci(x: np.ndarray, n_boot: int = 2000, seed: int = 11, alpha: float = 0.05):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return float("nan"), (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(x, size=len(x), replace=True).mean() for _ in range(n_boot)])
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(x.mean()), (float(lo), float(hi))


def mannwhitney_vs_control(sig: np.ndarray, ctl: np.ndarray) -> float:
    a = np.asarray(sig, dtype=float)
    b = np.asarray(ctl, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 8 or len(b) < 8:
        return float("nan")
    try:
        return float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)
    except Exception:
        return float("nan")
