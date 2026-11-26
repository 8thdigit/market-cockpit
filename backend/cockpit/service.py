"""Read model: assembles what the dashboard needs for a given as-of date."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .config import Settings, get_settings, instruments
from .db import DB, dec
from .engines.alerts import SEVERITIES
from .engines.patterns import PATTERN_INFO
from .providers.fred import FRED_SERIES

TILE_ORDER = ["^GSPC", "^NDX", "^NSEI", "^BSESN", "^VIX", "^INDIAVIX", "GC=F", "SI=F", "BZ=F", "CL=F", "DX-Y.NYB", "INR=X", "^TNX"]


def resolve_date(db: DB, date: str | None) -> str | None:
    if date:
        r = db.query("SELECT MAX(date) d FROM signals WHERE date<=?", (date,))
    else:
        r = db.query("SELECT MAX(date) d FROM signals")
    return r[0]["d"] if r else None


def dates(db: DB) -> list[str]:
    return [r["date"] for r in db.query("SELECT DISTINCT date FROM signals ORDER BY date")]


def _pick(r: dict, names: dict) -> dict:
    r = dict(r)
    r["rationale"] = dec(r.get("rationale"), [])
    r["jackpot"] = bool(r.get("jackpot"))
    r["name"] = names.get(r["symbol"], r["symbol"])
    risk = r["entry"] - r["stop"]
    r["risk_pct"] = risk / r["entry"] if r["entry"] else None
    r["reward_pct"] = (r["target"] - r["entry"]) / r["entry"] if r["entry"] else None
    return r


def tiles(db: DB, date: str) -> list[dict]:
    names = {i["symbol"]: i["name"] for i in instruments()}
    out = []
    for sym in TILE_ORDER:
        rows = db.query("SELECT date, close FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 260", (sym, date))
        if not rows:
            continue
        closes = [r["close"] for r in rows]
        last = closes[0]

        def chg(n):
            return (last / closes[n] - 1) if len(closes) > n and closes[n] else None
        spark = [{"date": r["date"], "close": r["close"]} for r in reversed(rows[:60])]
        out.append({"symbol": sym, "name": names.get(sym, sym), "date": rows[0]["date"], "close": last,
                    "chg_1d": chg(1), "chg_5d": chg(5), "chg_21d": chg(21),
                    "high_52w": max(closes), "low_52w": min(closes), "spark": spark,
                    "is_rate": sym == "^TNX"})
    return out


def macro_latest(db: DB, date: str) -> list[dict]:
    out = []
    for sid, (label, unit) in FRED_SERIES.items():
        rows = db.query("SELECT date, value FROM macro WHERE series=? AND date<=? ORDER BY date DESC LIMIT 13", (sid, date))
        if not rows:
            continue
        item = {"series": sid, "label": label, "unit": unit, "date": rows[0]["date"], "value": rows[0]["value"]}
        if unit == "index" and len(rows) >= 13:  # year-over-year change for price indices
            item["yoy"] = rows[0]["value"] / rows[12]["value"] - 1
        if len(rows) > 1:
            item["prev"] = rows[1]["value"]
        out.append(item)
    return out


def snapshot(db: DB, date: str | None = None, severity: str | None = None, s: Settings | None = None) -> dict:
    s = s or get_settings()
    d = resolve_date(db, date)
    if not d:
        return {"date": None, "empty": True}
    names = {i["symbol"]: i["name"] for i in instruments(s)}
    reg = db.query("SELECT * FROM regime WHERE date<=? ORDER BY date DESC LIMIT 60", (d,))
    for r in reg:
        r["components"] = dec(r["components"], {})
    min_sev = SEVERITIES.index(severity) if severity in SEVERITIES else 0
    al = [a for a in db.query("SELECT * FROM alerts WHERE date=? ORDER BY ts DESC", (d,))
          if SEVERITIES.index(a["severity"]) >= min_sev]
    al.sort(key=lambda a: -SEVERITIES.index(a["severity"]))
    new_picks = [_pick(p, names) for p in db.query("SELECT * FROM picks WHERE date=? ORDER BY rank", (d,))]
    open_picks = [_pick(p, names) for p in db.query(
        "SELECT * FROM picks WHERE date<? AND (status='open' OR exit_date>?) ORDER BY date DESC", (d, d))]
    start = pd.Timestamp(d).tz_localize("UTC")
    upcoming = [e for e in s.events() if start - timedelta(days=1) <= pd.Timestamp(e["ts"]) <= start + timedelta(days=21)]
    news = db.query("SELECT ts, source, title, url, sentiment, topics FROM news WHERE date<=? AND date>=? "
                    "ORDER BY ts DESC LIMIT 40", (d, (pd.Timestamp(d) - timedelta(days=3)).date().isoformat()))
    for n in news:
        n["topics"] = dec(n["topics"], [])
    sent = {}
    for r in db.query("SELECT series, value FROM macro WHERE series LIKE 'sent_%' AND date<=? AND date>=?",
                      (d, (pd.Timestamp(d) - timedelta(days=3)).date().isoformat())):
        sent.setdefault(r["series"][5:], []).append(r["value"])
    return {
        "date": d, "provider": s.provider,
        "regime": reg[0] if reg else None,
        "regime_history": list(reversed([{"date": r["date"], "score": r["score"], "label": r["label"]} for r in reg])),
        "tiles": tiles(db, d), "macro": macro_latest(db, d),
        "alerts": al, "alert_counts": {sv: sum(1 for a in al if a["severity"] == sv) for sv in SEVERITIES},
        "jackpot": [p for p in new_picks if p["jackpot"]], "picks": new_picks, "open_picks": open_picks,
        "events": upcoming, "news": news,
        "sentiment": {k: sum(v) / len(v) for k, v in sent.items()},
    }


def signals(db: DB, date: str | None, market: str | None = None, min_score: float = 0) -> dict:
    d = resolve_date(db, date)
    names = {i["symbol"]: i for i in instruments()}
    sql = "SELECT * FROM signals WHERE date=? AND score>=?"
    params: list = [d, min_score]
    if market:
        sql += " AND market=?"
        params.append(market)
    rows = db.query(sql + " ORDER BY score DESC", params)
    for r in rows:
        r["components"] = dec(r["components"], {})
        r["patterns"] = dec(r["patterns"], [])
        r["name"] = names.get(r["symbol"], {}).get("name", r["symbol"])
        r["sector"] = names.get(r["symbol"], {}).get("sector")
    return {"date": d, "signals": rows}


def instrument(db: DB, symbol: str, date: str | None, bars: int = 260) -> dict:
    d = resolve_date(db, date) or date
    inst = next((i for i in instruments() if i["symbol"] == symbol), {"symbol": symbol, "name": symbol})
    px = db.query("SELECT date, open, high, low, close, volume FROM prices WHERE symbol=? AND date<=? "
                  "ORDER BY date DESC LIMIT ?", (symbol, d, bars))
    sig = db.query("SELECT date, score, rsi, ema20, ema50, ema200, patterns, vol_ratio FROM signals "
                   "WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT ?", (symbol, d, bars))
    for r in sig:
        r["patterns"] = dec(r["patterns"], [])
    picks = [_pick(p, {symbol: inst["name"]}) for p in db.query(
        "SELECT * FROM picks WHERE symbol=? AND date<=? ORDER BY date DESC", (symbol, d))]
    return {"instrument": inst, "date": d, "bars": list(reversed(px)), "signals": list(reversed(sig)), "picks": picks,
            "pattern_info": {k: {"direction": v[0], "rate": v[1], "desc": v[2]} for k, v in PATTERN_INFO.items()}}


def track_record(db: DB, date: str | None = None) -> dict:
    d = resolve_date(db, date)
    names = {i["symbol"]: i["name"] for i in instruments()}
    closed = [_pick(p, names) for p in db.query(
        "SELECT * FROM picks WHERE status IN ('target','stopped','expired') AND exit_date<=? ORDER BY exit_date DESC", (d,))]
    def stats(rows):
        n = len(rows)
        wins = sum(1 for r in rows if (r["r_multiple"] or 0) > 0)
        return {"trades": n, "wins": wins, "hit_rate": wins / n if n else None,
                "avg_r": sum(r["r_multiple"] or 0 for r in rows) / n if n else None,
                "total_r": sum(r["r_multiple"] or 0 for r in rows)}
    by_mkt = {m: stats([r for r in closed if r["market"] == m]) for m in ("IN", "US", "CMD")}
    jp = stats([r for r in closed if r["jackpot"]])
    equity, cum = [], 0.0
    for r in sorted(closed, key=lambda r: r["exit_date"]):
        cum += r["r_multiple"] or 0
        equity.append({"date": r["exit_date"], "cum_r": round(cum, 3)})
    calib = db.query("SELECT * FROM calibration ORDER BY market, bucket")
    return {"date": d, "overall": stats(closed), "jackpot": jp, "by_market": by_mkt, "equity": equity,
            "closed": closed[:200], "calibration": calib}


def health(db: DB) -> dict:
    src = db.query("SELECT * FROM source_health ORDER BY source")
    runs = db.query("SELECT * FROM runs ORDER BY id DESC LIMIT 30")
    fresh = db.query("SELECT p.symbol, i.name, MAX(p.date) last_date, COUNT(*) bars FROM prices p "
                     "LEFT JOIN instruments i ON i.symbol=p.symbol GROUP BY p.symbol ORDER BY last_date")
    return {"sources": src, "runs": runs, "freshness": fresh, "provider": get_settings().provider}


# ============================================================ four-page views
COMMODITIES = ["GC=F", "SI=F", "BZ=F", "CL=F"]
INDEX_STANCES = ["^GSPC", "^NDX", "^NSEI", "^BSESN"]


def _view(db: DB, d: str, kind: str, default=None):
    r = db.query("SELECT payload FROM daily_views WHERE date=? AND kind=?", (d, kind))
    return dec(r[0]["payload"], default) if r else default


def _stances(db: DB, d: str, syms: list[str]) -> list[dict]:
    q = f"SELECT * FROM stances WHERE date=? AND symbol IN ({','.join('?' * len(syms))})"
    rows = db.query(q, [d, *syms])
    out = []
    for r in sorted(rows, key=lambda r: syms.index(r["symbol"])):
        p = dec(r["payload"], {})
        p.update({"outcome": r["outcome"], "ret_5d": r["ret_5d"]})
        out.append(p)
    return out


def _stance_record(db: DB, d: str, syms: list[str], limit: int = 400) -> dict:
    q = (f"SELECT date, symbol, stance, direction, ret_5d, outcome, checked_on, payload FROM stances "
         f"WHERE date<=? AND symbol IN ({','.join('?' * len(syms))}) ORDER BY date DESC LIMIT ?")
    rows = db.query(q, [d, *syms, limit])
    names = {i["symbol"]: i["name"] for i in instruments()}
    hist, per = [], {}
    for r in rows:
        p = dec(r.pop("payload"), {})
        r["name"] = names.get(r["symbol"], r["symbol"])
        r["close"] = p.get("close")
        r["prob_up_5d"] = p.get("prob_up_5d")
        hist.append(r)
    def agg(rs):
        decided = [x for x in rs if x["outcome"] in ("met", "failed")]
        met = sum(1 for x in decided if x["outcome"] == "met")
        return {"calls": len([x for x in rs if x["direction"] != 0]), "decided": len(decided), "met": met,
                "failed": len(decided) - met, "success": met / len(decided) if decided else None,
                "pending": sum(1 for x in rs if x["outcome"] == "pending" and x["direction"] != 0),
                "avg_ret_dir": (sum((x["ret_5d"] or 0) * x["direction"] for x in decided) / len(decided)) if decided else None}
    for sym in syms:
        per[sym] = dict(agg([x for x in hist if x["symbol"] == sym]), name=names.get(sym, sym))
    by_stance = {st: agg([x for x in hist if x["stance"] == st]) for st in ("BUY", "SELL", "ACCUMULATE DIPS", "SELL RALLIES")}
    return {"overall": agg(hist), "per_symbol": per, "by_stance": by_stance, "history": hist[:200]}


def _pick_stats(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["status"] in ("target", "stopped", "expired")]
    n = len(closed)
    met = sum(1 for r in closed if r["status"] == "target")
    failed = sum(1 for r in closed if r["status"] == "stopped")
    wins = sum(1 for r in closed if (r["r_multiple"] or 0) > 0)
    return {"closed": n, "target_hit": met, "stopped": failed, "expired": n - met - failed,
            "success": wins / n if n else None, "target_rate": met / n if n else None,
            "avg_r": sum(r["r_multiple"] or 0 for r in closed) / n if n else None,
            "total_r": sum(r["r_multiple"] or 0 for r in closed), "open": sum(1 for r in rows if r["status"] == "open")}


def page_influencers(db: DB, date: str | None, s: Settings | None = None) -> dict:
    s = s or get_settings()
    d = resolve_date(db, date)
    if not d:
        return {"date": None, "empty": True}
    snap = snapshot(db, d, None, s)
    return {
        "date": d, "provider": s.provider, "regime": snap["regime"], "regime_history": snap["regime_history"],
        "influencers": _view(db, d, "influencers", []),
        "expectations": _view(db, d, "expectations", []),
        "markets": _stances(db, d, INDEX_STANCES + COMMODITIES),
        "events": snap["events"], "news": snap["news"][:12], "sentiment": snap["sentiment"],
        "alerts": [a for a in snap["alerts"] if a["severity"] in ("warning", "critical")][:12],
        "macro": snap["macro"], "tiles": snap["tiles"],
    }


def page_history(db: DB, date: str | None, s: Settings | None = None) -> dict:
    s = s or get_settings()
    d = resolve_date(db, date)
    if not d:
        return {"date": None, "empty": True}
    from .engines import influence
    closes = {}
    for sym in list(influence.TARGETS) + ["DX-Y.NYB", "^TNX"]:
        rows = db.query("SELECT date, close FROM prices WHERE symbol=? AND date<=? ORDER BY date", (sym, d))
        if rows:
            closes[sym] = pd.Series([r["close"] for r in rows], index=pd.to_datetime([r["date"] for r in rows]))
    first = min((c.index[0] for c in closes.values()), default=None)
    return {"date": d, "provider": s.provider, "analogs": _view(db, d, "analogs", {}),
            "expectations": _view(db, d, "expectations", []),
            "episodes": influence.episodes(s.episodes(), closes),
            "history_from": first.date().isoformat() if first is not None else None,
            "targets": influence.TARGETS}


def page_stocks(db: DB, date: str | None, s: Settings | None = None) -> dict:
    s = s or get_settings()
    d = resolve_date(db, date)
    if not d:
        return {"date": None, "empty": True}
    names = {i["symbol"]: i["name"] for i in instruments(s)}
    new = [_pick(p, names) for p in db.query("SELECT * FROM picks WHERE date=? AND market IN ('IN','US') ORDER BY rank", (d,))]
    openp = [_pick(p, names) for p in db.query(
        "SELECT * FROM picks WHERE date<? AND market IN ('IN','US') AND (status='open' OR exit_date>?) ORDER BY date DESC", (d, d))]
    allp = [_pick(p, names) for p in db.query(
        "SELECT * FROM picks WHERE date<=? AND market IN ('IN','US') ORDER BY date DESC", (d,))]
    for p in allp:  # as-of view: anything that closed after the as-of date is still open
        if p["exit_date"] and p["exit_date"] > d:
            p.update(status="open", exit_date=None, exit_price=None, r_multiple=None)
    sig = signals(db, d)["signals"]
    reg = db.query("SELECT * FROM regime WHERE date=?", (d,))
    return {
        "date": d, "provider": s.provider, "regime": reg[0] if reg else None,
        "jackpot": [p for p in new if p["jackpot"]], "picks": new, "open": openp,
        "watchlist": [x for x in sig if x["market"] in ("IN", "US")][:40],
        "record": {"all": _pick_stats(allp), "IN": _pick_stats([p for p in allp if p["market"] == "IN"]),
                   "US": _pick_stats([p for p in allp if p["market"] == "US"]),
                   "jackpot": _pick_stats([p for p in allp if p["jackpot"]])},
        "closed": [p for p in allp if p["status"] != "open"][:80],
        "calibration": db.query("SELECT * FROM calibration WHERE market IN ('IN','US') ORDER BY market, bucket"),
        "expectations": [e for e in _view(db, d, "expectations", []) if e["symbol"] in ("^GSPC", "^NDX", "^NSEI", "^BSESN")],
    }


def page_commodities(db: DB, date: str | None, s: Settings | None = None) -> dict:
    s = s or get_settings()
    d = resolve_date(db, date)
    if not d:
        return {"date": None, "empty": True}
    names = {i["symbol"]: i["name"] for i in instruments(s)}
    stances = _stances(db, d, COMMODITIES)
    for st in stances:
        rows = db.query("SELECT date, close FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 130", (st["symbol"], d))
        st["spark"] = [{"date": r["date"], "close": r["close"]} for r in reversed(rows)]
    allp = [_pick(p, names) for p in db.query("SELECT * FROM picks WHERE date<=? AND market='CMD' ORDER BY date DESC", (d,))]
    for p in allp:
        if p["exit_date"] and p["exit_date"] > d:
            p.update(status="open", exit_date=None, exit_price=None, r_multiple=None)
    infl = [i for i in _view(db, d, "influencers", []) if i["id"] in ("dollar", "yields", "real_yield", "fed", "oil", "gold", "vix", "geopolitics", "inflation")]
    return {
        "date": d, "provider": s.provider, "stances": stances,
        "expectations": [e for e in _view(db, d, "expectations", []) if e["symbol"] in COMMODITIES],
        "drivers": infl,
        "stance_record": _stance_record(db, d, COMMODITIES),
        "picks_today": [p for p in allp if p["date"] == d],
        "open": [p for p in allp if p["status"] == "open" and p["date"] < d],
        "closed": [p for p in allp if p["status"] != "open"][:80],
        "pick_record": {"all": _pick_stats(allp), **{sym: dict(_pick_stats([p for p in allp if p["symbol"] == sym]), name=names[sym]) for sym in COMMODITIES},
                        "long": _pick_stats([p for p in allp if p["direction"] == "long"]),
                        "short": _pick_stats([p for p in allp if p["direction"] == "short"])},
        "calibration": db.query("SELECT * FROM calibration WHERE market IN ('CMD','CMD-S') ORDER BY market, bucket"),
        "events": [e for e in s.events() if any(a in e.get("assets", []) for a in ("GC=F", "BZ=F", "CL=F"))
                   and pd.Timestamp(e["ts"]) >= pd.Timestamp(d).tz_localize("UTC") - pd.Timedelta(days=1)],
    }
