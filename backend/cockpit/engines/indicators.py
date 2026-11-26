"""Vectorised technical indicators on a daily OHLCV frame."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=min(n, len(s))).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    out = out.mask((dn == 0) & (up > 0), 100.0).mask((up == 0) & (dn > 0), 0.0)
    return out.fillna(50)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean().fillna(0)


def bb_width_pctile(close: pd.Series, n: int = 20, lookback: int = 126) -> pd.Series:
    """Bollinger band width as a percentile of its own recent history (0 = tightest)."""
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    width = (4 * sd) / mid
    return width.rolling(lookback, min_periods=40).rank(pct=True)


def compute(df: pd.DataFrame, bench: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return df with indicator columns appended."""
    out = df.copy()
    c = out["close"]
    out["ema20"] = ema(c, 20)
    out["ema50"] = ema(c, 50)
    out["ema200"] = ema(c, 200)
    out["rsi"] = rsi(c)
    out["atr"] = atr(out)
    out["atr_pct"] = out["atr"] / c
    out["adx"] = adx(out)
    vol20 = out["volume"].rolling(20, min_periods=5).mean()
    out["vol_ratio"] = (out["volume"] / vol20.replace(0, np.nan)).fillna(1.0)
    down = c < c.shift()
    pull_vol = out["volume"].where(down).rolling(5, min_periods=1).mean()
    out["pullback_vol_ratio"] = (pull_vol / vol20.replace(0, np.nan)).fillna(1.0)
    out["bb_pctile"] = bb_width_pctile(c).fillna(0.5)
    rng = out["high"] - out["low"]
    out["nr7"] = rng <= rng.rolling(7).min()
    out["low10"] = out["low"].rolling(10).min()
    out["high252"] = out["high"].rolling(252, min_periods=20).max()
    out["dist_high"] = c / out["high252"] - 1
    out["ret1"] = c.pct_change()
    out["ret63"] = c.pct_change(63)
    if bench is not None and not bench.empty:
        b = bench["close"].reindex(out.index).ffill()
        out["rs_63"] = out["ret63"] - b.pct_change(63)
    else:
        out["rs_63"] = out["ret63"]
    out["rs_63"] = out["rs_63"].fillna(0)
    return out
