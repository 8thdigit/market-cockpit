"""Live prices: Yahoo Finance (via yfinance) with Stooq as a fallback."""
from __future__ import annotations

import io
import logging

import httpx
import pandas as pd

from .base import clean_bars, retry

log = logging.getLogger("cockpit.providers.yahoo")

# Stooq symbol mapping for the fallback (covers US equities/ETFs and a few macro series).
STOOQ_MAP = {
    "^GSPC": "^spx", "^NDX": "^ndx", "^DJI": "^dji", "GC=F": "gc.f", "SI=F": "si.f",
    "CL=F": "cl.f", "BZ=F": "cb.f", "DX-Y.NYB": "dx.f", "^VIX": "vi.f", "INR=X": "usdinr",
}


class YahooProvider:
    name = "yahoo"

    def daily(self, symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
        import yfinance as yf  # imported lazily so tests don't need network libs initialised

        def _get():
            df = yf.Ticker(symbol).history(start=start, end=end, interval="1d", auto_adjust=False,
                                           actions=False, raise_errors=True)
            if df is None or df.empty:
                raise ValueError(f"no data for {symbol}")
            return df

        try:
            return clean_bars(retry(_get, what=f"yahoo:{symbol}"))
        except Exception as e:  # noqa: BLE001
            log.warning("yahoo failed for %s (%s); trying stooq", symbol, e)
            return StooqProvider().daily(symbol, start, end)


class StooqProvider:
    name = "stooq"

    def _sym(self, symbol: str) -> str | None:
        if symbol in STOOQ_MAP:
            return STOOQ_MAP[symbol]
        if symbol.endswith(".NS") or symbol.startswith("^"):
            return None
        return symbol.lower().replace(".", "-") + ".us"

    def daily(self, symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
        s = self._sym(symbol)
        if not s:
            raise ValueError(f"no stooq mapping for {symbol}")
        url = f"https://stooq.com/q/d/l/?s={s}&i=d&d1={start.replace('-', '')}"
        if end:
            url += f"&d2={end.replace('-', '')}"

        def _get():
            r = httpx.get(url, timeout=20)
            r.raise_for_status()
            if not r.text.startswith("Date"):
                raise ValueError(f"stooq returned no data for {symbol}")
            return pd.read_csv(io.StringIO(r.text), index_col="Date", parse_dates=True)

        return clean_bars(retry(_get, what=f"stooq:{symbol}"))
