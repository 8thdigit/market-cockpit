"""SQLite storage. One file, WAL mode, safe for a single writer (the scheduler) and many readers (the API)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
  symbol TEXT PRIMARY KEY, name TEXT, market TEXT, kind TEXT, sector TEXT,
  tradable INTEGER, benchmark TEXT
);
CREATE TABLE IF NOT EXISTS prices (
  symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT,
  PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS macro (
  series TEXT, date TEXT, value REAL, source TEXT, PRIMARY KEY (series, date)
);
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, ts TEXT, date TEXT, source TEXT, title TEXT, url TEXT,
  sentiment REAL, topics TEXT
);
CREATE TABLE IF NOT EXISTS signals (
  date TEXT, symbol TEXT, market TEXT, close REAL, score REAL, components TEXT, patterns TEXT,
  rsi REAL, atr REAL, atr_pct REAL, vol_ratio REAL, bb_pctile REAL, rs_63 REAL, adx REAL,
  ema20 REAL, ema50 REAL, ema200 REAL, trend TEXT, PRIMARY KEY (date, symbol)
);
CREATE TABLE IF NOT EXISTS regime (
  date TEXT PRIMARY KEY, score REAL, label TEXT, components TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY, date TEXT, ts TEXT, severity TEXT, category TEXT, symbol TEXT,
  title TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS picks (
  id TEXT PRIMARY KEY, date TEXT, symbol TEXT, market TEXT, direction TEXT,
  entry REAL, stop REAL, target REAL, score REAL, confidence REAL, expected_r REAL, rank INTEGER, jackpot INTEGER,
  rationale TEXT, status TEXT, exit_date TEXT, exit_price REAL, r_multiple REAL
);
CREATE TABLE IF NOT EXISTS calibration (
  market TEXT, bucket TEXT, trades INTEGER, wins INTEGER, hit_rate REAL, avg_r REAL, expected_r REAL, updated TEXT,
  PRIMARY KEY (market, bucket)
);
CREATE TABLE IF NOT EXISTS daily_views (
  date TEXT, kind TEXT, payload TEXT, PRIMARY KEY (date, kind)
);
CREATE TABLE IF NOT EXISTS stances (
  date TEXT, symbol TEXT, stance TEXT, direction INTEGER, payload TEXT,
  ret_5d REAL, outcome TEXT, checked_on TEXT, PRIMARY KEY (date, symbol)
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, started TEXT, finished TEXT, status TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS source_health (
  source TEXT PRIMARY KEY, last_ok TEXT, last_error TEXT, last_error_msg TEXT, items INTEGER
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);
CREATE INDEX IF NOT EXISTS idx_alerts_date ON alerts(date);
CREATE INDEX IF NOT EXISTS idx_picks_date ON picks(date);
CREATE INDEX IF NOT EXISTS idx_news_date ON news(date);
"""


class DB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mem = sqlite3.connect(":memory:", check_same_thread=False) if str(path) == ":memory:" else None
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        if self._mem is not None:
            yield self._mem
            self._mem.commit()
            return
        c = sqlite3.connect(self.path, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---------- generic helpers ----------
    def upsert(self, table: str, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        cols = list(rows[0].keys())
        sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        vals = [[_enc(r.get(k)) for k in cols] for r in rows]
        with self.conn() as c:
            c.executemany(sql, vals)
        return len(rows)

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self.conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(sql, params).fetchall()
            c.row_factory = None
        return [dict(r) for r in rows]

    def df(self, sql: str, params: tuple | list = ()) -> pd.DataFrame:
        with self.conn() as c:
            return pd.read_sql_query(sql, c, params=params)

    def execute(self, sql: str, params: tuple | list = ()) -> None:
        with self.conn() as c:
            c.execute(sql, params)

    # ---------- domain helpers ----------
    def prices(self, symbol: str, end: str | None = None, limit: int | None = None) -> pd.DataFrame:
        sql = "SELECT date, open, high, low, close, volume FROM prices WHERE symbol=?"
        params: list = [symbol]
        if end:
            sql += " AND date<=?"
            params.append(end)
        sql += " ORDER BY date"
        df = self.df(sql, params)
        if limit:
            df = df.tail(limit)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        return df

    def macro_series(self, series: str, end: str | None = None) -> pd.Series:
        sql = "SELECT date, value FROM macro WHERE series=?"
        params: list = [series]
        if end:
            sql += " AND date<=?"
            params.append(end)
        df = self.df(sql + " ORDER BY date", params)
        if df.empty:
            return pd.Series(dtype=float)
        return pd.Series(df["value"].values, index=pd.to_datetime(df["date"]), name=series)

    def log_run(self, job: str, started: str, finished: str, status: str, message: str = "") -> None:
        self.execute("INSERT INTO runs (job, started, finished, status, message) VALUES (?,?,?,?,?)",
                     (job, started, finished, status, message[:2000]))

    def source_ok(self, source: str, ts: str, items: int) -> None:
        self.execute(
            "INSERT INTO source_health (source, last_ok, items) VALUES (?,?,?) "
            "ON CONFLICT(source) DO UPDATE SET last_ok=excluded.last_ok, items=excluded.items",
            (source, ts, items))

    def source_error(self, source: str, ts: str, msg: str) -> None:
        self.execute(
            "INSERT INTO source_health (source, last_error, last_error_msg) VALUES (?,?,?) "
            "ON CONFLICT(source) DO UPDATE SET last_error=excluded.last_error, last_error_msg=excluded.last_error_msg",
            (source, ts, msg[:500]))


def _enc(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    if hasattr(v, "item"):  # numpy scalars
        return v.item()
    return v


def dec(v, default=None):
    if v is None:
        return default
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default
