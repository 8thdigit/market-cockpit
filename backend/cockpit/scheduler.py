"""Background jobs. Times are UTC.

- Every 15 min while India (03:45-10:00) or US (14:30-21:00) cash markets are open: prices + analyse.
- Hourly: news + sentiment.
- 22:30 Mon-Fri (after US close): full run incl. FRED macro and a 10-day re-analysis.
"""
from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .db import DB
from . import pipeline as P

log = logging.getLogger("cockpit.scheduler")
_lock = threading.Lock()
_sched: BackgroundScheduler | None = None


def _guard(name, fn):
    def run():
        if not _lock.acquire(blocking=False):
            log.info("skip %s: another job is running", name)
            return
        try:
            fn()
        finally:
            _lock.release()
    return run


def _intraday(db: DB, s: Settings):
    P.run_job(db, "collect_prices", P.collect_prices, db, s)
    last = db.query("SELECT MAX(date) d FROM prices")[0]["d"]
    if last:
        P.run_job(db, "analyse", P.analyse, db, last, last, s)


def start(db: DB, s: Settings) -> BackgroundScheduler:
    global _sched
    if _sched:
        return _sched
    sch = BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600})
    sch.add_job(_guard("intraday", lambda: _intraday(db, s)),
                CronTrigger(day_of_week="mon-fri", hour="3-9,14-20", minute="*/15"), id="intraday")
    sch.add_job(_guard("news", lambda: P.run_job(db, "collect_news", P.collect_news, db, s)),
                CronTrigger(minute=5), id="news")
    sch.add_job(_guard("eod", lambda: P.run_all(db, s, backfill_days=10)),
                CronTrigger(day_of_week="mon-fri", hour=22, minute=30), id="eod")
    # Run once at boot if the database is empty or stale.
    sch.add_job(_guard("boot", lambda: P.run_all(db, s, backfill_days=10)), id="boot")
    sch.start()
    _sched = sch
    log.info("scheduler started")
    return sch
