from datetime import datetime
from zoneinfo import ZoneInfo

from src.session import is_within_session

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def _ist(hour, minute, day=22):
    return datetime(2026, 8, day, hour, minute, tzinfo=IST)  # Aug 22, 2026 is a Saturday


def test_within_session_start_boundary_inclusive():
    assert is_within_session(_ist(6, 0, day=24)) is True  # Monday


def test_within_session_end_boundary_inclusive():
    assert is_within_session(_ist(21, 30, day=24)) is True


def test_within_session_midday():
    assert is_within_session(_ist(13, 0, day=24)) is True


def test_outside_session_before_open():
    assert is_within_session(_ist(5, 59, day=24)) is False


def test_outside_session_after_close():
    assert is_within_session(_ist(21, 31, day=24)) is False


def test_outside_session_late_night():
    assert is_within_session(_ist(23, 0, day=24)) is False


def test_converts_non_ist_timezone_correctly():
    # 06:00 IST == 00:30 UTC, on a Monday
    within_open = datetime(2026, 8, 24, 0, 30, tzinfo=UTC)
    outside_open = datetime(2026, 8, 24, 0, 29, tzinfo=UTC)
    assert is_within_session(within_open) is True
    assert is_within_session(outside_open) is False


def test_default_excludes_weekends():
    assert is_within_session(_ist(13, 0, day=22)) is False  # Saturday
    assert is_within_session(_ist(13, 0, day=23)) is False  # Sunday


def test_env_configurable_session_window(monkeypatch):
    monkeypatch.setenv("SESSION_START", "08:00")
    monkeypatch.setenv("SESSION_END", "22:00")
    assert is_within_session(_ist(7, 30, day=24)) is False  # before new start
    assert is_within_session(_ist(8, 0, day=24)) is True
    assert is_within_session(_ist(22, 0, day=24)) is True
    assert is_within_session(_ist(21, 45, day=24)) is True  # within new (wider) window


def test_env_configurable_trading_days_can_include_weekends(monkeypatch):
    monkeypatch.setenv("TRADING_DAYS", "0,1,2,3,4,5,6")
    assert is_within_session(_ist(13, 0, day=22)) is True  # Saturday now allowed
    assert is_within_session(_ist(13, 0, day=23)) is True  # Sunday now allowed


def test_env_configurable_trading_days_can_be_narrower(monkeypatch):
    monkeypatch.setenv("TRADING_DAYS", "0,1,2")  # Mon-Wed only
    assert is_within_session(_ist(13, 0, day=24)) is True  # Monday
    assert is_within_session(_ist(13, 0, day=27)) is False  # Thursday


def test_empty_string_env_vars_fall_back_to_defaults(monkeypatch):
    # Simulates a GitHub Actions workflow referencing a secret that was
    # never added -- the env var is set to "" (present, empty), not absent.
    # The two-arg os.environ.get(key, default) form misses this and crashes.
    monkeypatch.setenv("SESSION_START", "")
    monkeypatch.setenv("SESSION_END", "")
    monkeypatch.setenv("TRADING_DAYS", "")

    assert is_within_session(_ist(13, 0, day=24)) is True  # Monday midday, defaults apply
    assert is_within_session(_ist(5, 59, day=24)) is False  # still respects the default start
