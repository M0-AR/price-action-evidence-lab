"""Verified charts — every bar comes straight from results/*.csv (no hand numbers).

Outputs docs/*.png used by README + preview.html.
Run: PYTHONPATH=. python3 experiments/make_charts.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
DOCS = ROOT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)


def chart_regimes():
    e1 = pd.read_csv(RES / "regimes.csv")
    syms = ["SPY", "AAPL", "BTC-USD", "GLD", "EURUSD=X"]
    regs = ["up", "down", "range"]
    x = np.arange(len(syms))
    w = 0.24
    fig, ax = plt.subplots(figsize=(10, 5))
    for j, r in enumerate(regs):
        means, lo, hi = [], [], []
        for s in syms:
            row = e1[(e1.symbol == s) & (e1.regime == r)].iloc[0]
            means.append(row.mean_bps)
            lo.append(row.mean_bps - row.ci_lo_bps)
            hi.append(row.ci_hi_bps - row.mean_bps)
        ax.bar(x + (j - 1) * w, means, w, yerr=[lo, hi], capsize=3, label=r)
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace("=X", "") for s in syms])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Mean 5d long return (bps, next-open execution)")
    ax.set_title("E1 — Regime base rates with 95% bootstrap CI (live 2020-2026)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(DOCS / "chart_regimes.png", dpi=150)
    print("wrote", DOCS / "chart_regimes.png")


def chart_costs():
    tab = pd.read_csv(RES / "table.csv")
    picks = [("SPY", "E5_macd_bear"), ("BTC-USD", "E5_macd_bear"),
             ("BTC-USD", "E5_rsi_ob"), ("EURUSD=X", "E5_rsi_ob"),
             ("EURUSD=X", "E3_1rule_placebo"), ("SPY", "E3_1rule_placebo")]
    costs = [0, 5, 11, 20]
    fig, ax = plt.subplots(figsize=(10, 5))
    for sym, exp in picks:
        row = tab[(tab.symbol == sym) & (tab.exp == exp)].iloc[0]
        vals = [row[f"mean_net_{c}bps"] for c in costs]
        ax.plot(costs, vals, marker="o", label=f"{sym} {exp.split('_', 1)[1]}")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Round-trip cost (bps)")
    ax.set_ylabel("Mean 5d short return (bps)")
    ax.set_title("E6 — Cost walk erases marginal edges (gross -> net)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(DOCS / "chart_costs.png", dpi=150)
    print("wrote", DOCS / "chart_costs.png")


def chart_signals():
    tab = pd.read_csv(RES / "table.csv")
    fams = ["E3_3rule_bear", "E3_1rule_placebo", "E5_macd_bear", "E5_rsi_ob"]
    totals = [int(tab[tab.exp == f].n_sig.sum()) for f in fams]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar([f.replace("E3_", "").replace("E5_", "") for f in fams], totals)
    ax.set_yscale("log")
    for i, v in enumerate(totals):
        ax.text(i, v * 1.08, str(v), ha="center", fontsize=10)
    ax.set_ylabel("Total events, 5 assets x ~6y (log scale)")
    ax.set_title("E3/E5 — Conjunction starvation: 3-rule fires 3x in 8,274 bars")
    fig.tight_layout()
    fig.savefig(DOCS / "chart_signals.png", dpi=150)
    print("wrote", DOCS / "chart_signals.png")


if __name__ == "__main__":
    chart_regimes()
    chart_costs()
    chart_signals()
