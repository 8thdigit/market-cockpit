"""Macro regime engine: turns cross-asset conditions into a 0-100 risk score per day.

>= 60 Risk-on, 40-60 Neutral, < 40 Risk-off. Each component contributes -2..+2 points; the sum is
rescaled to 0-100. The components and their current reading are stored for the dashboard.
"""
from __future__ import annotations

import pandas as pd

from .indicators import ema


def _vs_ma(close: pd.Series, n: int) -> pd.Series:
    return (close > close.rolling(n, min_periods=max(10, n // 3)).mean()).astype(int) * 2 - 1


def compute(closes: dict[str, pd.Series], macro: dict[str, pd.Series], sentiment: pd.Series | None = None) -> pd.DataFrame:
    """closes: symbol -> close Series. macro: FRED series. Returns frame: score, label, per-component points."""
    idx = None
    for s in closes.values():
        idx = s.index if idx is None else idx.union(s.index)
    if idx is None:
        return pd.DataFrame(columns=["score", "label"])
    comp = pd.DataFrame(index=idx)

    def get(sym):
        s = closes.get(sym)
        return s.reindex(idx).ffill() if s is not None else None

    spx, ndx, nifty = get("^GSPC"), get("^NDX"), get("^NSEI")
    vix, ivix, dxy, tnx = get("^VIX"), get("^INDIAVIX"), get("DX-Y.NYB"), get("^TNX")
    if spx is not None:
        comp["us_trend"] = _vs_ma(spx, 50)
    if ndx is not None:
        comp["tech_trend"] = _vs_ma(ndx, 200)
    if nifty is not None:
        comp["india_trend"] = _vs_ma(nifty, 50)
    if vix is not None:
        comp["vix"] = pd.cut(vix, [-1, 15, 20, 25, 30, 1e9], labels=[2, 1, 0, -1, -2]).astype(float)
    if ivix is not None:
        comp["india_vix"] = pd.cut(ivix, [-1, 12, 16, 20, 1e9], labels=[1, 0.5, 0, -1]).astype(float)
    if dxy is not None:
        comp["dollar"] = -((dxy > ema(dxy, 50)).astype(int) * 2 - 1)  # strong dollar = risk-off for EM/gold
    if tnx is not None:
        chg = tnx - tnx.shift(20)
        comp["yields"] = pd.cut(chg, [-1e9, -0.25, -0.05, 0.05, 0.25, 1e9], labels=[2, 1, 0, -1, -2]).astype(float)
    fed = macro.get("DFEDTARU")
    if fed is not None and not fed.empty:
        f = fed.reindex(idx.union(fed.index)).ffill().reindex(idx)
        d = f - f.shift(63)
        comp["fed"] = pd.cut(d, [-1e9, -0.1, 0.1, 1e9], labels=[2, 0, -2]).astype(float)
    if sentiment is not None and not sentiment.empty:
        s = sentiment.reindex(idx).fillna(0).rolling(3, min_periods=1).mean()
        comp["news"] = (s * 4).clip(-2, 2)
    comp = comp.fillna(0)
    n = max(len(comp.columns), 1)
    comp["score"] = ((comp.sum(axis=1) + 2 * n) / (4 * n) * 100).round(1)
    comp["label"] = pd.cut(comp["score"], [-1, 40, 60, 101], labels=["Risk-off", "Neutral", "Risk-on"]).astype(str)
    return comp


def points_for_scoring(label: str) -> float:
    return {"Risk-on": 10.0, "Neutral": 5.0, "Risk-off": 0.0}.get(label, 5.0)
