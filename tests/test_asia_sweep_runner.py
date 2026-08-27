import pandas as pd
import pytest

from src import asia_sweep_runner


@pytest.fixture(autouse=True)
def _telegram_and_state(monkeypatch):
    sent = []
    monkeypatch.setattr(asia_sweep_runner, "send_asia_sweep_message", lambda html: sent.append(html) or True)

    alerted = set()
    monkeypatch.setattr(
        asia_sweep_runner, "already_alerted",
        lambda key, ts, path=None: (key, ts.isoformat()) in alerted,
    )
    monkeypatch.setattr(
        asia_sweep_runner, "record_alert",
        lambda key, ts, path=None: alerted.add((key, ts.isoformat())),
    )
    monkeypatch.setattr(asia_sweep_runner, "is_within_asia_sweep_window", lambda now=None: True)
    monkeypatch.setattr(
        asia_sweep_runner, "fetch_candles",
        lambda symbol, lookback_bars=None, timeframe=None: (pd.DataFrame(), "OANDA"),
    )
    monkeypatch.setattr(asia_sweep_runner, "asia_sweep_params", lambda symbol: {})
    monkeypatch.setattr(
        asia_sweep_runner, "position_size_matrix",
        lambda symbol, entry, stop: {"accounts": [], "risk_percentages": [], "account_sizes": []},
    )
    return sent


TS = pd.Timestamp("2026-08-25 13:15", tz="UTC")


def _event(symbol, sweep=None, entry=None):
    return {"symbol": symbol, "timeframe": "1m", "bar_time": TS, "sweep": sweep, "entry": entry}


def test_skips_entirely_outside_the_window(monkeypatch, _telegram_and_state):
    monkeypatch.setattr(asia_sweep_runner, "is_within_asia_sweep_window", lambda now=None: False)
    called = []
    monkeypatch.setattr(asia_sweep_runner, "fetch_candles", lambda *a, **k: called.append(1))
    asia_sweep_runner.run_asia_sweep_check()
    assert called == []


def test_no_event_sends_nothing(monkeypatch, _telegram_and_state):
    monkeypatch.setattr(asia_sweep_runner, "latest_events", lambda s, tf, df, **p: _event(s))
    asia_sweep_runner.run_asia_sweep_check()
    assert _telegram_and_state == []


def test_sweep_event_sends_once_then_dedups(monkeypatch, _telegram_and_state):
    sweep = {"side": "HIGH", "swept_level": 1.1, "session_high": 1.1, "session_low": 1.0,
             "session_mid": 1.05, "session_start": TS, "session_date": "2026-08-25"}

    def only_eurusd(symbol, tf, df, **p):
        return _event(symbol, sweep=sweep if symbol == "EURUSD" else None)

    monkeypatch.setattr(asia_sweep_runner, "latest_events", only_eurusd)
    monkeypatch.setattr(asia_sweep_runner, "format_sweep_message", lambda e, src: "SWEEP MSG")

    asia_sweep_runner.run_asia_sweep_check()
    assert _telegram_and_state == ["SWEEP MSG"]

    asia_sweep_runner.run_asia_sweep_check()  # second run -- dedup
    assert _telegram_and_state == ["SWEEP MSG"]


def test_entry_event_builds_sizing_and_sends(monkeypatch, _telegram_and_state):
    entry = {"direction": "LONG", "entry": 1.10, "stop_loss": 1.09}

    monkeypatch.setattr(
        asia_sweep_runner, "latest_events",
        lambda s, tf, df, **p: _event(s, entry=entry if s == "GBPUSD" else None),
    )
    monkeypatch.setattr(asia_sweep_runner, "format_entry_message", lambda e, m, src: "ENTRY MSG")

    asia_sweep_runner.run_asia_sweep_check()
    assert _telegram_and_state == ["ENTRY MSG"]


def test_one_pair_failing_does_not_block_others_and_run_raises(monkeypatch, _telegram_and_state):
    sweep = {"side": "LOW", "swept_level": 1.0, "session_high": 1.1, "session_low": 1.0,
             "session_mid": 1.05, "session_start": TS, "session_date": "2026-08-25"}

    def maybe_boom(symbol, tf, df, **p):
        if symbol == "XAUUSD":
            raise RuntimeError("OANDA 500")
        return _event(symbol, sweep=sweep if symbol == "AUDUSD" else None)

    monkeypatch.setattr(asia_sweep_runner, "latest_events", maybe_boom)
    monkeypatch.setattr(asia_sweep_runner, "format_sweep_message", lambda e, src: "AUDUSD SWEEP")

    with pytest.raises(RuntimeError, match="XAUUSD"):
        asia_sweep_runner.run_asia_sweep_check()

    assert _telegram_and_state == ["AUDUSD SWEEP"]  # AUDUSD still processed
