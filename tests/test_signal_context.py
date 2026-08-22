import pandas as pd
import pytest

from src.halftrend import atr_volatility_label, risk_reward_ratios


def test_risk_reward_is_1_2_3_by_construction_long():
    entry, stop_loss = 1.0842, 1.0821
    dist = entry - stop_loss
    t1, t2, t3 = entry + dist, entry + dist * 2, entry + dist * 3

    rr = risk_reward_ratios(entry, stop_loss, t1, t2, t3)

    assert rr["target1"] == pytest.approx(1.0)
    assert rr["target2"] == pytest.approx(2.0)
    assert rr["target3"] == pytest.approx(3.0)


def test_risk_reward_is_1_2_3_by_construction_short():
    entry, stop_loss = 4602.30, 4608.10
    dist = stop_loss - entry
    t1, t2, t3 = entry - dist, entry - dist * 2, entry - dist * 3

    rr = risk_reward_ratios(entry, stop_loss, t1, t2, t3)

    assert rr["target1"] == pytest.approx(1.0)
    assert rr["target2"] == pytest.approx(2.0)
    assert rr["target3"] == pytest.approx(3.0)


def test_atr_label_normal_when_close_to_baseline():
    series = pd.Series([10.0] * 60)
    assert atr_volatility_label(series, window=50, band=0.10) == "normal"


def test_atr_label_above_average_when_current_spikes():
    series = pd.Series([10.0] * 59 + [15.0])  # current is 50% above the flat baseline
    assert atr_volatility_label(series, window=50, band=0.10) == "above-average"


def test_atr_label_below_average_when_current_drops():
    series = pd.Series([10.0] * 59 + [7.0])  # current is 30% below the flat baseline
    assert atr_volatility_label(series, window=50, band=0.10) == "below-average"


def test_atr_label_uses_available_history_when_shorter_than_window():
    series = pd.Series([10.0, 10.0, 10.0])
    assert atr_volatility_label(series, window=50, band=0.10) == "normal"


def test_atr_label_ignores_nan_warmup_rows():
    series = pd.Series([float("nan")] * 100 + [10.0] * 60)
    assert atr_volatility_label(series, window=50, band=0.10) == "normal"


def test_atr_label_raises_on_empty_series():
    with pytest.raises(ValueError):
        atr_volatility_label(pd.Series([], dtype=float))
