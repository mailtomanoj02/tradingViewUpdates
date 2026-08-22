"""Market data provider orchestration: OANDA (if configured) with automatic
fallback to yfinance.

OANDA is only attempted if OANDA_API_KEY is set in the environment. If it's
unset, or a configured OANDA fetch fails for any reason, this falls back to
yfinance. The fallback is always logged to stderr -- a silent provider swap
would hide a real problem (CLAUDE.md section 2: fail loud, not silent).
Every fetch reports which source actually produced the data, so the email
can disclose it (CLAUDE.md section 6).
"""

import os
import sys

from . import market_data_client
from . import oanda_client

OANDA_SOURCE_LABEL = "OANDA"
YFINANCE_SOURCE_LABEL = "Yahoo Finance (yfinance, unofficial)"


def fetch_candles(symbol, lookback_bars=1000):
    """Returns (candles_df, source_label)."""
    if os.environ.get("OANDA_API_KEY"):
        try:
            df = oanda_client.fetch_candles(symbol, lookback_bars)
            return df, OANDA_SOURCE_LABEL
        except Exception as exc:
            print(
                f"[data_provider] OANDA fetch failed for {symbol}, "
                f"falling back to yfinance: {exc}",
                file=sys.stderr,
            )

    df = market_data_client.fetch_candles(symbol, lookback_bars)
    return df, YFINANCE_SOURCE_LABEL
