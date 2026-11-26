"""Headline collection from public RSS feeds, scored with VADER plus a finance lexicon."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from .base import retry

log = logging.getLogger("cockpit.news")


def _gnews(q: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"


FEEDS = {
    "fed": "https://www.federalreserve.gov/feeds/press_all.xml",
    "rbi": "https://www.rbi.org.in/pressreleases_rss.xml",
    "eia": "https://www.eia.gov/rss/todayinenergy.xml",
    "gn_gold": _gnews("gold price when:2d"),
    "gn_oil": _gnews("crude oil Brent OPEC when:2d"),
    "gn_fed": _gnews("Federal Reserve rates inflation when:2d"),
    "gn_india": _gnews("Sensex Nifty market when:2d"),
    "gn_us": _gnews("Wall Street stocks S&P 500 when:2d"),
    "gn_geo": _gnews("Iran Strait of Hormuz when:2d"),
    "gn_dollar": _gnews("US dollar index Treasury yields when:2d"),
}

TOPICS = {
    "fed": ["fed", "fomc", "powell", "warsh", "rate hike", "rate cut", "federal reserve"],
    "inflation": ["inflation", "cpi", "pce", "prices rose"],
    "gold": ["gold", "bullion", "precious metal"],
    "oil": ["oil", "crude", "brent", "wti", "opec"],
    "india": ["nifty", "sensex", "rbi", "rupee", "india"],
    "us_equities": ["s&p", "nasdaq", "dow", "wall street", "stocks"],
    "geopolitics": ["iran", "hormuz", "war", "strike", "missile", "sanction", "ceasefire"],
    "dollar": ["dollar", "dxy", "treasury", "yield"],
}

# Finance-specific word scores layered onto VADER.
LEXICON = {
    "surge": 2.0, "rally": 2.0, "soar": 2.2, "jump": 1.5, "gain": 1.2, "record high": 2.0, "beat": 1.2,
    "plunge": -2.4, "crash": -3.0, "slump": -2.0, "tumble": -2.0, "selloff": -2.0, "sell-off": -2.0,
    "rout": -2.4, "slide": -1.4, "fall": -1.0, "falls": -1.0, "drop": -1.2, "hawkish": -1.0,
    "dovish": 1.0, "recession": -2.0, "default": -2.0, "escalation": -1.8, "ceasefire": 1.5,
    "glut": -1.5, "surplus": -0.8, "shortage": -1.0, "bear market": -2.2, "correction": -1.2,
}

_analyzer = None


def sentiment(text: str) -> float:
    global _analyzer
    if _analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _analyzer = SentimentIntensityAnalyzer()
        _analyzer.lexicon.update(LEXICON)
    return float(_analyzer.polarity_scores(text)["compound"])


def topics_for(text: str) -> list[str]:
    t = text.lower()
    return [k for k, words in TOPICS.items() if any(w in t for w in words)]


def fetch_feed(source: str, url: str) -> list[dict]:
    def _get():
        r = httpx.get(url, timeout=20, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (MarketCockpit RSS reader)"})
        r.raise_for_status()
        return r.content

    parsed = feedparser.parse(retry(_get, attempts=2, what=f"rss:{source}"))
    out = []
    for e in parsed.entries[:40]:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        ts = None
        for key in ("published_parsed", "updated_parsed"):
            if e.get(key):
                ts = datetime(*e[key][:6], tzinfo=timezone.utc)
                break
        ts = ts or datetime.now(timezone.utc)
        link = e.get("link", "")
        out.append({
            "id": hashlib.sha1((title + link).encode()).hexdigest()[:16],
            "ts": ts.isoformat(), "date": ts.date().isoformat(), "source": source, "title": title[:400],
            "url": link if link.startswith(("http://", "https://")) else "",
            "sentiment": sentiment(title), "topics": topics_for(title + " " + source.replace("gn_", "")),
        })
    return out
