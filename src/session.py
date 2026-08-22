"""IST trading-session window check (CLAUDE.md section 2).

Non-negotiable: no data fetch, no signal evaluation, no email outside this
window. Runners must check this FIRST, before anything else -- not "don't
send outside the window", but "don't even look" outside it.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SESSION_START = time(6, 0)
SESSION_END = time(21, 30)


def is_within_session(now=None):
    """True if `now` (default: current time) falls within 06:00-21:30 IST."""
    now = now or datetime.now(IST)
    return SESSION_START <= now.astimezone(IST).time() <= SESSION_END
