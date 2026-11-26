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


def test_four_pages(client):
    i = client.get("/api/page/influencers").json()
    assert i["influencers"] and i["markets"] and i["expectations"]
    assert all(m["stance"] in {"BUY", "SELL", "ACCUMULATE DIPS", "SELL RALLIES", "WAIT"} for m in i["markets"])
    h = client.get("/api/page/history").json()
    assert h["episodes"] and "analogs" in h
    st = client.get("/api/page/stocks").json()
    assert set(st["record"]) == {"all", "IN", "US", "jackpot"}
    c = client.get("/api/page/commodities").json()
    assert len(c["stances"]) == 4
    assert {"met", "failed", "success"} <= set(c["stance_record"]["overall"])


def test_short_simulation_mirror():
    import pandas as pd
    from cockpit.engines import indicators, trades
    idx = pd.bdate_range("2026-01-01", periods=2)
    bars = pd.DataFrame({"open": [100, 99], "high": [101, 99.5], "low": [98, 93], "close": [99, 94], "volume": [1, 1]}, index=idx)
    # short from 100, stop 103, target 94 -> target hit on day 2 (low 93)
    res = trades.simulate(indicators.invert(bars), 1 / 100, 1 / 103, 1 / 94, 15)
    assert res[0] == "target"


def test_predictions_and_recommended(client):
    i = client.get("/api/page/influencers").json()
    p = i["predictions"]
    assert p["rows"] and all(r["call"] in {"BUY", "SELL", "WATCH"} and 0 <= r["confidence"] <= 100 for r in p["rows"])
    assert all("exit" in r for r in p["rows"])
    assert p["overall"]["n"] >= 0 and isinstance(p["sets"], list)
    st = client.get("/api/page/stocks").json()
    for mkt in ("IN", "US"):
        for r in st["recommended"][mkt]:
            assert r["call"] in {"BUY", "WATCH"} and r["exit"] > r["entry"] > r["stop"]
