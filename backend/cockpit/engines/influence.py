"""Influencer movements, 'what history says', nearest-analog days and next-days expectations.

All statistics for an as-of date use only data available on that date (forward returns are only
counted where the forward window had already closed), so replaying a past date is honest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGETS = {"GC=F": "Gold", "BZ=F": "Brent", "^GSPC": "S&P 500", "^NSEI": "Nifty 50"}
EXPECT_ASSETS = ["GC=F", "SI=F", "BZ=F", "CL=F", "^GSPC", "^NDX", "^NSEI", "^BSESN", "DX-Y.NYB", "INR=X", "^TNX"]
HORIZONS = (5, 10, 20)

# driver id -> definition. kind: pct = % change over `n` days, bp = change in yield points*100, level
DRIVERS = [
    {"id": "fed", "name": "Fed policy rate", "series": "DFEDTARU", "kind": "chg", "n": 63, "unit": "%", "src": "macro",
     "up": "hiking", "down": "cutting", "thr": 0.1,
     "impact_up": {"gold": -1, "oil": -1, "us": -1, "india": -1}, "impact_down": {"gold": 1, "oil": 1, "us": 1, "india": 1}},
    {"id": "inflation", "name": "US inflation (CPI y/y)", "series": "CPIAUCSL", "kind": "yoy_chg", "unit": "%", "src": "macro",
     "up": "accelerating", "down": "cooling", "thr": 0.1,
     "impact_up": {"gold": 0, "oil": 0, "us": -1, "india": -1}, "impact_down": {"gold": 1, "oil": 0, "us": 1, "india": 1}},
    {"id": "yields", "name": "US 10-yr yield", "series": "^TNX", "kind": "bp", "n": 20, "unit": "bp", "src": "price",
     "up": "rising", "down": "falling", "thr": 10,
     "impact_up": {"gold": -1, "oil": 0, "us": -1, "india": -1}, "impact_down": {"gold": 1, "oil": 0, "us": 1, "india": 1}},
    {"id": "real_yield", "name": "US 10-yr real yield", "series": "DFII10", "kind": "bp_macro", "n": 20, "unit": "bp", "src": "macro",
     "up": "rising", "down": "falling", "thr": 10,
     "impact_up": {"gold": -1, "oil": 0, "us": -1, "india": 0}, "impact_down": {"gold": 1, "oil": 0, "us": 1, "india": 0}},
    {"id": "dollar", "name": "US dollar index", "series": "DX-Y.NYB", "kind": "pct", "n": 20, "unit": "%", "src": "price",
     "up": "strengthening", "down": "weakening", "thr": 1.0,
     "impact_up": {"gold": -1, "oil": -1, "us": -1, "india": -1}, "impact_down": {"gold": 1, "oil": 1, "us": 1, "india": 1}},
    {"id": "oil", "name": "Brent crude", "series": "BZ=F", "kind": "pct", "n": 20, "unit": "%", "src": "price",
     "up": "rising", "down": "falling", "thr": 5.0,
     "impact_up": {"gold": 1, "oil": 1, "us": 0, "india": -1}, "impact_down": {"gold": -1, "oil": -1, "us": 0, "india": 1}},
    {"id": "gold", "name": "Gold", "series": "GC=F", "kind": "pct", "n": 20, "unit": "%", "src": "price",
     "up": "rising", "down": "falling", "thr": 3.0,
     "impact_up": {"gold": 1, "oil": 0, "us": 0, "india": 0}, "impact_down": {"gold": -1, "oil": 0, "us": 0, "india": 0}},
    {"id": "vix", "name": "Volatility (VIX)", "series": "^VIX", "kind": "level", "unit": "", "src": "price",
     "up": "fearful", "down": "calm", "thr_hi": 22, "thr_lo": 16,
     "impact_up": {"gold": 0, "oil": -1, "us": -1, "india": -1}, "impact_down": {"gold": 0, "oil": 0, "us": 1, "india": 1}},
    {"id": "rupee", "name": "USD/INR", "series": "INR=X", "kind": "pct", "n": 20, "unit": "%", "src": "price",
     "up": "rupee weakening", "down": "rupee strengthening", "thr": 0.8,
     "impact_up": {"gold": 0, "oil": 0, "us": 0, "india": -1}, "impact_down": {"gold": 0, "oil": 0, "us": 0, "india": 1}},
    {"id": "geopolitics", "name": "Geopolitics (news tone)", "series": "sent_geopolitics", "kind": "sent", "unit": "", "src": "macro",
     "up": "calmer headlines", "down": "escalation headlines", "thr": 0.08,
     "impact_up": {"gold": -1, "oil": -1, "us": 1, "india": 1}, "impact_down": {"gold": 1, "oil": 1, "us": -1, "india": -1}},
]

ANALOG_FEATURES = ["dollar", "yields", "oil", "gold", "vix", "fed", "spx_trend", "nifty_trend"]


def driver_series(d: dict, closes: dict[str, pd.Series], macro: dict[str, pd.Series], idx: pd.DatetimeIndex) -> pd.Series | None:
    src = closes if d["src"] == "price" else macro
    s = src.get(d["series"])
    if s is None or s.dropna().empty:
        return None
    s = s.reindex(s.index.union(idx)).ffill().reindex(idx)
    k = d["kind"]
    if k == "pct":
        return (s / s.shift(d["n"]) - 1) * 100
    if k == "bp":  # ^TNX is quoted in percent
        return (s - s.shift(d["n"])) * 100
    if k == "bp_macro":
        return (s - s.shift(d["n"])) * 100
    if k == "chg":
        return s - s.shift(d["n"])
    if k == "yoy_chg":
        yoy = (s / s.shift(252) - 1) * 100
        return yoy - yoy.shift(21)
    if k == "sent":
        return s.rolling(3, min_periods=1).mean()
    return s  # level


def driver_level(d: dict, closes, macro, idx) -> pd.Series | None:
    src = closes if d["src"] == "price" else macro
    s = src.get(d["series"])
    if s is None or s.dropna().empty:
        return None
    s = s.reindex(s.index.union(idx)).ffill().reindex(idx)
    if d["kind"] == "yoy_chg":
        return (s / s.shift(252) - 1) * 100
    if d["kind"] == "sent":
        return s.rolling(3, min_periods=1).mean()
    return s


def direction(d: dict, v: float) -> int:
    if v is None or np.isnan(v):
        return 0
    if d["kind"] == "level":
        return 1 if v >= d["thr_hi"] else (-1 if v <= d["thr_lo"] else 0)
    return 1 if v >= d["thr"] else (-1 if v <= -d["thr"] else 0)


def direction_series(d: dict, s: pd.Series) -> pd.Series:
    if d["kind"] == "level":
        return pd.Series(np.where(s >= d["thr_hi"], 1, np.where(s <= d["thr_lo"], -1, 0)), index=s.index).where(s.notna())
    return pd.Series(np.where(s >= d["thr"], 1, np.where(s <= -d["thr"], -1, 0)), index=s.index).where(s.notna())


def forward_returns(closes: dict[str, pd.Series], idx: pd.DatetimeIndex) -> dict[str, dict[int, pd.Series]]:
    out = {}
    for sym in set(TARGETS) | set(EXPECT_ASSETS):
        s = closes.get(sym)
        if s is None:
            continue
        s = s.reindex(idx).ffill()
        out[sym] = {h: (s.shift(-h) / s - 1) * 100 for h in HORIZONS}
    return out


def _stats(vals: pd.Series) -> dict | None:
    vals = vals.dropna()
    if len(vals) < 5:
        return None
    return {"n": int(len(vals)), "avg": float(vals.mean()), "median": float(vals.median()),
            "pct_up": float((vals > 0).mean()), "p10": float(vals.quantile(0.1)), "p90": float(vals.quantile(0.9))}


class Context:
    """Precomputed series reused for every as-of date in a run."""

    def __init__(self, closes: dict[str, pd.Series], macro: dict[str, pd.Series]):
        idx = None
        for sym in ("^GSPC", "GC=F", "DX-Y.NYB", "^NSEI"):
            if sym in closes:
                idx = closes[sym].index if idx is None else idx.union(closes[sym].index)
        self.idx = idx if idx is not None else pd.DatetimeIndex([])
        self.closes = {k: v.reindex(self.idx).ffill() for k, v in closes.items()}
        self.macro = macro
        self.drv = {}
        self.lvl = {}
        for d in DRIVERS:
            s = driver_series(d, closes, macro, self.idx)
            if s is not None:
                self.drv[d["id"]] = s
                self.lvl[d["id"]] = driver_level(d, closes, macro, self.idx)
        self.fwd = forward_returns(closes, self.idx)
        feats = {k: self.drv[k] for k in ANALOG_FEATURES if k in self.drv}
        for sym, key in (("^GSPC", "spx_trend"), ("^NSEI", "nifty_trend")):
            s = self.closes.get(sym)
            if s is not None:
                feats[key] = (s / s.rolling(50, min_periods=20).mean() - 1) * 100
        self.features = pd.DataFrame(feats)
        self.daily_vol = {k: (v.pct_change().rolling(20, min_periods=10).std() * 100) for k, v in self.closes.items()}


def _known(ts: pd.Timestamp, h: int, idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Dates whose h-day forward window had closed by ts."""
    pos = idx.get_indexer([ts], method="pad")[0]
    if pos < 0:
        return idx[:0]
    return idx[: max(0, pos - h + 1)]


def influencers(ctx: Context, date: str) -> list[dict]:
    ts = pd.Timestamp(date)
    out = []
    for d in DRIVERS:
        s = ctx.drv.get(d["id"])
        if s is None or ts not in s.index or pd.isna(s.loc[ts]):
            continue
        v = float(s.loc[ts])
        lvl = ctx.lvl[d["id"]]
        level = float(lvl.loc[ts]) if pd.notna(lvl.loc[ts]) else None
        hist = s.loc[:ts].dropna().tail(756)
        pctile = float((hist < v).mean()) if len(hist) > 20 else None
        dr = direction(d, v)
        spark = [{"date": i.date().isoformat(), "value": float(x)} for i, x in lvl.loc[:ts].dropna().tail(120).items()]
        prev5 = s.loc[:ts].dropna()
        trend5 = float(v - prev5.iloc[-6]) if len(prev5) > 6 else None
        # What history says: forward moves of target assets when this driver was in the same state.
        known = _known(ts, 10, ctx.idx)
        dirs = direction_series(d, s.reindex(known))
        same = dirs[dirs == dr].index
        hist_says = {}
        for sym, name in TARGETS.items():
            f = ctx.fwd.get(sym)
            if f is None:
                continue
            st = _stats(f[10].reindex(same))
            if st:
                hist_says[sym] = dict(st, name=name)
        impact = d["impact_up"] if dr > 0 else d["impact_down"] if dr < 0 else {k: 0 for k in d["impact_up"]}
        out.append({
            "id": d["id"], "name": d["name"], "level": level, "signal": v, "unit": d["unit"], "kind": d["kind"],
            "window": d.get("n"), "direction": dr,
            "state": d["up"] if dr > 0 else d["down"] if dr < 0 else "neutral",
            "percentile": pctile, "trend_5d": trend5, "impact": impact, "history_says": hist_says,
            "history_n": int(len(same)), "spark": spark,
        })
    return out


def analogs(ctx: Context, date: str, k: int = 15, min_gap: int = 15) -> dict:
    ts = pd.Timestamp(date)
    F = ctx.features.dropna(how="any")
    if ts not in F.index or len(F) < 200:
        return {"analogs": [], "forward": {}, "features": []}
    known = F.loc[F.index.isin(_known(ts, 20, ctx.idx))]
    known = known.loc[: ts - pd.Timedelta(days=45)]
    if len(known) < 100:
        return {"analogs": [], "forward": {}, "features": list(F.columns)}
    mu, sd = F.loc[:ts].mean(), F.loc[:ts].std().replace(0, 1)
    z_now = (F.loc[ts] - mu) / sd
    z = (known - mu) / sd
    dist = np.sqrt(((z - z_now) ** 2).sum(axis=1)).sort_values()
    chosen: list[pd.Timestamp] = []
    for dt in dist.index:
        if all(abs((dt - c).days) >= min_gap for c in chosen):
            chosen.append(dt)
        if len(chosen) >= k:
            break
    rows = []
    for dt in chosen:
        row = {"date": dt.date().isoformat(), "distance": float(dist.loc[dt]),
               "features": {c: float(F.loc[dt, c]) for c in F.columns}, "forward": {}}
        for sym in TARGETS:
            f = ctx.fwd.get(sym)
            if f is not None:
                row["forward"][sym] = {h: (None if pd.isna(f[h].loc[dt]) else float(f[h].loc[dt])) for h in HORIZONS}
        rows.append(row)
    fwd = {}
    for sym in set(TARGETS) | set(EXPECT_ASSETS):
        f = ctx.fwd.get(sym)
        if f is None:
            continue
        fwd[sym] = {h: _stats(f[h].reindex(chosen)) for h in HORIZONS}
    return {"analogs": rows, "forward": fwd, "features": list(F.columns),
            "today": {c: float(F.loc[ts, c]) for c in F.columns}}


def expectations(ctx: Context, date: str, analog_fwd: dict, names: dict[str, str]) -> list[dict]:
    ts = pd.Timestamp(date)
    out = []
    for sym in EXPECT_ASSETS:
        s = ctx.closes.get(sym)
        if s is None or ts not in s.index or pd.isna(s.loc[ts]):
            continue
        close = float(s.loc[ts])
        vol = ctx.daily_vol[sym].loc[ts]
        vol = float(vol) if pd.notna(vol) else None
        item = {"symbol": sym, "name": names.get(sym, sym), "close": close, "daily_vol_pct": vol}
        for h in (5, 10):
            if vol:
                band = vol * np.sqrt(h) / 100
                item[f"range{h}"] = [close * (1 - band), close * (1 + band)]
            st = (analog_fwd.get(sym) or {}).get(h)
            if st:
                item[f"analog{h}"] = st
                item[f"center{h}"] = close * (1 + st["median"] / 100)
        a5 = item.get("analog5")
        p = a5["pct_up"] if a5 else 0.5
        item["prob_up_5d"] = p
        item["bias"] = "up" if p >= 0.6 else "down" if p <= 0.4 else "neutral"
        out.append(item)
    return out


def episodes(cfg: list[dict], closes: dict[str, pd.Series]) -> list[dict]:
    out = []
    for e in cfg:
        moves = {}
        for sym, name in {**TARGETS, "DX-Y.NYB": "Dollar index", "^TNX": "US 10-yr"}.items():
            s = closes.get(sym)
            if s is None:
                continue
            w = s.loc[e["start"]:e["end"]].dropna()
            if len(w) < 3:
                continue
            if sym == "^TNX":
                moves[sym] = {"name": name, "change": float((w.iloc[-1] - w.iloc[0]) * 100), "unit": "bp"}
            else:
                moves[sym] = {"name": name, "change": float((w.iloc[-1] / w.iloc[0] - 1) * 100), "unit": "%",
                              "max_drawdown": float(((w / w.cummax()) - 1).min() * 100)}
        out.append(dict(e, moves=moves))
    return out
