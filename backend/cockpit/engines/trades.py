"""Trade geometry, outcome simulation and score-bucket calibration.

The same rules are used for live picks, outcome tracking and the historical calibration, so the
confidence shown on a pick is the measured hit-rate of comparable past setups, not a guess.
"""
from __future__ import annotations

import pandas as pd

BUCKETS = [(90, 101, "90+"), (80, 90, "80-89"), (70, 80, "70-79")]


def bucket(score: float) -> str | None:
    for lo, hi, name in BUCKETS:
        if lo <= score < hi:
            return name
    return None


def levels(close: float, atr: float, low10: float | None, rr: float) -> tuple[float, float]:
    """Stop at 1.5 ATR below entry (or just under the 10-day low if that is tighter but >0.8 ATR)."""
    stop = close - 1.5 * atr
    if low10 is not None and pd.notna(low10):
        alt = low10 - 0.1 * atr
        if close - alt >= 0.8 * atr and alt > stop:
            stop = alt
    target = close + rr * (close - stop)
    return round(stop, 4), round(target, 4)


def simulate(bars: pd.DataFrame, entry: float, stop: float, target: float, max_days: int):
    """Walk forward through bars after entry. Returns (status, exit_date, exit_price, r_multiple) or None if still open.

    A bar touching both stop and target counts as a stop (conservative)."""
    risk = entry - stop
    if risk <= 0:
        return ("invalid", None, None, 0.0)
    for i, (dt, b) in enumerate(bars.iterrows()):
        if b["low"] <= stop:
            px = min(stop, b["open"]) if b["open"] < stop else stop
            return ("stopped", dt, px, (px - entry) / risk)
        if b["high"] >= target:
            px = max(target, b["open"]) if b["open"] > target else target
            return ("target", dt, px, (px - entry) / risk)
        if i + 1 >= max_days:
            return ("expired", dt, b["close"], (b["close"] - entry) / risk)
    return None


def calibrate(ind: pd.DataFrame, score: pd.Series, rr: float, max_days: int, min_score: float = 70) -> list[dict]:
    """Historical trades where score first crosses into a bucket. Returns per-trade results."""
    trades = []
    s = score
    entry_sig = (s >= min_score) & (s.shift(1) < min_score)
    idxs = [i for i, flag in enumerate(entry_sig.values) if flag and i >= 200]
    busy_until = -1
    for i in idxs:
        if i <= busy_until or i + 1 >= len(ind):
            continue
        row = ind.iloc[i]
        if pd.isna(row["atr"]) or row["atr"] <= 0:
            continue
        stop, target = levels(row["close"], row["atr"], row.get("low10"), rr)
        res = simulate(ind.iloc[i + 1:i + 1 + max_days], row["close"], stop, target, max_days)
        if res is None:
            continue  # not finished yet; excluded
        status, dt, _, r = res
        trades.append({"date": ind.index[i], "score": float(s.iloc[i]), "bucket": bucket(float(s.iloc[i])),
                       "status": status, "r": float(r), "win": r > 0})
        busy_until = ind.index.get_loc(dt) if dt is not None else i
    return trades


def summarise(trades: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    df = pd.DataFrame(trades)
    if df.empty:
        return out
    for b, g in df.groupby("bucket"):
        n, w = len(g), int(g["win"].sum())
        out[b] = {"trades": n, "wins": w, "hit_rate": w / n, "avg_r": float(g["r"].mean()),
                  "confidence": (w + 5) / (n + 10),  # shrunk toward 50% for small samples
                  "expected_r": float(g["r"].sum()) / (n + 10)}  # avg R shrunk toward 0
    return out
