"""US macro data from FRED (St. Louis Fed). Uses the API when FRED_API_KEY is set, else the public CSV."""
from __future__ import annotations

import io

import httpx
import pandas as pd

from .base import retry

# series id -> (label, unit)
FRED_SERIES = {
    "DFEDTARU": ("Fed funds target (upper)", "%"),
    "DGS10": ("US 10-yr Treasury", "%"),
    "DGS2": ("US 2-yr Treasury", "%"),
    "DFII10": ("US 10-yr real yield (TIPS)", "%"),
    "T10YIE": ("10-yr breakeven inflation", "%"),
    "CPIAUCSL": ("CPI index (SA)", "index"),
    "PCEPILFE": ("Core PCE index", "index"),
    "UNRATE": ("Unemployment rate", "%"),
}


class FredProvider:
    name = "fred"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def series(self, series_id: str, start: str) -> pd.Series:
        def _api():
            r = httpx.get("https://api.stlouisfed.org/fred/series/observations",
                          params={"series_id": series_id, "api_key": self.api_key, "file_type": "json",
                                  "observation_start": start}, timeout=20)
            r.raise_for_status()
            obs = r.json()["observations"]
            s = pd.Series({o["date"]: o["value"] for o in obs})
            return s

        def _csv():
            r = httpx.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                          params={"id": series_id, "cosd": start}, timeout=20, follow_redirects=True)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            return pd.Series(df.iloc[:, 1].values, index=df.iloc[:, 0].values)

        s = retry(_api if self.api_key else _csv, what=f"fred:{series_id}")
        s = pd.to_numeric(s.replace(".", None), errors="coerce").dropna()
        s.index = pd.to_datetime(s.index)
        return s.rename(series_id)
