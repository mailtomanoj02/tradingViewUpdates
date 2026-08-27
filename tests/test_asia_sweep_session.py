from datetime import datetime
from zoneinfo import ZoneInfo

from src.asia_sweep_session import is_within_asia_sweep_window, trading_days, window_end, window_start

NY = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")


def test_defaults_are_ny_0400_1200_mon_fri(monkeypatch):
    for var in (
        "ASIA_SWEEP_WINDOW_START", "ASIA_SWEEP_WINDOW_END",
        "ASIA_SWEEP_WINDOW_TZ", "ASIA_SWEEP_TRADING_DAYS",
    ):
        monkeypatch.delenv(var, raising=False)
    assert window_start().hour == 4
    assert window_end().hour == 12
    assert trading_days() == {0, 1, 2, 3, 4}


def test_inside_and_outside_window_ny_time(monkeypatch):
    for var in ("ASIA_SWEEP_WINDOW_START", "ASIA_SWEEP_WINDOW_END", "ASIA_SWEEP_WINDOW_TZ"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("ASIA_SWEEP_TRADING_DAYS", raising=False)

    # Tuesday 2026-08-25
    assert is_within_asia_sweep_window(datetime(2026, 8, 25, 8, 30, tzinfo=NY))
    assert not is_within_asia_sweep_window(datetime(2026, 8, 25, 3, 59, tzinfo=NY))
    assert not is_within_asia_sweep_window(datetime(2026, 8, 25, 12, 1, tzinfo=NY))


def test_window_holds_across_dst_when_expressed_in_ist(monkeypatch):
    for var in ("ASIA_SWEEP_WINDOW_START", "ASIA_SWEEP_WINDOW_END", "ASIA_SWEEP_WINDOW_TZ", "ASIA_SWEEP_TRADING_DAYS"):
        monkeypatch.delenv(var, raising=False)
    # NY 09:00 in August (EDT, UTC-4) == 18:30 IST -- inside
    assert is_within_asia_sweep_window(datetime(2026, 8, 25, 18, 30, tzinfo=IST))
    # NY 09:00 in January (EST, UTC-5) == 19:30 IST -- still inside, because
    # the gate is anchored to the NY clock, not IST
    assert is_within_asia_sweep_window(datetime(2026, 1, 6, 19, 30, tzinfo=IST))


def test_weekend_is_not_a_trading_day(monkeypatch):
    for var in ("ASIA_SWEEP_WINDOW_START", "ASIA_SWEEP_WINDOW_END", "ASIA_SWEEP_WINDOW_TZ", "ASIA_SWEEP_TRADING_DAYS"):
        monkeypatch.delenv(var, raising=False)
    assert not is_within_asia_sweep_window(datetime(2026, 8, 29, 8, 30, tzinfo=NY))  # Saturday


def test_empty_string_env_vars_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("ASIA_SWEEP_WINDOW_START", "")
    monkeypatch.setenv("ASIA_SWEEP_WINDOW_END", "")
    monkeypatch.setenv("ASIA_SWEEP_TRADING_DAYS", "")
    assert window_start().hour == 4
    assert trading_days() == {0, 1, 2, 3, 4}


def test_custom_window(monkeypatch):
    monkeypatch.setenv("ASIA_SWEEP_WINDOW_START", "03:00")
    monkeypatch.setenv("ASIA_SWEEP_WINDOW_END", "14:00")
    monkeypatch.setenv("ASIA_SWEEP_WINDOW_TZ", "UTC")
    monkeypatch.delenv("ASIA_SWEEP_TRADING_DAYS", raising=False)
    assert is_within_asia_sweep_window(datetime(2026, 8, 25, 13, 0, tzinfo=ZoneInfo("UTC")))
    assert not is_within_asia_sweep_window(datetime(2026, 8, 25, 14, 30, tzinfo=ZoneInfo("UTC")))
