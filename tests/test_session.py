from datetime import datetime
from zoneinfo import ZoneInfo

from src.session import is_within_session

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def _ist(hour, minute):
    return datetime(2026, 8, 22, hour, minute, tzinfo=IST)


def test_within_session_start_boundary_inclusive():
    assert is_within_session(_ist(6, 0)) is True


def test_within_session_end_boundary_inclusive():
    assert is_within_session(_ist(21, 30)) is True


def test_within_session_midday():
    assert is_within_session(_ist(13, 0)) is True


def test_outside_session_before_open():
    assert is_within_session(_ist(5, 59)) is False


def test_outside_session_after_close():
    assert is_within_session(_ist(21, 31)) is False


def test_outside_session_late_night():
    assert is_within_session(_ist(23, 0)) is False


def test_converts_non_ist_timezone_correctly():
    # 06:00 IST == 00:30 UTC
    within_open = datetime(2026, 8, 22, 0, 30, tzinfo=UTC)
    outside_open = datetime(2026, 8, 22, 0, 29, tzinfo=UTC)
    assert is_within_session(within_open) is True
    assert is_within_session(outside_open) is False
