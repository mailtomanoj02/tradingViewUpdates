import numpy as np
import pandas as pd
import pytest

from src.asia_sweep import _in_session_mask, _pivot_confirmations, compute_asia_sweep, latest_events


def _df(bars, start="2026-08-25 08:50", tz="UTC"):
    """bars: list of (open, high, low, close) 1-minute rows starting at `start`."""
    idx = pd.date_range(start, periods=len(bars), freq="1min", tz=tz)
    return pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=idx)


# --- session detection --------------------------------------------------------

def test_in_session_mask_overnight_wrap():
    idx = pd.to_datetime(
        ["2026-08-25 18:30", "2026-08-25 19:00", "2026-08-25 23:30",
         "2026-08-26 03:59", "2026-08-26 04:00", "2026-08-26 12:00"]
    ).tz_localize("UTC")
    mask = _in_session_mask(idx, "1900-0400", "UTC")
    assert list(mask) == [False, True, True, True, False, False]


def test_in_session_mask_same_day_window():
    idx = pd.to_datetime(
        ["2026-08-25 08:59", "2026-08-25 09:00", "2026-08-25 09:59", "2026-08-25 10:00"]
    ).tz_localize("UTC")
    assert list(_in_session_mask(idx, "0900-1000", "UTC")) == [False, True, True, False]


# --- pivots ------------------------------------------------------------------

def test_pivot_confirmations_strict_unique_extreme():
    highs = np.array([1.0, 2.0, 5.0, 2.0, 1.0, 3.0, 3.0, 3.0])
    ph, pl = _pivot_confirmations(highs, 2)
    # index 2 (value 5.0) is a strict unique max of [0..4] -> confirmed at index 4
    assert ph[4] == 5.0
    assert np.isnan(ph[:4]).all()
    # the flat 3.0 run produces no pivot high (tie)
    assert np.isnan(ph[5:]).all()


# --- a full sweep -> CHoCH -> short entry scenario --------------------------

def _short_entry_scenario():
    # session "0900-0910" UTC = bars 09:00..09:09; trend filter off.
    bars = []
    # 08:50..08:59 warm-up, flat, out of session
    bars += [(1.1020, 1.1020, 1.1020, 1.1020)] * 10
    # 09:00..09:09 Asia session -- high 1.1050 @ 09:04, low 1.1000 @ 09:06
    bars += [
        (1.1020, 1.1030, 1.1015, 1.1025),  # 09:00
        (1.1025, 1.1032, 1.1020, 1.1028),  # 09:01
        (1.1028, 1.1035, 1.1024, 1.1030),  # 09:02
        (1.1030, 1.1040, 1.1026, 1.1035),  # 09:03
        (1.1035, 1.1050, 1.1030, 1.1040),  # 09:04  <- session high
        (1.1040, 1.1045, 1.1020, 1.1025),  # 09:05
        (1.1025, 1.1030, 1.1000, 1.1010),  # 09:06  <- session low
        (1.1010, 1.1028, 1.1008, 1.1020),  # 09:07
        (1.1020, 1.1030, 1.1015, 1.1028),  # 09:08
        (1.1028, 1.1035, 1.1022, 1.1030),  # 09:09
    ]
    # 09:10 breakout + HIGH sweep (close > internal_high 1.1050 -> bullish BOS)
    bars += [
        (1.1030, 1.1055, 1.1048, 1.1052),  # 09:10
        (1.1052, 1.1053, 1.1040, 1.1042),  # 09:11
        (1.1042, 1.1044, 1.1035, 1.1043),  # 09:12  <- pivot low 1.1035
        (1.1043, 1.1048, 1.1041, 1.1047),  # 09:13
        (1.1047, 1.1049, 1.1043, 1.1048),  # 09:14  (confirms 09:12 pivot low)
        (1.1048, 1.1049, 1.1030, 1.1032),  # 09:15  close < 1.1035 -> bearish CHoCH -> SHORT
    ]
    return _df(bars)


def test_short_entry_scenario_produces_sweep_and_entry():
    df = _short_entry_scenario()
    result = compute_asia_sweep(
        df, session_str="0900-0910", timezone="UTC", internal_length=2,
        break_mode="Close", max_bars_after_sweep=10, trend_filter=False,
        target_multiples=(1.0, 2.0, 3.0), reward_rr=2.0, mintick=1e-5,
    )

    assert result["session_high"].iloc[-1] == pytest.approx(1.1050)
    assert result["session_low"].iloc[-1] == pytest.approx(1.1000)

    sweeps = result[result["high_sweep"]]
    assert len(sweeps) == 1
    assert sweeps.index[0] == df.index[20]  # 09:10

    entries = result[result["short_entry"]]
    assert len(entries) == 1
    row = entries.iloc[0]
    assert entries.index[0] == df.index[25]  # 09:15
    assert row["entry"] == pytest.approx(1.1032)
    assert row["stop_loss"] == pytest.approx(1.1055)
    r = 1.1055 - 1.1032
    assert row["target1"] == pytest.approx(1.1032 - r)
    assert row["target2"] == pytest.approx(1.1032 - 2 * r)
    assert row["target3"] == pytest.approx(1.1032 - 3 * r)
    assert not result["long_entry"].any()


def test_latest_events_reports_the_entry_on_the_last_bar():
    df = _short_entry_scenario()
    event = latest_events(
        "EURUSD", "1m", df, session_str="0900-0910", timezone="UTC",
        internal_length=2, break_mode="Close", max_bars_after_sweep=10,
        trend_filter=False, target_multiples=(1.0, 2.0, 3.0), reward_rr=2.0, mintick=1e-5,
    )
    assert event["sweep"] is None
    assert event["entry"]["direction"] == "SHORT"
    assert event["entry"]["entry"] == pytest.approx(1.1032)
    assert event["entry"]["risk_reward"]["target3"] == pytest.approx(3.0)
    assert "atr" in event["entry"] and event["entry"]["atr"] > 0


def test_latest_events_reports_the_sweep_on_the_sweep_bar():
    df = _short_entry_scenario().iloc[:21]  # cut at 09:10, the sweep bar
    event = latest_events(
        "EURUSD", "1m", df, session_str="0900-0910", timezone="UTC",
        internal_length=2, break_mode="Close", max_bars_after_sweep=10, trend_filter=False,
    )
    assert event["entry"] is None
    assert event["sweep"]["side"] == "HIGH"
    assert event["sweep"]["swept_level"] == pytest.approx(1.1050)
    assert event["sweep"]["session_low"] == pytest.approx(1.1000)


def test_max_bars_after_sweep_blocks_a_late_choch():
    df = _short_entry_scenario()
    result = compute_asia_sweep(
        df, session_str="0900-0910", timezone="UTC", internal_length=2,
        break_mode="Close", max_bars_after_sweep=3, trend_filter=False,
    )
    # the CHoCH is 5 bars after the breakout -- past the 3-bar limit
    assert not result["short_entry"].any()


def test_second_sweep_in_same_session_does_not_resignal():
    df = _short_entry_scenario()
    result = compute_asia_sweep(
        df, session_str="0900-0910", timezone="UTC", internal_length=2, trend_filter=False,
    )
    # 09:10 and 09:11 both trade above the Asia high, but only the first is a sweep
    assert result["high_sweep"].sum() == 1


def test_cancel_on_new_session_clears_an_active_trade():
    df = _short_entry_scenario()
    # append a fresh Asia session the next day starting 09:00 -- the active
    # short from 09:15 must be cancelled at that session's first bar.
    next_day = pd.date_range("2026-08-26 08:55", periods=8, freq="1min", tz="UTC")
    extra = pd.DataFrame(
        [(1.1032, 1.1033, 1.1031, 1.1032)] * 8,
        columns=["open", "high", "low", "close"], index=next_day,
    )
    combined = pd.concat([df, extra])
    result = compute_asia_sweep(
        combined, session_str="0900-0910", timezone="UTC", internal_length=2,
        trend_filter=False, close_trade_on_new_session=True,
    )
    # session_begins on 2026-08-26 09:00 -> a new Asia range starts there
    assert result.loc["2026-08-26 09:00", "session_high"] == pytest.approx(1.1033)


def test_trend_filter_blocks_a_short_above_the_ema():
    df = _short_entry_scenario()
    with_filter = compute_asia_sweep(
        df, session_str="0900-0910", timezone="UTC", internal_length=2,
        break_mode="Close", max_bars_after_sweep=10, trend_filter=True,
        trend_ema_length=50,
    )
    without = compute_asia_sweep(
        df, session_str="0900-0910", timezone="UTC", internal_length=2,
        break_mode="Close", max_bars_after_sweep=10, trend_filter=False,
    )
    # a slow 50-EMA barely moves off the 1.1020 warm-up level, so the CHoCH
    # close (1.1032) is ABOVE it -- a short is only allowed below the EMA.
    assert without["short_entry"].any()
    assert not with_filter["short_entry"].any()
