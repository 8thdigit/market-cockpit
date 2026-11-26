from __future__ import annotations

from ..config import Settings
from .fixture import FixtureMacro, FixtureProvider
from .fred import FredProvider
from .yahoo import YahooProvider


def price_provider(s: Settings):
    return FixtureProvider() if s.provider == "fixture" else YahooProvider()


def macro_provider(s: Settings):
    return FixtureMacro() if s.provider == "fixture" else FredProvider(s.fred_api_key)
