"""Persisted per-symbol last-alerted-signal marker -- a dedup guard for the
live alert workflows (eurusd_check.yml / xauusd_check.yml).

Each run is stateless by design (CLAUDE.md section 2): it recomputes the
full HalfTrend signal from scratch and never tracks open positions between
runs. That design assumed the external pinger (cron-job.org) calls each
workflow at roughly its own candle cadence -- every 5 minutes for EURUSD,
every 3 for XAUUSD -- so the "latest closed candle" is normally checked
once per candle.

In practice the pinger has fired far more often than that (duplicate or
overlapping cron-job.org jobs -- project history: observed ~once every 60
seconds for both symbols instead of 5min/3min). When that happens, the
same still-current candle gets checked on every extra run before the next
candle closes, and `latest_signal()` correctly reports the same flip every
time -- so without any memory of "did I already send this one,"
`runner.py` would re-email the identical signal on every extra trigger.

This is a guard against duplicate *sends*, not a fix for the trigger
cadence itself -- excess triggering still burns Actions minutes and
data-provider calls, and should be fixed at the pinger. But an alert must
never re-notify on a signal it already sent, no matter how many times (or
how oddly spaced) the workflow gets triggered, so a small commit-backed
marker records the last alerted signal per symbol -- the same
stateless-per-run-but-persist-the-small-summary trade-off already made for
the journal log (journal_log.py).
"""

import json
import os

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")


def _state_path(symbol, path=None):
    return path or os.path.join(STATE_DIR, f"last_alert_{symbol.lower()}.json")


def already_alerted(symbol, signal_time, path=None):
    """True if `signal_time` (the candle timestamp a signal fired on) was
    already recorded as alerted for `symbol`.
    """
    state_path = _state_path(symbol, path)
    if not os.path.exists(state_path):
        return False
    with open(state_path) as f:
        state = json.load(f)
    return state.get("signal_time") == signal_time.isoformat()


def record_alert(symbol, signal_time, path=None):
    """Record `signal_time` as the last alerted signal for `symbol`."""
    state_path = _state_path(symbol, path)
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w") as f:
        json.dump({"signal_time": signal_time.isoformat()}, f, indent=2)
