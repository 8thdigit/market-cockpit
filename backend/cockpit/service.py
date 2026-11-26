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


_VIEW_CACHE: dict | None = None  # enabled during static export only (data is immutable then)


def _view(db: DB, d: str, kind: str, default=None):
    key = (d, kind)
    if _VIEW_CACHE is not None and key in _VIEW_CACHE:
        return _VIEW_CACHE[key]
    r = db.query("SELECT payload FROM daily_views WHERE date=? AND kind=?", (d, kind))
    val = dec(r[0]["payload"], default) if r else default
    if _VIEW_CACHE is not None:
        _VIEW_CACHE[key] = val
    return val


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
        "predictions": predictions(db, d),
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
            "predictions": predictions(db, d),
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
        "predictions": predictions(db, d, ["^GSPC", "^NDX", "^NSEI", "^BSESN"]),
        "recommended": recommended_stocks(db, d, s=s),
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
        "predictions": predictions(db, d, COMMODITIES),
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


# ============================================================ predictions: call, exit, confidence, track record
PRED_H = 5


def _call(e: dict) -> str:
    p = e.get("prob_up_5d", 0.5)
    m = (e.get("analog5") or {}).get("median", 0) or 0
    if p >= 0.6 and m > 0:
        return "BUY"
    if p <= 0.4 and m < 0:
        return "SELL"
    return "WATCH"


def _judge(call: str, e: dict, close5: float) -> bool:
    ret = close5 / e["close"] - 1
    if call == "BUY":
        return ret > 0
    if call == "SELL":
        return ret < 0
    r = e.get("range5")
    return bool(r) and r[0] <= close5 <= r[1]  # WATCH = "no big move": price stayed inside the expected range


def _closes(db: DB, syms: list[str], d: str) -> dict[str, pd.Series]:
    out = {}
    for sym in syms:
        rows = db.query("SELECT date, close FROM prices WHERE symbol=? AND date<=? ORDER BY date", (sym, d))
        if rows:
            out[sym] = pd.Series([r["close"] for r in rows], index=[r["date"] for r in rows])
    return out


def predictions(db: DB, d: str, syms: list[str] | None = None, sets: int = 20) -> dict:
    """Enrich the as-of expectations with call / exit / confidence, and score the last `sets` prediction sets."""
    today = _view(db, d, "expectations", []) or []
    if syms:
        today = [e for e in today if e["symbol"] in syms]
    syms = [e["symbol"] for e in today]
    closes = _closes(db, syms, d)
    past_dates = [r["date"] for r in db.query(
        "SELECT date FROM daily_views WHERE kind='expectations' AND date<? ORDER BY date DESC LIMIT ?", (d, sets + PRED_H + 10))]
    history, per = [], {s: [] for s in syms}
    for pdt in past_dates:
        rows = {e["symbol"]: e for e in (_view(db, pdt, "expectations", []) or []) if e["symbol"] in syms}
        item = {"date": pdt, "calls": {}}
        resolved = False
        for sym, e in rows.items():
            c = closes.get(sym)
            if c is None or pdt not in c.index:
                continue
            i = c.index.get_loc(pdt)
            call = _call(e)
            rec = {"call": call, "close": e["close"], "exit": e.get("center5")}
            if i + PRED_H < len(c):  # window closed by the as-of date
                c5 = float(c.iloc[i + PRED_H])
                ok = _judge(call, e, c5)
                rec.update(close5=c5, ret5=(c5 / e["close"] - 1) * 100, result="success" if ok else "fail")
                per[sym].append(ok)
                resolved = True
            else:
                rec["result"] = "pending"
            item["calls"][sym] = rec
        if item["calls"] and (resolved or len(history) < 3):
            history.append(item)
        if sum(1 for h in history if any(v.get("result") != "pending" for v in h["calls"].values())) >= sets:
            break
    summary = {}
    for sym in syms:
        res = per[sym][:sets]
        n, hits = len(res), sum(res)
        summary[sym] = {"n": n, "hits": hits, "rate": hits / n if n else None,
                        "shrunk": (hits + 2) / (n + 4)}  # small samples pulled toward 50%
    rows = []
    for e in today:
        call = _call(e)
        p = e.get("prob_up_5d", 0.5)
        model = p if call == "BUY" else (1 - p) if call == "SELL" else 0.68
        track = summary[e["symbol"]]["shrunk"]
        conf = round(100 * (0.5 * model + 0.5 * track))
        r5 = e.get("range5") or [None, None]
        exit_px = e.get("center5") or e["close"]
        stop = r5[0] if call == "BUY" else r5[1] if call == "SELL" else None
        rows.append(dict(e, call=call, confidence=conf, model_prob=model, exit=exit_px, stop=stop,
                         track=summary[e["symbol"]]))
    allres = [x for s in syms for x in per[s][:sets]]
    overall = {"n": len(allres), "hits": sum(allres), "rate": (sum(allres) / len(allres)) if allres else None,
               "confidence": round(sum(r["confidence"] for r in rows) / len(rows)) if rows else None}
    return {"rows": rows, "sets": history[:sets + PRED_H], "summary": summary, "overall": overall,
            "rules": "BUY: P(up 5d) >= 60% and analog median > 0. SELL: P(up) <= 40% and median < 0. "
                     "WATCH otherwise. Success = 5 trading days later price moved the called way "
                     "(WATCH: stayed inside the expected range). Confidence = 50% model probability + "
                     "50% this asset's last-20 success rate (shrunk toward 50%)."}


def recommended_stocks(db: DB, d: str, per_market: int = 15, s: Settings | None = None) -> dict:
    """Ranked stock list per market with confidence, entry and exit (target) prices."""
    from .engines import trades
    s = s or get_settings()
    insts = {i["symbol"]: i for i in instruments(s)}
    calib = {(c["market"], c["bucket"]): c for c in db.query("SELECT * FROM calibration")}
    hist = {}
    for r in db.query("SELECT symbol, status, r_multiple FROM picks WHERE exit_date<=? AND status!='open'", (d,)):
        h = hist.setdefault(r["symbol"], [0, 0])
        h[0] += 1
        h[1] += int((r["r_multiple"] or 0) > 0)
    out = {}
    for mkt in ("IN", "US"):
        rows = db.query("SELECT * FROM signals WHERE date=? AND market=? ORDER BY score DESC", (d, mkt))
        lst = []
        for r in rows:
            if r["score"] < 50 or r["trend"] == "downtrend":
                continue
            px = db.query("SELECT high FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 10", (r["symbol"], d))
            hi10 = max(x["high"] for x in px) if px else r["close"]
            if r["score"] >= s.min_pick_score:
                call, entry = "BUY", r["close"]
            else:
                call, entry = "WATCH", max(hi10, r["close"])  # buy only on a break above the 10-day high
            stop = entry - 1.5 * r["atr"]
            exit_px = entry + s.reward_risk * (entry - stop)
            b = trades.bucket(r["score"]) or "70-79"
            cal = calib.get((mkt, b))
            hit = cal["hit_rate"] if cal else 0.45
            if r["score"] < s.min_pick_score:
                hit *= 0.9  # untriggered setups are less reliable than triggered ones
            own = hist.get(r["symbol"])
            own_rate = (own[1] + 1) / (own[0] + 2) if own else None
            conf = 0.45 * (r["score"] / 100) + 0.40 * hit + 0.15 * (own_rate if own_rate is not None else hit)
            lst.append({"symbol": r["symbol"], "name": insts.get(r["symbol"], {}).get("name", r["symbol"]),
                        "sector": insts.get(r["symbol"], {}).get("sector"), "call": call, "score": r["score"],
                        "confidence": round(conf * 100), "close": r["close"], "entry": entry, "stop": stop,
                        "exit": exit_px, "upside": exit_px / entry - 1, "risk": 1 - stop / entry,
                        "hit_rate": hit, "own_record": {"closed": own[0], "wins": own[1]} if own else None,
                        "rsi": r["rsi"], "trend": r["trend"], "patterns": dec(r["patterns"], [])})
        lst.sort(key=lambda x: (x["call"] != "BUY", -x["confidence"]))
        out[mkt] = lst[:per_market]
    return out
