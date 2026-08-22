"""IST trading-session window check (CLAUDE.md section 2).

Non-negotiable: no data fetch, no signal evaluation, no email outside this
window. Runners must check this FIRST, before anything else -- not "don't
send outside the window", but "don't even look" outside it.

The window and trading days are configurable via env vars (defaults match
the original spec: 06:00-21:30 IST, Monday-Friday) -- so widening hours or
adding Sat/Sun requires only an env var change, never a code change. Note
this only affects the Python-level gate; a workflow's own cron schedule
(the coarse over-covering window, not the real gate -- CLAUDE.md section
8) may need a matching manual edit if a new window falls outside what that
cron already covers.
"""

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

DEFAULT_SESSION_START = "06:00"
DEFAULT_SESSION_END = "21:30"
DEFAULT_TRADING_DAYS = "0,1,2,3,4"  # Monday=0 ... Sunday=6 (date.weekday() convention)


def _parse_time(env_var, default):
    # `or default`, not the two-arg os.environ.get(key, default): a GitHub
    # Actions workflow referencing a secret that was never added sets the
    # env var to an EMPTY STRING, not absent -- the two-arg form would
    # miss that and crash trying to parse "" as a time (see CLAUDE.md
    # section 12/project history).
    raw = os.environ.get(env_var) or default
    hour, minute = (int(x) for x in raw.split(":"))
    return time(hour, minute)


def session_start():
    return _parse_time("SESSION_START", DEFAULT_SESSION_START)


def session_end():
    return _parse_time("SESSION_END", DEFAULT_SESSION_END)


def trading_days():
    """Set of weekday numbers (Monday=0 ... Sunday=6) that count as trading days."""
    raw = os.environ.get("TRADING_DAYS") or DEFAULT_TRADING_DAYS
    return {int(x) for x in raw.split(",")}


def is_trading_day(d):
    return d.weekday() in trading_days()


def is_within_session(now=None):
    """True if `now` (default: current time) falls within the configured
    trading window AND is a configured trading day.
    """
    now = (now or datetime.now(IST)).astimezone(IST)
    if not is_trading_day(now.date()):
        return False
    return session_start() <= now.time() <= session_end()
