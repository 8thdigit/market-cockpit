"""CLI: python -m cockpit [run|backfill|serve|export|status]"""
from __future__ import annotations

import argparse
import json
import logging
import os

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser(prog="cockpit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect all sources and analyse recent days")
    r.add_argument("--days", type=int, default=5, help="re-analyse this many recent trading days")
    b = sub.add_parser("backfill", help="collect and analyse a long history (builds track record + trends)")
    b.add_argument("--days", type=int, default=250)
    sv = sub.add_parser("serve", help="start API (+ scheduler)")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--no-scheduler", action="store_true")
    ex = sub.add_parser("export", help="write static JSON for the dashboard (GitHub Pages mode)")
    ex.add_argument("--out", default="frontend/public/data")
    ex.add_argument("--days", type=int, default=60, help="how many recent dates to export")
    sub.add_parser("status", help="print source health")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .config import get_settings
    from .db import DB
    from . import pipeline as P

    s = get_settings()
    db = DB(s.db_path)
    if args.cmd == "run":
        res = P.run_all(db, s, backfill_days=args.days)
        print(json.dumps({k: (v if k != "analyse" else {kk: vv for kk, vv in (v or {}).items() if kk != "calibration"})
                          for k, v in res.items()}, indent=2, default=str))
    elif args.cmd == "backfill":
        P.run_job(db, "collect_prices", P.collect_prices, db, s)
        P.run_job(db, "collect_macro", P.collect_macro, db, s)
        P.run_job(db, "collect_news", P.collect_news, db, s)
        last = db.query("SELECT MAX(date) d FROM prices")[0]["d"]
        start = (pd.Timestamp(last) - pd.tseries.offsets.BDay(args.days)).date().isoformat()
        res = P.run_job(db, "analyse", P.analyse, db, start, last, s)
        print(json.dumps({k: v for k, v in (res or {}).items()}, indent=2, default=str))
    elif args.cmd == "serve":
        import uvicorn
        if args.no_scheduler:
            os.environ["COCKPIT_SCHEDULER"] = "0"
        uvicorn.run("cockpit.api:app", host=args.host, port=args.port)
    elif args.cmd == "export":
        from .export import export
        print(json.dumps(export(db, args.out, args.days), indent=2))
    elif args.cmd == "status":
        from . import service
        print(json.dumps(service.health(db), indent=2, default=str))


if __name__ == "__main__":
    main()
