"""Alert rules. Severity: info < watch < warning < critical. Alert ids are deterministic so reruns don't duplicate."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pandas as pd

SEVERITIES = ["info", "watch", "warning", "critical"]
MACRO_WATCH = {"^GSPC", "^NDX", "^NSEI", "^BSESN", "GC=F", "SI=F", "BZ=F", "CL=F", "DX-Y.NYB", "INR=X", "^VIX", "^TNX"}


def make(date: str, severity: str, category: str, title: str, detail: str = "", symbol: str = "") -> dict:
    aid = hashlib.sha1(f"{date}|{category}|{symbol}|{title}".encode()).hexdigest()[:16]
    return {"id": aid, "date": date, "ts": datetime.now(timezone.utc).isoformat(), "severity": severity,
            "category": category, "symbol": symbol, "title": title, "detail": detail}


def market_alerts(date: str, frames: dict[str, pd.DataFrame], names: dict[str, str]) -> list[dict]:
    out = []
    ts = pd.Timestamp(date)
    for sym, df in frames.items():
        if df is None or df.empty or ts not in df.index:
            continue
        row = df.loc[ts]
        name = names.get(sym, sym)
        is_macro = sym in MACRO_WATCH
        if sym == "^TNX":
            prev = df["close"].shift(1).loc[ts]
            bp = (row["close"] - prev) * 100 if pd.notna(prev) else 0
            if abs(bp) >= 12:
                out.append(make(date, "warning", "rates", f"US 10-yr yield moved {bp:+.0f} bp to {row['close']:.2f}%",
                                "Large daily move in long yields: expect knock-on in gold, the dollar and growth stocks.", sym))
            continue
        if sym == "^VIX":
            if row["close"] >= 30:
                out.append(make(date, "critical", "volatility", f"VIX at {row['close']:.1f} — fear regime",
                                "Above 30: reduce position size, widen stops or stand aside.", sym))
            elif row["close"] >= 25:
                out.append(make(date, "warning", "volatility", f"VIX elevated at {row['close']:.1f}",
                                "Above 25: half size on new swing trades.", sym))
            continue
        r1 = row.get("ret1", 0) or 0
        sd = df["ret1"].rolling(60, min_periods=20).std().loc[ts]
        if pd.notna(sd) and sd > 0 and abs(r1) >= 2.5 * sd and abs(r1) >= 0.015:
            sev = "critical" if abs(r1) >= 4 * sd else "warning"
            out.append(make(date, sev if is_macro else "watch", "move", f"{name} {r1 * 100:+.1f}% — {abs(r1) / sd:.1f}σ move",
                            "Unusually large daily move versus the last 60 sessions.", sym))
        if is_macro:
            rsi = row.get("rsi", 50)
            if rsi >= 75:
                out.append(make(date, "watch", "momentum", f"{name} overbought (RSI {rsi:.0f})", "Pullback risk rises above 75.", sym))
            elif rsi <= 25:
                out.append(make(date, "watch", "momentum", f"{name} oversold (RSI {rsi:.0f})",
                                "Watch for a selling climax and reversal candle before buying.", sym))
            if row.get("dist_high", -1) >= -0.002:
                out.append(make(date, "watch", "breakout", f"{name} at a 52-week high", "", sym))
    return out


def pattern_alerts(date: str, sym: str, name: str, patterns: list[str], score: float, prev_score: float | None) -> list[dict]:
    out = []
    strong = [p for p in patterns if p in {"three_line_strike_bull", "three_white_soldiers", "morning_star",
                                           "selling_climax", "three_black_crows", "evening_star", "bearish_engulfing"}]
    if strong and (sym in MACRO_WATCH or score >= 60):
        out.append(make(date, "watch", "pattern", f"{name}: {', '.join(p.replace('_', ' ') for p in strong)}",
                        f"Setup score {score:.0f}.", sym))
    if prev_score is not None and prev_score < 70 <= score:
        out.append(make(date, "watch", "setup", f"{name} setup score crossed 70 ({score:.0f})", "", sym))
    return out


def event_alerts(date: str, events: list[dict]) -> list[dict]:
    out = []
    ref = pd.Timestamp(date).tz_localize("UTC") + timedelta(days=1)
    now = pd.Timestamp.now(tz="UTC")
    ref = min(ref, now) if now > pd.Timestamp(date).tz_localize("UTC") else ref
    for e in events:
        ts = pd.Timestamp(e["ts"])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
        hours = (ts - ref).total_seconds() / 3600
        if hours <= 0:
            continue
        if hours <= 24 and e["impact"] in ("high", "very_high"):
            sev = "critical" if e["impact"] == "very_high" else "warning"
        elif hours <= 72 and e["impact"] in ("high", "very_high"):
            sev = "warning" if e["impact"] == "very_high" else "watch"
        elif hours <= 24:
            sev = "info"
        else:
            continue
        out.append(make(date, sev, "event", f"{e['title']} in {hours:.0f}h",
                        "Avoid opening new positions right before the event; stops can gap.", ",".join(e.get("assets", []))))
    return out
