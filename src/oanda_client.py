"""OANDA REST API v20 market data client (optional primary data source).

Only used if OANDA_API_KEY is set in the environment -- see
src/data_provider.py for the fallback-to-yfinance orchestration. Only needs
an API key (a personal access token); account ID is not required for
candle/pricing history, only for account-specific endpoints this project
never calls (CLAUDE.md section 2: read-only market data only).
"""

import os

import pandas as pd
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

from .market_data_client import MarketDataError

OANDA_TICKERS = {"EURUSD": "EUR_USD", "XAUUSD": "XAU_USD"}
OANDA_GRANULARITY = {"EURUSD": "M5", "XAUUSD": "M3"}


class OandaNotConfigured(RuntimeError):
    """Raised when OANDA_API_KEY is not set -- signals the caller to fall back."""


def _client():
    api_key = os.environ.get("OANDA_API_KEY")
    if not api_key:
        raise OandaNotConfigured("OANDA_API_KEY is not set")
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
    return API(access_token=api_key, environment=environment)


def fetch_candles(symbol, lookback_bars=1000):
    """Fetch the most recent `lookback_bars` confirmed/closed candles for `symbol`.

    Same contract as market_data_client.fetch_candles: DataFrame indexed by
    bar-open time (ascending), open/high/low/close columns, closed candles
    only (OANDA marks in-progress candles with complete=False -- those are
    dropped, matching CLAUDE.md section 2's confirmed-candles-only rule).
    """
    if symbol not in OANDA_TICKERS:
        raise ValueError(f"Unknown symbol: {symbol}")

    client = _client()
    params = {"granularity": OANDA_GRANULARITY[symbol], "count": lookback_bars, "price": "M"}
    request = InstrumentsCandles(instrument=OANDA_TICKERS[symbol], params=params)
    client.request(request)
    raw_candles = request.response.get("candles", [])

    rows = [
        {
            "time": pd.Timestamp(c["time"]),
            "open": float(c["mid"]["o"]),
            "high": float(c["mid"]["h"]),
            "low": float(c["mid"]["l"]),
            "close": float(c["mid"]["c"]),
        }
        for c in raw_candles
        if c["complete"]
    ]
    if not rows:
        raise MarketDataError(f"{symbol}: OANDA returned no closed candles")

    df = pd.DataFrame(rows).set_index("time").sort_index()
    if len(df) < lookback_bars:
        raise MarketDataError(
            f"{symbol}: only {len(df)} closed OANDA candles available, need {lookback_bars}"
        )
    return df.iloc[-lookback_bars:]
