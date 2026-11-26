"""Confluence score (0-100) for long swing setups.

Weights follow the checklist shown on the dashboard:
  trend 20 | RSI pullback 15 | volume behaviour 20 | consolidation 15 | relative strength 10
  pullback depth + ADX 10 | regime/event 10, plus up to +10 for bullish candles / -15 for bearish.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .patterns import PATTERN_INFO

WEIGHTS = {"trend": 20, "rsi": 15, "volume": 20, "consolidation": 15, "relative_strength": 10,
           "pullback": 10, "regime": 10}

BULL = [k for k, v in PATTERN_INFO.items() if v[0] == "bull"]
BEAR = [k for k, v in PATTERN_INFO.items() if v[0] == "bear"]


def components(ind: pd.DataFrame, pats: pd.DataFrame, regime_points: pd.Series | float = 5.0) -> pd.DataFrame:
    c = ind["close"]
    up_trend = ind["ema50"] > ind["ema200"]
    comp = pd.DataFrame(index=ind.index)

    comp["trend"] = (8 * (c > ind["ema50"]) + 7 * up_trend + 5 * (c > ind["ema20"])).astype(float)

    r, r_up = ind["rsi"], ind["rsi"] > ind["rsi"].shift(1)
    rsi_pts = np.where(up_trend & r.between(40, 55) & r_up, 15,
              np.where(up_trend & r.between(55, 65), 8,
              np.where(up_trend & r.between(35, 40) & r_up, 10,
              np.where(~up_trend & (r < 30) & r_up, 6, 0))))
    comp["rsi"] = rsi_pts.astype(float)

    quiet = ind["pullback_vol_ratio"] < 0.8
    push = (ind["ret1"] > 0) & (ind["vol_ratio"] > 1.5)
    mild = (ind["ret1"] > 0) & (ind["vol_ratio"] > 1.2)
    comp["volume"] = (10 * quiet + np.where(push, 10, np.where(mild, 5, 0))).astype(float)

    bbp = ind["bb_pctile"]
    cons = np.where(bbp < 0.2, 15, np.where(bbp < 0.35, 8, 0)) + 5 * ind["nr7"].astype(int)
    comp["consolidation"] = np.minimum(cons, 15).astype(float)

    rs = ind["rs_63"]
    comp["relative_strength"] = np.where(rs > 0.05, 10, np.where(rs > 0, 5, 0)).astype(float)

    near20 = (c / ind["ema20"] - 1).abs() < 0.03
    near50 = (c / ind["ema50"] - 1).abs() < 0.03
    comp["pullback"] = (5 * (up_trend & (near20 | near50)) + 5 * (ind["adx"] > 20)).astype(float)

    comp["regime"] = regime_points if np.isscalar(regime_points) else regime_points.reindex(ind.index).fillna(5.0)

    bull_n = pats[BULL].sum(axis=1)
    bear_n = pats[BEAR].sum(axis=1)
    comp["patterns"] = np.minimum(bull_n * 5, 10) - np.minimum(bear_n * 8, 15)
    return comp


def score(comp: pd.DataFrame) -> pd.Series:
    return comp.sum(axis=1).clip(0, 100)


def trend_label(row: pd.Series) -> str:
    if row["close"] > row["ema50"] > row["ema200"]:
        return "uptrend"
    if row["close"] < row["ema50"] < row["ema200"]:
        return "downtrend"
    return "range"


def rationale(comp_row: pd.Series, ind_row: pd.Series, patterns: list[str]) -> list[str]:
    out = []
    if comp_row["trend"] >= 15:
        out.append("Price above 20/50-EMA with 50 above 200 (uptrend)")
    if comp_row["rsi"] >= 10:
        out.append(f"RSI {ind_row['rsi']:.0f} turning up from a pullback")
    if comp_row["volume"] >= 10:
        out.append(f"Volume: quiet pullback, today {ind_row['vol_ratio']:.1f}x average")
    if comp_row["consolidation"] >= 8:
        out.append(f"Tight consolidation (Bollinger width at {ind_row['bb_pctile'] * 100:.0f}th percentile)")
    if comp_row["relative_strength"] >= 5:
        out.append(f"Outperforming benchmark by {ind_row['rs_63'] * 100:+.1f}% over 3 months")
    if comp_row["pullback"] >= 5:
        out.append(f"Pullback to moving-average support, ADX {ind_row['adx']:.0f}")
    for p in patterns:
        info = PATTERN_INFO.get(p)
        if info and info[0] == "bull":
            rate = f" (~{info[1]}% historical reversal rate)" if info[1] else ""
            out.append(f"Candle: {p.replace('_', ' ')}{rate}")
        if info and info[0] == "bear":
            out.append(f"Warning candle: {p.replace('_', ' ')}")
    return out
