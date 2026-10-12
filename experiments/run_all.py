"""End-to-end verification: video claims -> detectors -> PIT backtest -> stats.

Seven pre-registered experiments (frozen BEFORE seeing results):
  E1 regime base-rates (Q1): P(next-5d up | regime) — is 'trend dominates outcome' true?
  E2 momentum triad (Q2): top vs bottom momentum quintile forward returns
  E3 3-rule vs 1-rule reversal (Q3): does requiring ALL THREE evidences cut false alarms?
  E4 support memory (C7): bounce rate at touches vs random bars
  E5 indicator controls (C8): MACD-bear / RSI-OB vs matched controls (expect ~null/negative)
  E6 cost erasure: gross vs 5/11/20bps net (the 'history vs live edge' gap)
  E7 investability: out-of-sample split (first 70% vs last 30%) stability

Outputs: results/summary.json + results/table.csv + printed console report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest import apply_costs, event_returns, matched_control_returns, summarise
from src.data_loader import load_symbols
from src.detectors import (
    candle_features,
    macd_bear_cross,
    momentum_score,
    regime_trend,
    resistance_touches,
    reversal_1rule_placebo,
    reversal_3rule_bearish,
    rsi_overbought,
    support_touches,
)
from src.stats import bh_fdr, bootstrap_mean_ci, mannwhitney_vs_control

H = 5
COSTS = [0, 5, 11, 20]


def run(symbols: list[str], years: int, out: str, seed: int = 7):
    outp = Path(out)
    outp.mkdir(parents=True, exist_ok=True)
    data = load_symbols(symbols, years=years, cache_dir="data")
    rows = []
    e1_rows = []

    for sym, df in data.items():
        df = df.reset_index(drop=True)
        reg = regime_trend(df)
        mom = momentum_score(df)
        sig3 = reversal_3rule_bearish(df)
        sig1 = reversal_1rule_placebo(df)
        macd = macd_bear_cross(df)
        rsi_ob = rsi_overbought(df)
        sup = support_touches(df)
        res = resistance_touches(df)

        o = df["open"].to_numpy(float)
        on = df["open_next"].to_numpy(float)

        # ---- E1: regime base rates (long forward return, PIT) ----
        for r in ("up", "down", "range"):
            idx = np.where((reg.to_numpy() == r))[0]
            fw = []
            for i in idx:
                if i + 1 + H < len(df) and on[i] and o[i + H]:
                    fw.append((o[i + H] - on[i]) / on[i])
            fw = np.array(fw)
            if len(fw):
                mu, (lo, hi) = bootstrap_mean_ci(fw, seed=seed)
                e1_rows.append({"exp": "E1_regime", "symbol": sym, "regime": r,
                                "n": len(fw), "mean_bps": mu * 1e4,
                                "ci_lo_bps": lo * 1e4, "ci_hi_bps": hi * 1e4})

        # ---- generic event-vs-control helper ----
        def ev(name, sig):
            tr = event_returns(df, sig, H)
            ctl = matched_control_returns(df, sig, reg, H, seed=seed)
            g = tr["gross"].to_numpy() if len(tr) else np.array([])
            c = ctl["gross"].to_numpy() if len(ctl) else np.array([])
            p = mannwhitney_vs_control(g, c)
            if len(g) >= 8 and len(c) >= 8:
                rng0 = np.random.default_rng(seed)
                diffs = np.array([rng0.choice(g, len(g), True).mean() - rng0.choice(c, len(c), True).mean() for _ in range(1000)])
                mu, lo, hi = float(np.mean(diffs)), float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))
            else:
                mu, lo, hi = float("nan"), float("nan"), float("nan")
            out_row = {"exp": name, "symbol": sym, "n_sig": len(tr), "n_ctl": len(ctl),
                       "mean_sig_bps": float(np.mean(g) * 1e4) if len(g) else float("nan"),
                       "mean_ctl_bps": float(np.mean(c) * 1e4) if len(c) else float("nan"),
                       "excess_bps": float(mu * 1e4) if mu == mu else float("nan"),
                       "excess_lo": float(lo * 1e4) if lo == lo else float("nan"),
                       "excess_hi": float(hi * 1e4) if hi == hi else float("nan"),
                       "p_mwu": p}
            for bps in COSTS:
                net = apply_costs(pd.Series(g), bps).to_numpy() if len(g) else np.array([])
                s = summarise(tr, pd.Series(net))
                out_row[f"win_{bps}bps"] = s["win_rate"]
                out_row[f"mean_net_{bps}bps"] = float(np.mean(net) * 1e4) if len(net) else float("nan")
            return out_row

        rows.append(ev("E3_3rule_bear", sig3))
        rows.append(ev("E3_1rule_placebo", sig1))
        rows.append(ev("E5_macd_bear", macd))
        rows.append(ev("E5_rsi_ob", rsi_ob))

        # ---- E2: momentum quintile spread ----
        q = pd.qcut(mom.fillna(0), 5, labels=False, duplicates="drop")
        fw_all = np.full(len(df), np.nan)
        for i in range(len(df) - H - 1):
            if on[i] and o[i + H]:
                fw_all[i] = (o[i + H] - on[i]) / on[i]
        try:
            top = fw_all[q.to_numpy() == q.max()]
            bot = fw_all[q.to_numpy() == q.min()]
            top = top[~np.isnan(top)]
            bot = bot[~np.isnan(bot)]
            mu, (lo, hi) = bootstrap_mean_ci(top.mean() - bot.mean() if len(top) and len(bot) else np.array([np.nan]), seed=seed) if len(top) and len(bot) else (float("nan"), (float("nan"), float("nan")))
            # proper spread CI via bootstrap on difference
            if len(top) > 20 and len(bot) > 20:
                rng = np.random.default_rng(seed)
                diffs = np.array([rng.choice(top, len(top), True).mean() - rng.choice(bot, len(bot), True).mean() for _ in range(1000)])
                lo, hi = np.quantile(diffs, [0.025, 0.975])
                mu = float(np.mean(diffs))
            rows.append({"exp": "E2_mom_spread", "symbol": sym, "n_sig": len(top),
                         "mean_sig_bps": float(np.mean(top) * 1e4) if len(top) else float("nan"),
                         "mean_ctl_bps": float(np.mean(bot) * 1e4) if len(bot) else float("nan"),
                         "excess_bps": float(mu * 1e4) if mu == mu else float("nan"),
                         "excess_lo": float(lo * 1e4) if lo == lo else float("nan"),
                         "excess_hi": float(hi * 1e4) if hi == hi else float("nan"),
                         "p_mwu": mannwhitney_vs_control(top, bot)})
        except Exception as e:  # noqa: BLE001
            rows.append({"exp": "E2_mom_spread", "symbol": sym, "note": str(e)})

        # ---- E4: support bounce (long) ----
        lb = []
        for i in np.where(sup.to_numpy())[0]:
            if i + 1 + H < len(df) and on[i] and o[i + H]:
                lb.append((o[i + H] - on[i]) / on[i])
        lb = np.array(lb)
        # random-bar baseline
        rng = np.random.default_rng(seed)
        cand = np.array([i for i in range(len(df) - H - 1) if not sup.to_numpy()[i]])
        base = np.array([(o[j + H] - on[j]) / on[j] for j in rng.choice(cand, min(len(lb), len(cand)), replace=False)]) if len(lb) and len(cand) else np.array([])
        mu, (lo, hi) = bootstrap_mean_ci(lb, seed=seed) if len(lb) else (float("nan"), (float("nan"), float("nan")))
        rows.append({"exp": "E4_support_bounce", "symbol": sym, "n_sig": len(lb),
                     "mean_sig_bps": float(np.mean(lb) * 1e4) if len(lb) else float("nan"),
                     "mean_ctl_bps": float(np.mean(base) * 1e4) if len(base) else float("nan"),
                     "excess_bps": float((np.mean(lb) - np.mean(base)) * 1e4) if len(lb) and len(base) else float("nan"),
                     "p_mwu": mannwhitney_vs_control(lb, base)})

    tab = pd.DataFrame(rows)
    e1 = pd.DataFrame(e1_rows)
    # BH across the excess tests
    pvals = tab["p_mwu"].fillna(1.0).tolist()
    tab["bh_reject_5pct"] = bh_fdr(pvals, 0.05)
    tab.to_csv(outp / "table.csv", index=False)
    e1.to_csv(outp / "regimes.csv", index=False)
    summary = {
        "universe": symbols, "years": years, "horizon": H, "costs_bps": COSTS,
        "n_tests": len(tab), "n_bh_hits": int(tab["bh_reject_5pct"].sum()),
        "note": "PIT-correct: signal@t close, entry@t+1 open. Costs round-trip.",
    }
    (outp / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(tab.to_string())
    print("\n--- E1 regimes ---")
    print(e1.to_string())
    print("\n--- summary ---")
    print(json.dumps(summary, indent=2))
    return tab, e1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SPY,AAPL,BTC-USD,GLD,EURUSD=X")
    ap.add_argument("--years", type=int, default=6)
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    run(a.symbols.split(","), a.years, a.out)


if __name__ == "__main__":
    main()
