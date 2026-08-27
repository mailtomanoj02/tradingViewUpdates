import pandas as pd

from src import alert_state


def test_already_alerted_false_when_no_state_file(tmp_path):
    path = tmp_path / "last_alert_eurusd.json"
    assert alert_state.already_alerted("EURUSD", pd.Timestamp("2026-08-27T10:00:00Z"), path=str(path)) is False


def test_record_then_already_alerted_true_for_same_signal(tmp_path):
    path = tmp_path / "last_alert_eurusd.json"
    signal_time = pd.Timestamp("2026-08-27T10:00:00Z")

    alert_state.record_alert("EURUSD", signal_time, path=str(path))

    assert alert_state.already_alerted("EURUSD", signal_time, path=str(path)) is True


def test_already_alerted_false_for_a_different_signal_time(tmp_path):
    path = tmp_path / "last_alert_eurusd.json"
    alert_state.record_alert("EURUSD", pd.Timestamp("2026-08-27T10:00:00Z"), path=str(path))

    assert alert_state.already_alerted("EURUSD", pd.Timestamp("2026-08-27T10:05:00Z"), path=str(path)) is False


def test_record_alert_overwrites_previous_marker(tmp_path):
    path = tmp_path / "last_alert_eurusd.json"
    alert_state.record_alert("EURUSD", pd.Timestamp("2026-08-27T10:00:00Z"), path=str(path))
    alert_state.record_alert("EURUSD", pd.Timestamp("2026-08-27T10:05:00Z"), path=str(path))

    assert alert_state.already_alerted("EURUSD", pd.Timestamp("2026-08-27T10:00:00Z"), path=str(path)) is False
    assert alert_state.already_alerted("EURUSD", pd.Timestamp("2026-08-27T10:05:00Z"), path=str(path)) is True
