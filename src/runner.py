"""Shared core for the per-instrument entrypoints (CLAUDE.md sections 2, 7, 8).

Each instrument still gets its own entrypoint file (eurusd_runner.py,
xauusd_runner.py) so the two GitHub Actions workflows stay fully
independent at the process level -- a delay/issue on one instrument's
track never affects the other's. This module only avoids duplicating the
identical session-check -> fetch -> signal -> sizing -> email logic
between them.

Any real error (data fetch failure, malformed data, email send failure,
etc.) is left to propagate uncaught -- a failed run must show up as a
failed GitHub Actions run, never be silently swallowed (CLAUDE.md
section 2's fail-loud rule). Only two outcomes here are treated as
"nothing to do" rather than errors: outside the trading session, and no
active signal on the latest closed candle.
"""

from .data_provider import fetch_candles
from .email_alert import send_signal_alert
from .halftrend import latest_signal, strategy_params
from .position_sizing import position_size_matrix
from .session import is_within_session

DEFAULT_LOOKBACK_BARS = 1000


def run(symbol, timeframe, lookback_bars=DEFAULT_LOOKBACK_BARS):
    if not is_within_session():
        print(f"{symbol}: outside trading session (06:00-21:30 IST) -- skipping.")
        return

    df, source = fetch_candles(symbol, lookback_bars=lookback_bars)
    params = strategy_params(symbol)
    signal = latest_signal(symbol, timeframe, df, **params)

    if not signal["direction"]:
        print(f"{symbol}: no signal on latest closed candle ({signal['signal_time']}). Source: {source}.")
        return

    matrix = position_size_matrix(symbol, signal["entry"], signal["stop_loss"])
    subject, _ = send_signal_alert(signal, matrix, source)
    print(f"{symbol}: sent '{subject}' (source: {source})")
