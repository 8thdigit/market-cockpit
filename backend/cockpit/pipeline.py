"""Collect -> analyse -> store. Every stage isolates failures per source/symbol so one bad feed never stops a run."""
from __future__ import annotations

import logging
import traceback
from datetime import date as Date
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import Settings, get_settings, instruments
from .db import DB, dec
from .engines import alerts as A
from .engines import indicators, influence, patterns, regime, scoring, stance, trades
from .providers import macro_provider, price_provider
from .providers.fred import FRED_SERIES

log = logging.getLogger("cockpit.pipeline")
GOLD_LIKE = {"GC=F", "SI=F", "GLD", "GOLDBEES.NS"}
STANCE_SYMS = ["GC=F", "SI=F", "BZ=F", "CL=F", "^GSPC", "^NDX", "^NSEI", "^BSESN"]
SHORTABLE = {"GC=F", "SI=F", "BZ=F", "CL=F"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _market(inst: dict) -> str:
    return inst["market"] if inst["market"] in ("IN", "US") else "CMD"


# ----------------------------------------------------------------------------- collection
def collect_prices(db: DB, s: Settings | None = None, provider=None, end: str | None = None) -> dict:
    s = s or get_settings()
    provider = provider or price_provider(s)
    insts = instruments(s)
    db.upsert("instruments", [{k: i.get(k) for k in ("symbol", "name", "market", "kind", "sector", "tradable", "benchmark")}
                              for i in insts])
    last = {r["symbol"]: r["d"] for r in db.query("SELECT symbol, MAX(date) d FROM prices GROUP BY symbol")}
    ok, failed = 0, []
    for inst in insts:
        sym = inst["symbol"]
        first = (Date.today() - timedelta(days=int(s.history_days * 1.45))).isoformat() if inst["kind"] == "equity" \
            else (Date.today() - timedelta(days=365 * s.macro_years)).isoformat()
        start = (pd.Timestamp(last[sym]) - timedelta(days=7)).date().isoformat() if sym in last else first
        try:
            df = provider.daily(sym, start, end)
            rows = [{"symbol": sym, "date": d.date().isoformat(), "open": float(r.open), "high": float(r.high),
                     "low": float(r.low), "close": float(r.close), "volume": float(r.volume),
                     "source": getattr(provider, "name", "?")} for d, r in df.iterrows()]
            db.upsert("prices", rows)
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append(f"{sym}: {e}")
            log.warning("price fetch failed %s: %s", sym, e)
    ts = now_iso()
    if ok:
        db.source_ok(f"prices:{getattr(provider, 'name', '?')}", ts, ok)
    if failed:
        db.source_error(f"prices:{getattr(provider, 'name', '?')}", ts, "; ".join(failed[:10]))
    return {"ok": ok, "failed": failed}


def collect_macro(db: DB, s: Settings | None = None, provider=None) -> dict:
    s = s or get_settings()
    provider = provider or macro_provider(s)
    start = (Date.today() - timedelta(days=365 * s.macro_years)).isoformat()
    ok, failed = 0, []
    for sid in FRED_SERIES:
        try:
            ser = provider.series(sid, start)
            db.upsert("macro", [{"series": sid, "date": d.date().isoformat(), "value": float(v), "source": provider.name}
                                for d, v in ser.items()])
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append(f"{sid}: {e}")
    ts = now_iso()
    if ok:
        db.source_ok(f"macro:{provider.name}", ts, ok)
    if failed:
        db.source_error(f"macro:{provider.name}", ts, "; ".join(failed))
    return {"ok": ok, "failed": failed}


def collect_news(db: DB, s: Settings | None = None) -> dict:
    s = s or get_settings()
    if not s.news_enabled or s.provider == "fixture":
        return {"ok": 0, "failed": [], "skipped": True}
    from .providers.news import FEEDS, fetch_feed
    ok, failed, n = 0, [], 0
    for src, url in FEEDS.items():
        try:
            items = fetch_feed(src, url)
            n += db.upsert("news", items)
            ok += 1
            db.source_ok(f"news:{src}", now_iso(), len(items))
        except Exception as e:  # noqa: BLE001
            failed.append(f"{src}: {e}")
            db.source_error(f"news:{src}", now_iso(), str(e))
    _store_sentiment(db)
    return {"ok": ok, "failed": failed, "items": n}


def _store_sentiment(db: DB) -> None:
    df = db.df("SELECT date, sentiment, topics FROM news WHERE date >= ?", ((Date.today() - timedelta(days=60)).isoformat(),))
    if df.empty:
        return
    rows = []
    for d, g in df.groupby("date"):
        rows.append({"series": "sent_all", "date": d, "value": float(g["sentiment"].mean()), "source": "news"})
        exploded = g.assign(topic=g["topics"].map(lambda t: dec(t, []))).explode("topic").dropna(subset=["topic"])
        for t, gt in exploded.groupby("topic"):
            rows.append({"series": f"sent_{t}", "date": d, "value": float(gt["sentiment"].mean()), "source": "news"})
    db.upsert("macro", rows)


# ----------------------------------------------------------------------------- analysis
def _frames(db: DB, insts: list[dict], end: str | None):
    raw = {i["symbol"]: db.prices(i["symbol"], end=end) for i in insts}
    out = {}
    for i in insts:
        df = raw[i["symbol"]]
        if df.empty or len(df) < 60:
            continue
        bench = raw.get(i.get("benchmark")) if i.get("benchmark") else None
        ind = indicators.compute(df, bench)
        out[i["symbol"]] = (ind, patterns.detect(df))
    return out


def _gold_tilt(idx: pd.DatetimeIndex, frames) -> pd.Series:
    tilt = pd.Series(0.0, index=idx)
    if "DX-Y.NYB" in frames:
        d = frames["DX-Y.NYB"][0].reindex(idx).ffill()
        tilt += 5 * (d["close"] < d["ema20"])
    if "^TNX" in frames:
        t = frames["^TNX"][0]["close"].reindex(idx).ffill()
        tilt += 5 * (t < t.shift(5))
    return tilt - 5  # range -5..+5


def analyse(db: DB, start: str, end: str, s: Settings | None = None) -> dict:
    """Compute signals, regime, calibration, picks, outcomes and alerts for every trading day in [start, end]."""
    s = s or get_settings()
    insts = instruments(s)
    meta = {i["symbol"]: i for i in insts}
    names = {i["symbol"]: i["name"] for i in insts}
    frames = _frames(db, insts, end)
    if not frames:
        return {"days": 0, "message": "no price data"}

    # --- regime
    closes = {sym: f[0]["close"] for sym, f in frames.items()}
    macro = {"DFEDTARU": db.macro_series("DFEDTARU", end)}
    reg = regime.compute(closes, macro, db.macro_series("sent_all", end))
    reg_rng = reg.loc[start:end]
    db.upsert("regime", [{"date": d.date().isoformat(), "score": float(r["score"]), "label": r["label"],
                          "components": {k: float(v) for k, v in r.items() if k not in ("score", "label")}}
                         for d, r in reg_rng.iterrows()])
    reg_pts = reg["label"].map(regime.points_for_scoring)

    # --- signals + calibration
    sig_rows, calib_trades = [], {"IN": [], "US": [], "CMD": [], "CMD-S": []}
    scores: dict[str, pd.Series] = {}
    for sym, (ind, pats) in frames.items():
        inst = meta[sym]
        if not inst.get("tradable"):
            continue
        comp = scoring.components(ind, pats, reg_pts)
        if sym in GOLD_LIKE:
            comp["macro_tilt"] = _gold_tilt(ind.index, frames)
        sc = scoring.score(comp)
        scores[sym] = sc
        # calibration uses a neutral regime so the history isn't coloured by today's regime
        comp_neutral = scoring.components(ind, pats, 5.0)
        calib_trades[_market(inst)] += trades.calibrate(ind, scoring.score(comp_neutral), s.reward_risk, s.max_hold_days, s.min_pick_score)
        sel = ind.loc[start:end]
        for d in sel.index:
            r = ind.loc[d]
            sig_rows.append({
                "date": d.date().isoformat(), "symbol": sym, "market": _market(inst), "close": float(r["close"]),
                "score": float(sc.loc[d]), "components": {k: float(v) for k, v in comp.loc[d].items()},
                "patterns": [p for p, v in pats.loc[d].items() if v],
                "rsi": float(r["rsi"]), "atr": float(r["atr"]), "atr_pct": float(r["atr_pct"]),
                "vol_ratio": float(r["vol_ratio"]), "bb_pctile": float(r["bb_pctile"]), "rs_63": float(r["rs_63"]),
                "adx": float(r["adx"]), "ema20": float(r["ema20"]), "ema50": float(r["ema50"]),
                "ema200": float(r["ema200"]), "trend": scoring.trend_label(r)})
    db.upsert("signals", sig_rows)

    # short side for commodities: long-setup logic on the mirrored (1/price) series
    short: dict[str, tuple] = {}
    for sym in SHORTABLE:
        if sym not in frames:
            continue
        inv = indicators.invert(frames[sym][0][["open", "high", "low", "close", "volume"]])
        iind, ipats = indicators.compute(inv), patterns.detect(inv)
        isc = scoring.score(scoring.components(iind, ipats, 5.0))
        short[sym] = (isc, iind, ipats)
        calib_trades["CMD-S"] += trades.calibrate(iind, isc, s.reward_risk, s.max_hold_days, s.min_pick_score)
    # indices get scores for their stance (they are not traded as picks)
    idx_scores = {sym: scoring.score(scoring.components(*frames[sym], 5.0)) for sym in STANCE_SYMS
                  if sym in frames and sym not in scores}
    calib = {}
    for mkt, tr in calib_trades.items():
        summ = trades.summarise(tr)
        calib[mkt] = summ
        db.upsert("calibration", [{"market": mkt, "bucket": b, "trades": v["trades"], "wins": v["wins"],
                                   "hit_rate": v["hit_rate"], "avg_r": v["avg_r"], "expected_r": v["expected_r"],
                                   "updated": now_iso()}
                                  for b, v in summ.items()])

    # --- influencer / analog context (long history)
    macro_all = {sid: db.macro_series(sid, end) for sid in ("DFEDTARU", "CPIAUCSL", "DFII10", "sent_geopolitics")}
    ctx = influence.Context(closes, macro_all)

    # --- day-by-day: outcomes, picks, alerts
    days = sorted({r["date"] for r in sig_rows})
    events = s.events()
    prev_label = None
    prev_reg = db.query("SELECT label FROM regime WHERE date < ? ORDER BY date DESC LIMIT 1", (start,))
    if prev_reg:
        prev_label = prev_reg[0]["label"]
    for d in days:
        ts = pd.Timestamp(d)
        day_alerts = []
        day_alerts += _update_outcomes(db, d, frames, names)
        day_alerts += _make_picks(db, d, frames, scores, meta, calib, reg, s, short)
        day_alerts += _views_and_stances(db, d, ctx, frames, scores, idx_scores, short, reg, names, s)
        day_alerts += A.market_alerts(d, {k: v[0] for k, v in frames.items()}, names)
        day_alerts += A.event_alerts(d, events)
        for sym, sc in scores.items():
            if ts in sc.index:
                i = sc.index.get_loc(ts)
                prev = float(sc.iloc[i - 1]) if i > 0 else None
                pats = [p for p, v in frames[sym][1].loc[ts].items() if v]
                day_alerts += A.pattern_alerts(d, sym, names[sym], pats, float(sc.iloc[i]), prev)
        for sym in ("GC=F", "BZ=F", "^NSEI", "^GSPC"):  # macro assets aren't scored, but their candles matter
            if sym in frames and ts in frames[sym][1].index and sym not in scores:
                pats = [p for p, v in frames[sym][1].loc[ts].items() if v]
                day_alerts += A.pattern_alerts(d, sym, names[sym], pats, 0, None)
        if ts in reg.index:
            label = reg.loc[ts, "label"]
            if prev_label and label != prev_label:
                sev = "critical" if label == "Risk-off" else "warning"
                day_alerts.append(A.make(d, sev, "regime", f"Regime changed: {prev_label} → {label}",
                                         f"Macro risk score {reg.loc[ts, 'score']:.0f}/100."))
            prev_label = label
        day_alerts += _stale_alerts(d, frames, names)
        db.upsert("alerts", day_alerts)
    _score_stances(db, closes)
    return {"days": len(days), "signals": len(sig_rows), "calibration": calib}


def _stale_alerts(d: str, frames, names) -> list[dict]:
    ts = pd.Timestamp(d)
    if (pd.Timestamp.today().normalize() - ts).days > 3:
        return []  # only meaningful for the live date
    out = []
    for sym, (ind, _) in frames.items():
        lag = len(pd.bdate_range(ind.index[-1], ts)) - 1
        if lag >= 4:
            out.append(A.make(d, "warning", "data", f"Stale data: {names[sym]} last bar {ind.index[-1].date()}",
                              "The source hasn't delivered new bars; check source health.", sym))
    return out


def _update_outcomes(db: DB, d: str, frames, names) -> list[dict]:
    out = []
    for p in db.query("SELECT * FROM picks WHERE status='open' AND date < ?", (d,)):
        f = frames.get(p["symbol"])
        if not f:
            continue
        ind = f[0]
        bars = ind.loc[pd.Timestamp(p["date"]) + timedelta(days=1): pd.Timestamp(d)]
        if p["direction"] == "short":
            res = trades.simulate(indicators.invert(bars), 1 / p["entry"], 1 / p["stop"], 1 / p["target"],
                                  get_settings().max_hold_days)
            if res is not None:
                res = (res[0], res[1], 1 / res[2] if res[2] else res[2], res[3])
        else:
            res = trades.simulate(bars, p["entry"], p["stop"], p["target"], get_settings().max_hold_days)
        if res is None:
            continue
        status, dt, px, r = res
        db.execute("UPDATE picks SET status=?, exit_date=?, exit_price=?, r_multiple=? WHERE id=?",
                   (status, dt.date().isoformat() if dt is not None else None, px, r, p["id"]))
        sev = {"target": "info", "stopped": "warning", "expired": "info"}.get(status, "info")
        out.append(A.make(d, sev, "pick", f"{names.get(p['symbol'], p['symbol'])} pick {status} ({r:+.1f}R)",
                          f"Entry {p['entry']:.2f} on {p['date']}, exit {px:.2f}.", p["symbol"]))
    return out


def _make_picks(db: DB, d: str, frames, scores, meta, calib, reg, s: Settings, short=None) -> list[dict]:
    ts = pd.Timestamp(d)
    open_syms = {r["symbol"] for r in db.query("SELECT symbol FROM picks WHERE status='open' AND date < ?", (d,))}
    label = reg.loc[ts, "label"] if ts in reg.index else "Neutral"
    cands = []
    for sym, sc in scores.items():
        if ts not in sc.index or sym in open_syms:
            continue
        score = float(sc.loc[ts])
        if score < s.min_pick_score:
            continue
        ind, pats = frames[sym]
        row = ind.loc[ts]
        if pd.isna(row["atr"]) or row["atr"] <= 0:
            continue
        mkt = _market(meta[sym])
        b = trades.bucket(score)
        cal = calib.get(mkt, {}).get(b)
        conf = cal["confidence"] if cal else 0.5
        exp_r = cal["expected_r"] if cal else 0.0
        stop, target = trades.levels(row["close"], row["atr"], row.get("low10"), s.reward_risk)
        comp = scoring.components(ind.loc[:ts].tail(2), pats.loc[:ts].tail(2), 5.0).iloc[-1]
        active = [p for p, v in pats.loc[ts].items() if v]
        why = scoring.rationale(comp, row, active)
        if cal:
            why.append(f"Similar {mkt} setups ({b}) hit target first {cal['hit_rate'] * 100:.0f}% of the time "
                       f"in {cal['trades']} past trades (avg {cal['avg_r']:+.2f}R)")
        cands.append({"symbol": sym, "market": mkt, "score": score, "confidence": conf, "entry": float(row["close"]),
                      "stop": stop, "target": target, "rationale": why, "expected_r": exp_r, "direction": "long"})
    for sym, (isc, iind, ipats) in (short or {}).items():
        if ts not in isc.index or sym in open_syms or float(isc.loc[ts]) < s.min_pick_score:
            continue
        score, irow, row = float(isc.loc[ts]), iind.loc[ts], frames[sym][0].loc[ts]
        if pd.isna(irow["atr"]) or irow["atr"] <= 0:
            continue
        b = trades.bucket(score)
        cal = calib.get("CMD-S", {}).get(b)
        istop, itarget = trades.levels(irow["close"], irow["atr"], irow.get("low10"), s.reward_risk)
        why = scoring.rationale_short(row, [p for p, v in frames[sym][1].loc[ts].items() if v])
        if cal:
            why.append(f"Similar commodity short setups ({b}) hit target first {cal['hit_rate'] * 100:.0f}% of the time "
                       f"in {cal['trades']} past trades (avg {cal['avg_r']:+.2f}R)")
        cands.append({"symbol": sym, "market": "CMD", "score": score, "confidence": cal["confidence"] if cal else 0.5,
                      "entry": float(row["close"]), "stop": 1 / istop, "target": 1 / itarget, "rationale": why,
                      "expected_r": cal["expected_r"] if cal else 0.0, "direction": "short"})
    cands.sort(key=lambda c: c["score"] * (1 + c["expected_r"]), reverse=True)
    cands = cands[:12]
    jackpot_min = s.jackpot_score + (8 if label == "Risk-off" else 0)
    jp = 0
    rows, out = [], []
    for rank, c in enumerate(cands, 1):
        is_jp = jp < 3 and c["score"] >= jackpot_min and c["expected_r"] >= s.jackpot_min_edge
        jp += int(is_jp)
        pid = f"{d}:{c['symbol']}" + (":S" if c["direction"] == "short" else "")
        rows.append({"id": pid, "date": d, "symbol": c["symbol"], "market": c["market"], "direction": c["direction"],
                     "entry": c["entry"], "stop": c["stop"], "target": c["target"], "score": c["score"],
                     "confidence": c["confidence"], "expected_r": c["expected_r"], "rank": rank, "jackpot": int(is_jp), "rationale": c["rationale"],
                     "status": "open", "exit_date": None, "exit_price": None, "r_multiple": None})
        name = meta[c["symbol"]]["name"]
        out.append(A.make(d, "watch" if is_jp else "info", "pick",
                          f"{'JACKPOT ' if is_jp else ''}New {'SHORT ' if c['direction'] == 'short' else ''}pick: {name} (score {c['score']:.0f}, hit-rate {c['confidence'] * 100:.0f}%, edge {c['expected_r']:+.2f}R)",
                          f"Entry {c['entry']:.2f} · stop {c['stop']:.2f} · target {c['target']:.2f}", c["symbol"]))
    existing = {r["id"] for r in db.query("SELECT id FROM picks WHERE date=?", (d,))}
    db.upsert("picks", [r for r in rows if r["id"] not in existing])
    return out


def _views_and_stances(db: DB, d: str, ctx, frames, scores, idx_scores, short, reg, names, s: Settings) -> list[dict]:
    ts = pd.Timestamp(d)
    infl = influence.influencers(ctx, d)
    an = influence.analogs(ctx, d)
    ex = influence.expectations(ctx, d, an.get("forward", {}), names)
    db.upsert("daily_views", [{"date": d, "kind": "influencers", "payload": infl},
                              {"date": d, "kind": "analogs", "payload": an},
                              {"date": d, "kind": "expectations", "payload": ex}])
    label = reg.loc[ts, "label"] if ts in reg.index else "Neutral"
    exmap = {e["symbol"]: e for e in ex}
    rows, out = [], []
    prev = {r["symbol"]: r["stance"] for r in db.query(
        "SELECT symbol, stance FROM stances WHERE date=(SELECT MAX(date) FROM stances WHERE date<?)", (d,))}
    for sym in STANCE_SYMS:
        if sym not in frames or ts not in frames[sym][0].index:
            continue
        row = frames[sym][0].loc[ts]
        if pd.isna(row["atr"]):
            continue
        ls_series = scores.get(sym, idx_scores.get(sym))
        ls = float(ls_series.loc[ts]) if ls_series is not None and ts in ls_series.index else None
        ss = float(short[sym][0].loc[ts]) if sym in short and ts in short[sym][0].index else None
        st = stance.decide(sym, names[sym], row, ls, ss, exmap.get(sym), label, s.min_pick_score, s.reward_risk)
        rows.append({"date": d, "symbol": sym, "stance": st["stance"], "direction": st["direction"], "payload": st,
                     "ret_5d": None, "outcome": "pending", "checked_on": None})
        if prev.get(sym) and prev[sym] != st["stance"]:
            sev = "warning" if st["stance"] in ("BUY", "SELL") else "watch"
            out.append(A.make(d, sev, "stance", f"{names[sym]}: {prev[sym]} → {st['stance']}", st["rationale"][0], sym))
    existing = {(r["date"], r["symbol"]) for r in db.query("SELECT date, symbol FROM stances WHERE date=? AND outcome!='pending'", (d,))}
    db.upsert("stances", [r for r in rows if (r["date"], r["symbol"]) not in existing])
    return out


def _score_stances(db: DB, closes: dict[str, pd.Series]) -> None:
    for r in db.query("SELECT date, symbol, direction FROM stances WHERE outcome='pending'"):
        c = closes.get(r["symbol"])
        if c is None:
            continue
        res = stance.outcome(c, r["date"], r["direction"])
        if res:
            db.execute("UPDATE stances SET ret_5d=?, outcome=?, checked_on=? WHERE date=? AND symbol=?",
                       (res["ret_5d"], res["outcome"], res["checked_on"], r["date"], r["symbol"]))


# ----------------------------------------------------------------------------- orchestration
def run_job(db: DB, job: str, fn, *args, **kwargs):
    started = now_iso()
    try:
        res = fn(*args, **kwargs)
        db.log_run(job, started, now_iso(), "ok", str({k: v for k, v in (res or {}).items() if k != "calibration"})[:1500])
        return res
    except Exception as e:  # noqa: BLE001
        db.log_run(job, started, now_iso(), "error", f"{e}\n{traceback.format_exc()}")
        log.exception("job %s failed", job)
        return None


def run_all(db: DB, s: Settings | None = None, backfill_days: int = 5) -> dict:
    s = s or get_settings()
    out = {"prices": run_job(db, "collect_prices", collect_prices, db, s),
           "macro": run_job(db, "collect_macro", collect_macro, db, s),
           "news": run_job(db, "collect_news", collect_news, db, s)}
    last = db.query("SELECT MAX(date) d FROM prices")[0]["d"]
    if last:
        start = (pd.Timestamp(last) - pd.tseries.offsets.BDay(backfill_days)).date().isoformat()
        out["analyse"] = run_job(db, "analyse", analyse, db, start, last, s)
    return out
