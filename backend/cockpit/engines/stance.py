"""Daily recommendation ("stance") per watched asset, and its outcome after N trading days.

Stances:
  BUY              long setup score >= 70: entry now, stop/target from ATR
  SELL             short setup score >= 70 (commodities): entry now, stop/target from ATR
  ACCUMULATE DIPS  uptrend and history leans up, but no trigger yet: buy zone near the 20-EMA
  SELL RALLIES     downtrend and history leans down: sell zone near the 20-EMA
  WAIT             signals disagree: no position
Each directional stance is scored after `HORIZON` trading days: met if price moved its way.
"""
from __future__ import annotations

import pandas as pd

HORIZON = 5
DIR = {"BUY": 1, "ACCUMULATE DIPS": 1, "SELL": -1, "SELL RALLIES": -1, "WAIT": 0}


def decide(sym: str, name: str, row: pd.Series, long_score: float | None, short_score: float | None,
           expect: dict | None, regime_label: str, min_score: float, rr: float) -> dict:
    close, atr, ema20 = float(row["close"]), float(row["atr"]), float(row["ema20"])
    trend = "uptrend" if row["close"] > row["ema50"] > row["ema200"] else "downtrend" if row["close"] < row["ema50"] < row["ema200"] else "range"
    p_up = (expect or {}).get("prob_up_5d", 0.5)
    why = []
    ls, ss = long_score or 0, short_score or 0
    if ls >= min_score and ls >= ss:
        stance = "BUY"
        stop = close - 1.5 * atr
        target = close + rr * (close - stop)
        entry = [close, close]
        why.append(f"Long setup score {ls:.0f}/100 (trigger present)")
    elif ss >= min_score:
        stance = "SELL"
        stop = close + 1.5 * atr
        target = close - rr * (stop - close)
        entry = [close, close]
        why.append(f"Short setup score {ss:.0f}/100 (trigger present)")
    elif trend == "uptrend" and p_up >= 0.5:
        stance = "ACCUMULATE DIPS"
        entry = [ema20 - 0.5 * atr, ema20 + 0.25 * atr]
        stop = entry[0] - 1.5 * atr
        target = entry[1] + rr * 1.5 * atr
        why.append("Uptrend intact (price above 50- and 200-day averages)")
    elif trend == "downtrend" and p_up <= 0.5:
        stance = "SELL RALLIES"
        entry = [ema20 - 0.25 * atr, ema20 + 0.5 * atr]
        stop = entry[1] + 1.5 * atr
        target = entry[0] - rr * 1.5 * atr
        why.append("Downtrend intact (price below 50- and 200-day averages)")
    else:
        stance, entry, stop, target = "WAIT", None, None, None
        why.append(f"Trend is {trend} and signals disagree; no edge")
    why.append(f"RSI {row['rsi']:.0f}; 20-day average at {ema20:,.2f}")
    if expect and expect.get("analog5"):
        a = expect["analog5"]
        why.append(f"In the {a['n']} most similar past setups, it rose over the next 5 days {a['pct_up'] * 100:.0f}% "
                   f"of the time (median {a['median']:+.1f}%)")
    why.append(f"Macro regime: {regime_label}")
    agree = (DIR[stance] > 0 and p_up >= 0.55) or (DIR[stance] < 0 and p_up <= 0.45)
    conflict = (DIR[stance] > 0 and p_up <= 0.4) or (DIR[stance] < 0 and p_up >= 0.6)
    if conflict:
        why.append("Caution: historical analogs lean the other way")
    conf = 0.5 + (0.1 if agree else 0) - (0.1 if conflict else 0) + (0.05 if stance in ("BUY", "SELL") else 0)
    return {"symbol": sym, "name": name, "stance": stance, "direction": DIR[stance], "trend": trend,
            "close": close, "entry": entry, "stop": stop, "target": target, "long_score": ls, "short_score": ss,
            "prob_up_5d": p_up, "confidence": round(conf, 2), "rationale": why,
            "range5": (expect or {}).get("range5")}


def outcome(close_series: pd.Series, date: str, direction: int) -> dict | None:
    """Return outcome after HORIZON bars, or None if the window hasn't closed."""
    s = close_series.dropna()
    ts = pd.Timestamp(date)
    if ts not in s.index:
        return None
    i = s.index.get_loc(ts)
    if i + HORIZON >= len(s):
        return None
    ret = float(s.iloc[i + HORIZON] / s.iloc[i] - 1) * 100
    if direction == 0:
        res = "n/a"
    else:
        res = "met" if ret * direction > 0 else "failed"
    return {"ret_5d": ret, "outcome": res, "checked_on": s.index[i + HORIZON].date().isoformat()}
