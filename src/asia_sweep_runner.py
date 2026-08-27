"""Live Asia Sweep Reversals check -- all 4 pairs, one job (CLAUDE.md section 14).

Stateless per run, same as the HalfTrend runner (CLAUDE.md section 2): fetch
the latest 1m candles, recompute the full engine, look at only the last
closed bar for a sweep and/or a CHoCH entry, alert (Telegram only), exit.

Each pair is processed in its own try/except so one pair's fetch/send
failure can't block the others -- exactly the isolation journal_runner.py
gained after a transient error on one symbol silently skipped the other
(project history). Still fail-loud: every per-pair failure is printed and
the run ends by raising if anything failed.

Duplicate-send guard: the external pinger fires this every minute, so the
same still-current 1m bar is re-checked many times before it closes.
alert_state.py persists a per-(pair, event-type) "last alerted bar" marker
so a sweep/entry is never re-sent, no matter how often the workflow runs.
"""

import os
import sys

from .alert_state import already_alerted, record_alert
from .asia_sweep import asia_sweep_params, latest_events
from .asia_sweep_session import is_within_asia_sweep_window
from .asia_sweep_telegram import format_entry_message, format_sweep_message, send_asia_sweep_message
from .data_provider import fetch_candles
from .position_sizing import position_size_matrix

ASIA_SWEEP_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "AUDUSD"]
ASIA_SWEEP_TIMEFRAME = "1m"
DEFAULT_LOOKBACK_BARS = 2500


def _lookback_bars():
    return int(os.environ.get("ASIA_SWEEP_LOOKBACK_BARS") or DEFAULT_LOOKBACK_BARS)


def run_asia_sweep_check(now=None):
    if not is_within_asia_sweep_window(now):
        print("asia_sweep: outside the configured NY window (default 04:00-12:00 Mon-Fri) -- skipping.")
        return

    lookback = _lookback_bars()
    failed = []
    for symbol in ASIA_SWEEP_SYMBOLS:
        try:
            _check_symbol(symbol, lookback)
        except Exception as exc:  # noqa: BLE001 -- isolate per pair, re-raise aggregate below
            failed.append(symbol)
            print(f"{symbol}: asia_sweep check FAILED -- {exc}", file=sys.stderr)

    if failed:
        raise RuntimeError(f"Asia sweep check failed for: {', '.join(failed)} (see log above)")


def _check_symbol(symbol, lookback):
    df, source = fetch_candles(symbol, lookback_bars=lookback, timeframe=ASIA_SWEEP_TIMEFRAME)
    params = asia_sweep_params(symbol)
    event = latest_events(symbol, ASIA_SWEEP_TIMEFRAME, df, **params)
    bar_time = event["bar_time"]

    if event["sweep"]:
        _emit(symbol, f"{symbol}_asia_sweep", bar_time, source,
              lambda: format_sweep_message(event, source),
              f"Asia {event['sweep']['side']} sweep")

    if event["entry"]:
        entry = event["entry"]
        matrix = position_size_matrix(symbol, entry["entry"], entry["stop_loss"])
        _emit(symbol, f"{symbol}_asia_entry", bar_time, source,
              lambda: format_entry_message(event, matrix, source),
              f"{entry['direction']} entry")

    if not event["sweep"] and not event["entry"]:
        print(f"{symbol}: no Asia sweep event on latest closed bar ({bar_time}). Source: {source}.")


def _emit(symbol, state_key, bar_time, source, build_message, label):
    if already_alerted(state_key, bar_time):
        print(f"{symbol}: {label} already alerted for {bar_time} -- skipping duplicate.")
        return
    sent = send_asia_sweep_message(build_message())
    record_alert(state_key, bar_time)
    status = "sent" if sent else "SKIPPED (Asia Sweep bot not configured)"
    print(f"{symbol}: {label} alert {status} ({bar_time}, source: {source}).")
