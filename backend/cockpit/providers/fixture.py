"""Deterministic synthetic data for tests, CI and offline demos (COCKPIT_PROVIDER=fixture).

Series are random walks seeded by the symbol, anchored so the last close lands near a realistic
level. They are NOT real prices: the dashboard labels fixture mode clearly.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

ANCHORS = {
    "^GSPC": 7180, "^NDX": 26000, "^DJI": 50180, "^RUT": 2700, "RSP": 190, "^VIX": 28, "^NSEI": 25880,
    "^BSESN": 84330, "^NSEBANK": 58000, "^INDIAVIX": 15, "GC=F": 3570, "SI=F": 41, "BZ=F": 93,
    "CL=F": 83, "DX-Y.NYB": 103.7, "INR=X": 88.5, "^TNX": 4.8,
}
VOL = {"^VIX": 0.06, "^INDIAVIX": 0.05, "^TNX": 0.02, "DX-Y.NYB": 0.004, "INR=X": 0.003}


def _seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)


class FixtureProvider:
    name = "fixture"

    def __init__(self, end: str | None = None):
        self.end = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()

    def daily(self, symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
        end_ts = pd.Timestamp(end) if end else self.end
        idx = pd.bdate_range(pd.Timestamp(start), end_ts)
        n = len(idx)
        if n == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        rng = np.random.default_rng(_seed(symbol))
        vol = VOL.get(symbol, 0.012 + (_seed(symbol) % 100) / 10000)
        # Regime-switching drift produces trends, pullbacks and consolidations.
        drift = np.repeat(rng.normal(0.0004, 0.0015, size=n // 40 + 1), 40)[:n]
        rets = rng.normal(drift, vol)
        path = np.exp(np.cumsum(rets))
        anchor = ANCHORS.get(symbol, 50 + _seed(symbol) % 3000)
        close = anchor * path / path[-1]
        open_ = close * (1 + rng.normal(0, vol / 3, n))
        span = np.abs(rng.normal(vol * 0.8, vol / 3, n)) * close
        high = np.maximum(open_, close) + span / 2
        low = np.minimum(open_, close) - span / 2
        base_vol = 1e6 * (1 + _seed(symbol) % 50)
        volume = base_vol * np.exp(rng.normal(0, 0.35, n)) * (1 + 8 * np.abs(rets))
        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
        return df


class FixtureMacro:
    name = "fixture"

    LEVELS = {"CPIAUCSL": 330.0, "PCEPILFE": 128.0, "DFEDTARU": 4.0, "DGS10": 4.8, "DGS2": 4.65,
              "DFII10": 2.3, "T10YIE": 2.5, "UNRATE": 4.1}

    def series(self, series_id: str, start: str) -> pd.Series:
        monthly = series_id in {"CPIAUCSL", "PCEPILFE", "UNRATE"}
        idx = pd.date_range(start, pd.Timestamp.today(), freq="MS" if monthly else "B")
        rng = np.random.default_rng(_seed(series_id))
        lvl = self.LEVELS.get(series_id, 1.0)
        if monthly and series_id != "UNRATE":
            vals = lvl / np.cumprod(np.full(len(idx), 1.003))[::-1]
        else:
            vals = lvl + np.cumsum(rng.normal(0, 0.02, len(idx)))
            vals = vals - vals[-1] + lvl
        return pd.Series(vals, index=idx, name=series_id)
