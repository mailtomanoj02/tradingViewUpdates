from src.halftrend import (
    DEFAULT_AMPLITUDE,
    DEFAULT_BASE_RISK_MULT,
    DEFAULT_CHANNEL_DEVIATION,
    strategy_params,
)


def test_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("EURUSD_AMPLITUDE", raising=False)
    monkeypatch.delenv("EURUSD_CHANNEL_DEVIATION", raising=False)
    monkeypatch.delenv("EURUSD_BASE_RISK_MULT", raising=False)

    params = strategy_params("EURUSD")

    assert params == {
        "amplitude": DEFAULT_AMPLITUDE,
        "channel_deviation": DEFAULT_CHANNEL_DEVIATION,
        "base_risk_mult": DEFAULT_BASE_RISK_MULT,
    }


def test_per_instrument_env_override(monkeypatch):
    monkeypatch.setenv("EURUSD_AMPLITUDE", "25")
    monkeypatch.setenv("EURUSD_CHANNEL_DEVIATION", "2")
    monkeypatch.setenv("EURUSD_BASE_RISK_MULT", "4")
    monkeypatch.delenv("XAUUSD_AMPLITUDE", raising=False)

    eurusd = strategy_params("EURUSD")
    xauusd = strategy_params("XAUUSD")

    assert eurusd == {"amplitude": 25, "channel_deviation": 2.0, "base_risk_mult": 4.0}
    assert xauusd["amplitude"] == DEFAULT_AMPLITUDE, "overriding EURUSD must not affect XAUUSD"
