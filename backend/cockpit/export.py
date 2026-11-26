"""Static export: the dashboard can run from plain JSON files (GitHub Pages) with the same views as the API."""
from __future__ import annotations

import json
from pathlib import Path

from . import service
from .db import DB


def _w(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, default=str, separators=(",", ":")))


def export(db: DB, out: str, days: int = 60) -> dict:
    root = Path(out)
    all_dates = service.dates(db)[-days:]
    for d in all_dates:
        _w(root / "snapshot" / f"{d}.json", service.snapshot(db, d))
        _w(root / "signals" / f"{d}.json", service.signals(db, d))
    latest = all_dates[-1] if all_dates else None
    syms = sorted({r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM prices")})
    for sym in syms:
        safe = sym.replace("^", "_").replace("=", "_").replace("&", "_")
        _w(root / "instrument" / f"{safe}.json", service.instrument(db, sym, latest, 400))
    _w(root / "track-record.json", service.track_record(db, latest))
    _w(root / "health.json", service.health(db))
    _w(root / "dates.json", {"dates": all_dates})
    return {"dates": len(all_dates), "instruments": len(syms), "latest": latest}
