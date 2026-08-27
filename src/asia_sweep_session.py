"""Alert-active window for the Asia Sweep Reversals system (CLAUDE.md section 14).

Distinct from src/session.py -- that module is the IST 06:00-21:30 gate for
the (now dormant) HalfTrend system and is left untouched. The Asia Sweep
sweeps/entries happen during the New York morning (the London/NY overlap
that takes the Asia range), so this gate is evaluated in New York time by
default -- NY 04:00-12:00, Mon-Fri -- and stays put across daylight saving
because it's tied to the NY clock, not to IST.

Same non-negotiable as session.py: nothing (fetch, evaluation, alert)
happens outside the window. Same empty-string-safe env parsing (`... or
default`) -- a GitHub Actions workflow referencing a never-added secret
sets the var to "" rather than leaving it absent.
"""

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

DEFAULT_WINDOW_START = "04:00"
DEFAULT_WINDOW_END = "12:00"
DEFAULT_WINDOW_TZ = "America/New_York"
DEFAULT_TRADING_DAYS = "0,1,2,3,4"  # Monday=0 ... Sunday=6


def _parse_time(env_var, default):
    raw = os.environ.get(env_var) or default
    hour, minute = (int(x) for x in raw.split(":"))
    return time(hour, minute)


def window_start():
    return _parse_time("ASIA_SWEEP_WINDOW_START", DEFAULT_WINDOW_START)


def window_end():
    return _parse_time("ASIA_SWEEP_WINDOW_END", DEFAULT_WINDOW_END)


def window_tz():
    return ZoneInfo(os.environ.get("ASIA_SWEEP_WINDOW_TZ") or DEFAULT_WINDOW_TZ)


def trading_days():
    """Set of weekday numbers (Monday=0 ... Sunday=6) that count as trading days."""
    raw = os.environ.get("ASIA_SWEEP_TRADING_DAYS") or DEFAULT_TRADING_DAYS
    return {int(x) for x in raw.split(",")}


def is_trading_day(d):
    return d.weekday() in trading_days()


def is_within_asia_sweep_window(now=None):
    """True if `now` (default: current time) falls within the configured
    window AND is a configured trading day, evaluated in the window's own
    timezone.
    """
    tz = window_tz()
    now = (now or datetime.now(tz)).astimezone(tz)
    if not is_trading_day(now.date()):
        return False
    return window_start() <= now.time() <= window_end()
