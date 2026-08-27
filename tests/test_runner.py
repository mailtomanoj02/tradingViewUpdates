import pandas as pd

from src import runner


def test_skips_entirely_outside_session(monkeypatch, capsys):
    monkeypatch.setattr(runner, "is_within_session", lambda: False)
    called = {"fetch": False}
    monkeypatch.setattr(runner, "fetch_candles", lambda *a, **k: called.__setitem__("fetch", True))

    runner.run("EURUSD", "5m")

    assert called["fetch"] is False, "must not fetch data outside the session window"
    assert "outside trading session" in capsys.readouterr().out


def test_fetches_but_sends_nothing_when_no_signal(monkeypatch, capsys):
    monkeypatch.setattr(runner, "is_within_session", lambda: True)
    monkeypatch.setattr(runner, "fetch_candles", lambda *a, **k: (pd.DataFrame(), "OANDA"))
    monkeypatch.setattr(runner, "strategy_params", lambda symbol: {})
    monkeypatch.setattr(
        runner,
        "latest_signal",
        lambda *a, **k: {"direction": None, "signal_time": pd.Timestamp("2026-08-22", tz="UTC")},
    )
    sent = {"called": False}
    monkeypatch.setattr(runner, "send_signal_alert", lambda *a, **k: sent.__setitem__("called", True))

    runner.run("EURUSD", "5m")

    assert sent["called"] is False
    assert "no signal on latest closed candle" in capsys.readouterr().out


def test_sends_alert_when_signal_fires(monkeypatch, capsys):
    monkeypatch.setattr(runner, "is_within_session", lambda: True)
    monkeypatch.setattr(runner, "fetch_candles", lambda *a, **k: (pd.DataFrame(), "OANDA"))
    monkeypatch.setattr(runner, "strategy_params", lambda symbol: {"amplitude": 25})
    signal = {
        "direction": "LONG",
        "entry": 1.0842,
        "stop_loss": 1.0821,
        "signal_time": pd.Timestamp("2026-08-22", tz="UTC"),
    }
    monkeypatch.setattr(runner, "latest_signal", lambda *a, **k: signal)
    monkeypatch.setattr(runner, "position_size_matrix", lambda *a, **k: {"matrix": True})
    monkeypatch.setattr(runner, "already_alerted", lambda *a, **k: False)
    recorded = {}
    monkeypatch.setattr(runner, "record_alert", lambda symbol, signal_time: recorded.update(symbol=symbol, signal_time=signal_time))

    sent_args = {}

    def fake_send(sig, matrix, source):
        sent_args["sig"] = sig
        sent_args["matrix"] = matrix
        sent_args["source"] = source
        return "[EURUSD] LONG Signal - Entry Formed", "body"

    monkeypatch.setattr(runner, "send_signal_alert", fake_send)

    runner.run("EURUSD", "5m")

    assert sent_args["sig"] is signal
    assert sent_args["matrix"] == {"matrix": True}
    assert sent_args["source"] == "OANDA"
    assert "sent '[EURUSD] LONG Signal - Entry Formed'" in capsys.readouterr().out
    assert recorded == {"symbol": "EURUSD", "signal_time": signal["signal_time"]}


def test_skips_duplicate_send_for_already_alerted_signal(monkeypatch, capsys):
    monkeypatch.setattr(runner, "is_within_session", lambda: True)
    monkeypatch.setattr(runner, "fetch_candles", lambda *a, **k: (pd.DataFrame(), "OANDA"))
    monkeypatch.setattr(runner, "strategy_params", lambda symbol: {"amplitude": 25})
    signal = {
        "direction": "LONG",
        "entry": 1.0842,
        "stop_loss": 1.0821,
        "signal_time": pd.Timestamp("2026-08-22", tz="UTC"),
    }
    monkeypatch.setattr(runner, "latest_signal", lambda *a, **k: signal)
    monkeypatch.setattr(runner, "already_alerted", lambda *a, **k: True)
    sent = {"called": False}
    monkeypatch.setattr(runner, "send_signal_alert", lambda *a, **k: sent.__setitem__("called", True))

    runner.run("EURUSD", "5m")

    assert sent["called"] is False, "must not re-send a signal that was already alerted"
    assert "already alerted" in capsys.readouterr().out


def test_errors_propagate_uncaught(monkeypatch):
    monkeypatch.setattr(runner, "is_within_session", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("data source down")

    monkeypatch.setattr(runner, "fetch_candles", boom)

    try:
        runner.run("EURUSD", "5m")
        raised = False
    except RuntimeError:
        raised = True

    assert raised, "a real error must propagate, never be silently swallowed"
