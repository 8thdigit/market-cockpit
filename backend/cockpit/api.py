"""FastAPI app. Start with: python -m cockpit serve  (scheduler included unless --no-scheduler)."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, service
from .config import ROOT, get_settings
from .db import DB

settings = get_settings()
db = DB(settings.db_path)
app = FastAPI(title="Market Cockpit API", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["GET", "POST"],
                   allow_headers=["*"])


@app.on_event("startup")
def _startup():
    if os.environ.get("COCKPIT_SCHEDULER", "1") == "1":
        from .scheduler import start
        start(db, settings)


@app.get("/api/health")
def health():
    return service.health(db)


@app.get("/api/dates")
def dates():
    return {"dates": service.dates(db)}


@app.get("/api/snapshot")
def snapshot(date: str | None = None, severity: str | None = Query(None, pattern="^(info|watch|warning|critical)$")):
    return service.snapshot(db, date, severity, settings)


@app.get("/api/signals")
def signals(date: str | None = None, market: str | None = Query(None, pattern="^(IN|US|CMD)$"), min_score: float = 0):
    return service.signals(db, date, market, min_score)


@app.get("/api/instrument/{symbol}")
def instrument(symbol: str, date: str | None = None, bars: int = Query(260, ge=30, le=1500)):
    res = service.instrument(db, symbol, date, bars)
    if not res["bars"]:
        raise HTTPException(404, f"no data for {symbol}")
    return res


@app.get("/api/track-record")
def track_record(date: str | None = None):
    return service.track_record(db, date)


@app.post("/api/run")
def run_now():
    """Trigger a full collect + analyse cycle (runs synchronously)."""
    from .pipeline import run_all
    res = run_all(db, settings)
    return {"ok": True, "result": {k: (v if k != "analyse" else {kk: vv for kk, vv in (v or {}).items() if kk != "calibration"})
                                   for k, v in res.items()}}


# Serve the built dashboard if present (single-container deploys).
DIST = Path(os.environ.get("COCKPIT_DIST", ROOT / "frontend" / "dist"))
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
