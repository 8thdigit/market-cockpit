import numpy as np
import pandas as pd
import pytest

from cockpit.engines import indicators, patterns, scoring, trades
from cockpit.providers.fixture import FixtureProvider


def bars(rows):
    idx = pd.bdate_range("2026-01-01", periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx, dtype=float)


@pytest.fixture
def series():
    return FixtureProvider(end="2026-11-27").daily("TEST", "2024-01-01")


def test_indicators_bounds(series):
    ind = indicators.compute(series)
    assert ind["rsi"].between(0, 100).all()
    assert (ind["atr"].dropna() > 0).all()
    assert ind["bb_pctile"].between(0, 1).all()
    assert {"ema20", "ema50", "ema200", "adx", "vol_ratio", "rs_63"} <= set(ind.columns)


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert indicators.rsi(up).iloc[-1] > 95
    assert indicators.rsi(up[::-1].reset_index(drop=True)).iloc[-1] < 5


def test_bullish_engulfing_detected():
    rows = [[110 - i, 111 - i, 108 - i, 109 - i, 1e6] for i in range(8)]  # steady decline
    rows.append([101.5, 102, 100, 100.5, 1e6])                         # down candle
    rows.append([100.2, 104, 100, 103.5, 2e6])                         # engulfs it
    p = patterns.detect(bars(rows))
    assert p["bullish_engulfing"].iloc[-1]


def test_three_line_strike_bull_detected():
    rows = [[120 - i, 121 - i, 118 - i, 119 - i, 1e6] for i in range(6)]
    rows += [[113, 113.5, 111, 111.5, 1e6], [111.5, 112, 109.5, 110, 1e6], [110, 110.5, 108, 108.5, 1e6]]
    rows.append([108.3, 114, 108, 113.5, 3e6])
    p = patterns.detect(bars(rows))
    assert p["three_line_strike_bull"].iloc[-1]


def test_score_range(series):
    ind = indicators.compute(series)
    sc = scoring.score(scoring.components(ind, patterns.detect(series)))
    assert sc.between(0, 100).all()


def test_simulate_target_and_stop():
    b = bars([[100, 101, 99, 100, 1], [100, 106, 99.5, 105, 1]])
    assert trades.simulate(b, 100, 97, 106, 15)[0] == "target"
    b = bars([[100, 101, 96, 97, 1]])
    st, _, px, r = trades.simulate(b, 100, 97, 106, 15)
    assert st == "stopped" and r == pytest.approx(-1)
    # both touched in one bar -> conservative stop
    b = bars([[100, 107, 96, 100, 1]])
    assert trades.simulate(b, 100, 97, 106, 15)[0] == "stopped"
    # gap below stop fills at the open
    b = bars([[95, 96, 94, 95, 1]])
    assert trades.simulate(b, 100, 97, 106, 15)[2] == 95


def test_levels_reward_risk():
    stop, target = trades.levels(100, 2, None, 2.0)
    assert stop == 97 and target == 106


def test_calibration_shrinks():
    summ = trades.summarise([{"bucket": "80-89", "win": True, "r": 2.0}] * 2)
    assert summ["80-89"]["hit_rate"] == 1.0
    assert summ["80-89"]["confidence"] < 0.6  # 2 wins of 2 is not 100% confidence
