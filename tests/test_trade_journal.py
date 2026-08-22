import numpy as np
import pandas as pd
import pytest

from src.halftrend import compute_halftrend
from src.trade_journal import compute_trade_outcomes, outcome_label, simulate_trade_outcome

TS = [pd.Timestamp("2026-08-22 10:00") + pd.Timedelta(minutes=5 * i) for i in range(10)]


def bar(i, high, low):
    return (TS[i], high, low)


def test_long_direct_stop_loss():
    # entry=100, sl=98, t1=102,t2=104,t3=106 -- price drops straight to SL
    future = [bar(0, 100.5, 97.5)]
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, future)
    assert result == {
        "wins_delta": 0,
        "losses_delta": 1,
        "final_exit": "SL",
        "close_time": TS[0],
        "r_multiple": -1.0,
    }


def test_short_direct_stop_loss():
    # entry=100, sl=102, t1=98,t2=96,t3=94 -- price rises straight to SL
    future = [bar(0, 102.5, 99.5)]
    result = simulate_trade_outcome("SHORT", 100, 102, 98, 96, 94, future)
    assert result["final_exit"] == "SL"
    assert result["r_multiple"] == -1.0
    assert result["wins_delta"] == 0
    assert result["losses_delta"] == 1


def test_long_tp1_then_stopped_is_a_scratch():
    future = [
        bar(0, 102.5, 99.0),   # touches TP1 (102)
        bar(1, 101.0, 97.5),   # later drops through SL (98)
    ]
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, future)
    assert result["wins_delta"] == 0
    assert result["losses_delta"] == 0
    assert result["final_exit"] == "SL"
    assert result["r_multiple"] == -1.0  # real money outcome is still a full stop
    assert result["close_time"] == TS[1]


def test_long_tp1_and_tp2_then_stopped_nets_one_win_zero_losses():
    future = [
        bar(0, 102.5, 99.0),   # TP1
        bar(1, 104.5, 101.0),  # TP2
        bar(2, 103.0, 97.5),   # SL
    ]
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, future)
    assert result["wins_delta"] == 1
    assert result["losses_delta"] == 0
    assert result["final_exit"] == "SL"
    assert result["r_multiple"] == -1.0


def test_long_full_run_to_tp3_sequentially():
    future = [
        bar(0, 102.5, 99.0),   # TP1
        bar(1, 104.5, 101.0),  # TP2
        bar(2, 106.5, 103.0),  # TP3 -- closes trade
    ]
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, future)
    assert result["wins_delta"] == 3
    assert result["losses_delta"] == 0
    assert result["final_exit"] == "TP3"
    assert result["r_multiple"] == 3.0
    assert result["close_time"] == TS[2]


def test_single_bar_gap_past_all_three_targets_only_credits_tp1_that_bar():
    # Pine's elif chain means only the FIRST satisfied branch (TP1) fires,
    # even though this bar's high already exceeds TP2 and TP3 too.
    future = [bar(0, 110.0, 99.5)]
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, future)
    assert result["wins_delta"] == 1
    assert result["final_exit"] == "open"  # trade stays open, TP2/TP3 still pending
    assert result["r_multiple"] is None


def test_same_bar_tp1_and_stop_cancels_out():
    # a single volatile bar touches both TP1 and the stop
    future = [bar(0, 102.5, 97.5)]
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, future)
    assert result["wins_delta"] == 0
    assert result["losses_delta"] == 0
    assert result["final_exit"] == "SL"
    assert result["r_multiple"] == -1.0


def test_never_resolves_stays_open():
    future = [bar(0, 100.2, 99.8), bar(1, 100.3, 99.7)]
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, future)
    assert result["final_exit"] == "open"
    assert result["close_time"] is None
    assert result["r_multiple"] is None
    assert result["wins_delta"] == 0
    assert result["losses_delta"] == 0


def test_no_future_bars_stays_open():
    result = simulate_trade_outcome("LONG", 100, 98, 102, 104, 106, [])
    assert result["final_exit"] == "open"
    assert result["r_multiple"] is None


def _bars(closes, spread=0.0005):
    index = pd.date_range("2026-01-01", periods=len(closes), freq="5min")
    closes = np.array(closes, dtype=float)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    high = np.maximum(opens, closes) + spread
    low = np.minimum(opens, closes) - spread
    return pd.DataFrame({"open": opens, "high": high, "low": low, "close": closes}, index=index)


def test_outcome_label_matches_the_four_described_outcomes():
    assert outcome_label("TP3", 3, 0) == "TP3 (full target)"
    assert outcome_label("SL", 0, 1) == "Direct Stop Loss"
    assert outcome_label("SL", 0, 0) == "TP1 then Stop (scratch)"
    assert outcome_label("SL", 1, 0) == "TP1+TP2 then Stop"
    assert outcome_label("open", 0, 0) == "Open / Unresolved"


def test_compute_trade_outcomes_end_to_end_on_synthetic_series():
    rise1 = list(np.linspace(90, 108, 15))
    decline = list(np.linspace(108, 90, 15))[1:]
    rise2 = list(np.linspace(90, 108, 15))[1:]
    df = _bars(rise1 + decline + rise2)

    result = compute_halftrend(df, amplitude=3, channel_deviation=2.0, base_risk_mult=3.0)
    trades = compute_trade_outcomes("EURUSD", "5m", result)

    assert len(trades) == 2  # the sell_signal then the buy_signal from this fixture
    for trade in trades:
        assert trade["direction"] in ("LONG", "SHORT")
        assert trade["r_multiple"] in (-1.0, 3.0, None)
        assert trade["outcome"] in (
            "Direct Stop Loss",
            "TP1 then Stop (scratch)",
            "TP1+TP2 then Stop",
            "TP3 (full target)",
            "Open / Unresolved",
        )
        if trade["close_time"] is not None:
            assert trade["close_time"] > trade["signal_time"]
        else:
            assert trade["r_multiple"] is None
