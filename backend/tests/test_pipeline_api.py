import importlib

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "t.db"
    mp = pytest.MonkeyPatch()
    mp.setenv("COCKPIT_PROVIDER", "fixture")
    mp.setenv("COCKPIT_DB", str(db_path))
    mp.setenv("COCKPIT_SCHEDULER", "0")
    mp.setenv("COCKPIT_HISTORY_DAYS", "500")
    from cockpit import config
    config.get_settings.cache_clear()
    from cockpit import pipeline
    from cockpit.db import DB
    s = config.get_settings()
    db = DB(s.db_path)
    pipeline.collect_prices(db, s)
    pipeline.collect_macro(db, s)
    last = db.query("SELECT MAX(date) d FROM prices")[0]["d"]
    import pandas as pd
    start = (pd.Timestamp(last) - pd.tseries.offsets.BDay(40)).date().isoformat()
    res = pipeline.analyse(db, start, last, s)
    assert res["days"] > 30
    from cockpit import api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    yield TestClient(api.app)
    mp.undo()
    config.get_settings.cache_clear()


def test_snapshot(client):
    r = client.get("/api/snapshot").json()
    assert r["date"] and r["regime"]["label"] in {"Risk-on", "Neutral", "Risk-off"}
    assert len(r["tiles"]) >= 10
    assert set(r["alert_counts"]) == {"info", "watch", "warning", "critical"}


def test_snapshot_date_and_severity(client):
    dates = client.get("/api/dates").json()["dates"]
    mid = dates[len(dates) // 2]
    r = client.get("/api/snapshot", params={"date": mid, "severity": "warning"}).json()
    assert r["date"] == mid
    assert all(a["severity"] in ("warning", "critical") for a in r["alerts"])
    assert client.get("/api/snapshot", params={"severity": "bogus"}).status_code == 422


def test_signals_and_instrument(client):
    s = client.get("/api/signals", params={"market": "US"}).json()
    assert s["signals"] and all(x["market"] == "US" for x in s["signals"])
    i = client.get("/api/instrument/GC=F").json()
    assert len(i["bars"]) > 100
    assert client.get("/api/instrument/NOPE").status_code == 404


def test_track_record_and_health(client):
    t = client.get("/api/track-record").json()
    assert "overall" in t and "calibration" in t
    h = client.get("/api/health").json()
    assert h["freshness"]
