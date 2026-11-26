"""Provider interfaces and a retry helper shared by all collectors."""
from __future__ import annotations

import logging
import time
from typing import Callable, Protocol, TypeVar

import pandas as pd

log = logging.getLogger("cockpit.providers")
T = TypeVar("T")

OHLCV = ["open", "high", "low", "close", "volume"]


class PriceProvider(Protocol):
    name: str

    def daily(self, symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
        """Return daily bars indexed by date with columns open, high, low, close, volume."""


class MacroProvider(Protocol):
    name: str

    def series(self, series_id: str, start: str) -> pd.Series:
        ...


def retry(fn: Callable[[], T], attempts: int = 3, base_delay: float = 1.5, what: str = "") -> T:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - providers raise anything
            last = e
            log.warning("attempt %s/%s failed for %s: %s", i + 1, attempts, what, e)
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    assert last is not None
    raise last


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names, drop empty/invalid rows and enforce high>=max(open,close)>=..>=low."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV)
    df = df.rename(columns=str.lower)
    df = df[[c for c in OHLCV if c in df.columns]].copy()
    for c in OHLCV:
        if c not in df.columns:
            df[c] = 0.0 if c == "volume" else df.get("close")
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df["volume"] = df["volume"].fillna(0)
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    return df
