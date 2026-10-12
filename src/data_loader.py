"""Live OHLC loader — Yahoo Finance v8, no API key.

Best practice (from freqtrade docs + SSRN/CSCV literature surveyed):
- point-in-time only: we store Open,High,Low,Close,Volume,Open_next
- execution is always at NEXT open (t+1), never at signal close (t)
- deterministic on-disk cache under ./data to make runs reproducible
- multi-asset universe to avoid single-ticker survivorship storytelling
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) price-action-evidence-lab/1.0"}

PERIOD1_2020 = 1577836800  # 2020-01-01 UTC


def _yahoo_daily(symbol: str, period1: int, period2: int) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1d", "period1": period1, "period2": period2, "includePrePost": "false"}
    last_err = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        for attempt in range(3):
            try:
                r = requests.get(
                    url.replace("query1.finance.yahoo.com", host),
                    params=params,
                    headers=UA,
                    timeout=30,
                )
                r.raise_for_status()
                js = r.json()
                res = js["chart"]["result"][0]
                ts = res["timestamp"]
                q = res["indicators"]["quote"][0]
                adj = None
                if "adjclose" in res["indicators"]:
                    try:
                        adj = res["indicators"]["adjclose"][0]["adjclose"]
                    except Exception:
                        adj = None
                df = pd.DataFrame(
                    {
                        "time": pd.to_datetime(ts, unit="s", utc=True),
                        "open": q["open"],
                        "high": q["high"],
                        "low": q["low"],
                        "close": q["close"],
                        "volume": q.get("volume", [None] * len(ts)),
                    }
                )
                if adj is not None:
                    df["adjclose"] = adj
                df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
                df["symbol"] = symbol
                return df
            except Exception as e:  # noqa: BLE001 - retry then raise
                last_err = e
                time.sleep(2 + attempt * 2)
    raise RuntimeError(f"Yahoo fetch failed for {symbol}: {last_err}")


def load_symbols(symbols: list[str], years: int = 6, cache_dir: str | Path = "data") -> dict[str, pd.DataFrame]:
    """Fetch `years` of daily bars ending now. Returns {symbol: df} with PIT columns."""
    import datetime as dt

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    period1 = now - int(years * 365.25 * 86400)
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        safe = sym.replace("=", "_EQ_").replace("-", "_D_")
        fp = cache / f"{safe}_{years}y.parquet"
        csv_fp = cache / f"{safe}_{years}y.csv"
        df = None
        if fp.exists():
            try:
                df = pd.read_parquet(fp)
            except Exception:
                df = None
        if df is None or df.empty:
            print(f"[data] fetching {sym} ({years}y) from Yahoo v8 ...", flush=True)
            df = _yahoo_daily(sym, period1, now)
            try:
                df.to_parquet(fp, index=False)
            except Exception:
                df.to_csv(csv_fp, index=False)
        # PIT execution column: next open (what a live trader could actually trade)
        df = df.sort_values("time").reset_index(drop=True)
        df["open_next"] = df["open"].shift(-1)
        out[sym] = df
        print(f"[data] {sym}: {len(df)} bars {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}", flush=True)
    return out


if __name__ == "__main__":
    import sys

    syms = sys.argv[1:] or ["SPY", "AAPL", "BTC-USD", "GLD", "EURUSD=X"]
    load_symbols(syms, years=6, cache_dir="data")
