import numpy as np
import pandas as pd
import pytest

from src.halftrend import compute_halftrend, wilder_atr


def _bars(closes, spread=0.0005):
    """Build a minimal OHLC DataFrame from a list of closes."""
    index = pd.date_range("2026-01-01", periods=len(closes), freq="5min")
    closes = np.array(closes, dtype=float)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    high = np.maximum(opens, closes) + spread
    low = np.minimum(opens, closes) - spread
    return pd.DataFrame({"open": opens, "high": high, "low": low, "close": closes}, index=index)


def test_wilder_atr_matches_hand_computed_rma():
    high = pd.Series([10.0, 11.0, 10.5, 12.0])
    low = pd.Series([9.0, 9.5, 9.0, 10.0])
    close = pd.Series([9.5, 10.5, 9.5, 11.5])

    # true range: bar0 = high-low (no prev close); bars 1-3 = max of the 3 Pine TR components
    tr0 = 10.0 - 9.0
    tr1 = max(11.0 - 9.5, abs(11.0 - 9.5), abs(9.5 - 9.5))
    tr2 = max(10.5 - 9.0, abs(10.5 - 10.5), abs(9.0 - 10.5))
    tr3 = max(12.0 - 10.0, abs(12.0 - 9.5), abs(10.0 - 9.5))

    length = 2
    expected = [tr0]
    for tr in (tr1, tr2, tr3):
        expected.append(expected[-1] + (tr - expected[-1]) / length)

    atr = wilder_atr(high, low, close, length=length)
    assert atr.tolist() == pytest.approx(expected)


def test_no_signal_columns_on_flat_series():
    df = _bars([100.0] * 40)
    result = compute_halftrend(df, amplitude=3, channel_deviation=2.0, base_risk_mult=3.0)
    assert not result["buy_signal"].any()
    assert not result["sell_signal"].any()


def _arm_decline_rally_bars():
    """Rise -> decline -> rise, each phase strong enough to actually cross
    the relevant threshold (not just a token tick).

    The ported `nextTrend` staging variable (CLAUDE.md section 3) means a
    bearish flip can only fire once a prior bullish breakout has armed it
    -- a plain decline starting from the default fresh state never arms
    that path on its own. So a genuine bearish->bullish (buy_signal)
    transition needs: a rise (arms the bearish check), a decline strong
    enough to actually trigger it (bearish flip / sell_signal), then a
    second rise strong enough to flip back (bullish flip / buy_signal,
    the thing under test). Verified against a bar-by-bar debug trace
    before being used here -- see project history.
    """
    rise1 = list(np.linspace(90, 108, 15))
    decline = list(np.linspace(108, 90, 15))[1:]
    rise2 = list(np.linspace(90, 108, 15))[1:]
    return rise1 + decline + rise2


def test_buy_signal_fires_on_sharp_v_shaped_recovery_with_correct_entry_math():
    df = _bars(_arm_decline_rally_bars())

    result = compute_halftrend(df, amplitude=3, channel_deviation=2.0, base_risk_mult=3.0)

    assert result["buy_signal"].any(), "expected a bullish flip during the sharp recovery"
    assert not (result["buy_signal"] & result["sell_signal"]).any()

    signal_rows = result[result["buy_signal"]]
    dist = signal_rows["atr2"] * 3.0
    assert signal_rows["entry"].tolist() == pytest.approx(signal_rows["close"].tolist())
    assert (signal_rows["stop_loss"] == signal_rows["close"] - dist).all()
    assert (signal_rows["target1"] == signal_rows["close"] + dist).all()
    assert (signal_rows["target2"] == signal_rows["close"] + dist * 2).all()
    assert (signal_rows["target3"] == signal_rows["close"] + dist * 3).all()


def test_sell_signal_fires_on_sharp_inverted_v_drop_with_correct_entry_math():
    rally = list(np.linspace(100, 110, 15))
    drop = list(np.linspace(110, 92, 15))[1:]
    df = _bars(rally + drop)

    result = compute_halftrend(df, amplitude=3, channel_deviation=2.0, base_risk_mult=3.0)

    assert result["sell_signal"].any(), "expected a bearish flip during the sharp decline"
    assert not (result["buy_signal"] & result["sell_signal"]).any()

    signal_rows = result[result["sell_signal"]]
    dist = signal_rows["atr2"] * 3.0
    assert signal_rows["entry"].tolist() == pytest.approx(signal_rows["close"].tolist())
    assert (signal_rows["stop_loss"] == signal_rows["close"] + dist).all()
    assert (signal_rows["target1"] == signal_rows["close"] - dist).all()
    assert (signal_rows["target2"] == signal_rows["close"] - dist * 2).all()
    assert (signal_rows["target3"] == signal_rows["close"] - dist * 3).all()


def test_buy_signal_requires_previous_bar_to_be_bearish():
    df = _bars(_arm_decline_rally_bars())
    result = compute_halftrend(df, amplitude=3, channel_deviation=2.0, base_risk_mult=3.0)
    flips = result[result["buy_signal"]]
    assert not flips.empty, "expected at least one buy_signal to actually check"
    prev_trend = result["trend"].shift(1)
    assert (prev_trend.loc[flips.index] == 1).all()
