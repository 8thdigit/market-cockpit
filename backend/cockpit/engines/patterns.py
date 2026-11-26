"""Candlestick pattern detection (vectorised). Each detector returns a boolean Series.

Reversal rates are from Thomas Bulkowski's published tests (Encyclopedia of Candlestick Charts);
they describe how often price moved the expected way, not how often a trade was profitable.
"""
from __future__ import annotations

import pandas as pd

# name -> (direction, Bulkowski reversal/continuation rate %, short description)
PATTERN_INFO = {
    "three_line_strike_bull": ("bull", 84, "Three falling candles fully engulfed by one rising candle"),
    "three_white_soldiers": ("bull", 82, "Three strong rising closes after a decline"),
    "morning_star": ("bull", 78, "Down candle, small-body star, strong up candle"),
    "bullish_engulfing": ("bull", 63, "Up body engulfs prior down body after a decline"),
    "hammer": ("bull", 60, "Long lower shadow at a low"),
    "selling_climax": ("bull", None, "High-volume flush near lows closing off the low"),
    "inside_bar": ("neutral", None, "Range inside the prior bar (pause)"),
    "nr7": ("neutral", None, "Narrowest range of 7 sessions (volatility contraction)"),
    "three_black_crows": ("bear", 78, "Three strong falling closes after a rise"),
    "evening_star": ("bear", 72, "Up candle, small-body star, strong down candle"),
    "bearish_engulfing": ("bear", 79, "Down body engulfs prior up body after a rise"),
    "shooting_star": ("bear", 59, "Long upper shadow at a high"),
}


def detect(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, 1e-12)
    up, dn = c > o, c < o
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    lower = pd.concat([o, c], axis=1).min(axis=1) - l
    avg_body = body.rolling(10, min_periods=3).mean()
    downtrend = c.shift(1) < c.shift(6)
    uptrend = c.shift(1) > c.shift(6)
    vol_ratio = df["volume"] / df["volume"].rolling(20, min_periods=5).mean()

    p = pd.DataFrame(index=df.index)
    p["bullish_engulfing"] = downtrend & dn.shift(1) & up & (c >= o.shift(1)) & (o <= c.shift(1)) & (body > body.shift(1))
    p["bearish_engulfing"] = uptrend & up.shift(1) & dn & (o >= c.shift(1)) & (c <= o.shift(1)) & (body > body.shift(1))
    p["hammer"] = downtrend & (lower >= 2 * body) & (upper <= 0.3 * body + 0.1 * rng) & (body > 0.05 * rng)
    p["shooting_star"] = uptrend & (upper >= 2 * body) & (lower <= 0.3 * body + 0.1 * rng) & (body > 0.05 * rng)
    star_small = body.shift(1) < 0.4 * avg_body.shift(1)
    p["morning_star"] = (dn.shift(2) & (body.shift(2) > avg_body.shift(2)) & star_small & up
                         & (c > (o.shift(2) + c.shift(2)) / 2) & downtrend.shift(1, fill_value=False))
    p["evening_star"] = (up.shift(2) & (body.shift(2) > avg_body.shift(2)) & star_small & dn
                         & (c < (o.shift(2) + c.shift(2)) / 2) & uptrend.shift(1, fill_value=False))
    rising = up & (c > c.shift(1)) & (body > 0.6 * rng) & (upper < 0.25 * body + 0.05 * rng)
    falling = dn & (c < c.shift(1)) & (body > 0.6 * rng) & (lower < 0.25 * body + 0.05 * rng)
    p["three_white_soldiers"] = rising & rising.shift(1, fill_value=False) & rising.shift(2, fill_value=False) & (c.shift(3) < c.shift(8))
    p["three_black_crows"] = falling & falling.shift(1, fill_value=False) & falling.shift(2, fill_value=False) & (c.shift(3) > c.shift(8))
    three_down = dn.shift(1) & dn.shift(2) & dn.shift(3) & (c.shift(1) < c.shift(2)) & (c.shift(2) < c.shift(3))
    p["three_line_strike_bull"] = three_down & up & (o <= c.shift(1)) & (c >= o.shift(3))
    p["selling_climax"] = (vol_ratio > 2.0) & (c < c.shift(1)) & ((c - l) / rng > 0.4) & (c <= c.rolling(20).min() * 1.03)
    p["inside_bar"] = (h < h.shift(1)) & (l > l.shift(1))
    p["nr7"] = (h - l) <= (h - l).rolling(7).min()
    return p.fillna(False).astype(bool)


def active(p: pd.DataFrame, i: int = -1) -> list[str]:
    row = p.iloc[i]
    return [k for k, v in row.items() if v]
