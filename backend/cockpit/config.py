"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env support: KEY=VALUE lines; real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(_env("COCKPIT_DB", str(ROOT / "data" / "cockpit.db"))))
    config_dir: Path = field(default_factory=lambda: Path(_env("COCKPIT_CONFIG", str(ROOT / "config"))))
    # "yahoo" for live data, "fixture" for deterministic offline data (tests / demos).
    provider: str = field(default_factory=lambda: _env("COCKPIT_PROVIDER", "yahoo"))
    fred_api_key: str = field(default_factory=lambda: _env("FRED_API_KEY", ""))
    history_days: int = field(default_factory=lambda: int(_env("COCKPIT_HISTORY_DAYS", "750")))
    # indices, commodities, FX and rates get a long history for the analog/history engines
    macro_years: int = field(default_factory=lambda: int(_env("COCKPIT_MACRO_YEARS", "15")))
    news_enabled: bool = field(default_factory=lambda: _env("COCKPIT_NEWS", "1") == "1")
    cors_origins: str = field(default_factory=lambda: _env("COCKPIT_CORS", "*"))
    # Trading rules
    min_pick_score: float = field(default_factory=lambda: float(_env("COCKPIT_MIN_PICK_SCORE", "70")))
    jackpot_score: float = field(default_factory=lambda: float(_env("COCKPIT_JACKPOT_SCORE", "80")))
    # minimum calibrated expectancy (R per trade, shrunk) for a Jackpot pick
    jackpot_min_edge: float = field(default_factory=lambda: float(_env("COCKPIT_JACKPOT_MIN_EDGE", "0.15")))
    reward_risk: float = field(default_factory=lambda: float(_env("COCKPIT_REWARD_RISK", "2.0")))
    max_hold_days: int = field(default_factory=lambda: int(_env("COCKPIT_MAX_HOLD_DAYS", "15")))

    def universe(self) -> dict:
        return json.loads((self.config_dir / "universe.json").read_text())

    def episodes(self) -> list[dict]:
        p = self.config_dir / "episodes.json"
        return json.loads(p.read_text())["episodes"] if p.exists() else []

    def events(self) -> list[dict]:
        return json.loads((self.config_dir / "events.json").read_text())["events"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def instruments(settings: Settings | None = None) -> list[dict]:
    """Flatten the universe into instrument dicts."""
    s = settings or get_settings()
    u = s.universe()
    out = [dict(i, sector=i.get("kind"), tradable=i.get("tradable", False)) for i in u["macro"]]
    for market, block in u["equities"].items():
        for sym, name, sector in block["symbols"]:
            out.append({"symbol": sym, "name": name, "market": market, "kind": "equity",
                        "sector": sector, "tradable": True, "benchmark": block["benchmark"]})
    for i in out:
        if i["kind"] == "commodity":
            i["benchmark"] = None
    return out
