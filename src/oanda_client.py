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

from .market_data_client import SYMBOL_INFO, MarketDataError, drop_unclosed_bar, resample_candles

OANDA_TICKERS = {
    "EURUSD": "EUR_USD",
    "XAUUSD": "XAU_USD",
    "GBPUSD": "GBP_USD",
    "AUDUSD": "AUD_USD",
}

# OANDA's v20 API has no native 3-minute granularity -- its minute-based
# values jump straight from M2 to M4 (verified against OANDA's own docs,
# project history). Requesting the invalid "M3" used to make every single
# XAUUSD OANDA fetch fail and silently fall back to yfinance. Fixed by
# fetching OANDA's native M1 and resampling to 3-minute bars ourselves,
# the exact same approach market_data_client.py uses for the yfinance
# fallback. The Asia Sweep system pulls every pair at 1m (M1, no
# resample) -- CLAUDE.md section 14.
OANDA_GRANULARITY = {"EURUSD": "M5", "XAUUSD": "M1", "GBPUSD": "M1", "AUDUSD": "M1"}

# Explicit-timeframe -> (OANDA granularity, returned bar size in minutes).
TIMEFRAME_GRANULARITY = {
    "1m": ("M1", 1),
    "3m": ("M1", 3),
    "5m": ("M5", 5),
}


class OandaNotConfigured(RuntimeError):
    """Raised when OANDA_API_KEY is not set -- signals the caller to fall back."""


def _granularity_and_candle_minutes(symbol, timeframe):
    """(granularity, candle_minutes) for `symbol`: the symbol default, or
    the TIMEFRAME_GRANULARITY override when `timeframe` is given.
    """
    if timeframe is not None:
        if timeframe not in TIMEFRAME_GRANULARITY:
            raise ValueError(f"Unknown timeframe: {timeframe}")
        return TIMEFRAME_GRANULARITY[timeframe]
    return OANDA_GRANULARITY[symbol], SYMBOL_INFO[symbol]["candle_minutes"]


def _client():
    api_key = os.environ.get("OANDA_API_KEY")
    if not api_key:
        raise OandaNotConfigured("OANDA_API_KEY is not set")
    environment = os.environ.get("OANDA_ENVIRONMENT") or "practice"
    return API(access_token=api_key, environment=environment)


MAX_OANDA_COUNT = 5000  # OANDA's own per-request cap on the `count` param


def _fetch_one_batch(client, ticker, granularity, count, to=None):
    params = {"granularity": granularity, "count": count, "price": "M"}
    if to is not None:
        params["to"] = to
    request = InstrumentsCandles(instrument=ticker, params=params)
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
    return rows, len(raw_candles)


def _fetch_raw(client, symbol, granularity, count):
    """Fetch the most recent `count` closed candles at `granularity`,
    closed candles only (OANDA marks in-progress candles complete=False).

    Pages backward in batches of up to MAX_OANDA_COUNT when `count`
    exceeds OANDA's own per-request cap -- needed for the resampling
    paths at large lookbacks, which a single request can't cover.
    """
    ticker = OANDA_TICKERS[symbol]
    collected = []
    to_param = None
    while len(collected) < count:
        chunk = min(count - len(collected), MAX_OANDA_COUNT)
        batch, raw_len = _fetch_one_batch(client, ticker, granularity, chunk, to=to_param)

        if collected:
            earliest_seen = collected[0]["time"]
            batch = [row for row in batch if row["time"] < earliest_seen]

        if not batch:
            break

        collected = batch + collected
        to_param = batch[0]["time"].isoformat()

        if raw_len < chunk:
            break  # OANDA has no more history before this point

    if not collected:
        raise MarketDataError(f"{symbol}: OANDA returned no closed candles")
    return pd.DataFrame(collected).set_index("time").sort_index()


def fetch_candles(symbol, lookback_bars=1000, timeframe=None):
    """Fetch the most recent `lookback_bars` confirmed/closed candles for `symbol`.

    Same contract as market_data_client.fetch_candles: DataFrame indexed by
    bar-open time (ascending), open/high/low/close columns, closed candles
    only. `timeframe` overrides the symbol's default granularity.
    """
    if symbol not in OANDA_TICKERS:
        raise ValueError(f"Unknown symbol: {symbol}")

    client = _client()
    granularity, candle_minutes = _granularity_and_candle_minutes(symbol, timeframe)
    needs_resample = granularity == "M1" and candle_minutes != 1

    if needs_resample:
        # Fetch enough native M1 bars to cover lookback_bars worth of
        # candle_minutes-sized bars after resampling, with a buffer for
        # the always-dropped in-progress bar and one partial trailing
        # bucket (mirrors market_data_client.fetch_candles's resample path).
        requested = lookback_bars * candle_minutes + candle_minutes * 3 + 5
        raw = _fetch_raw(client, symbol, granularity, requested)
        candles = resample_candles(raw, candle_minutes)
        candles = drop_unclosed_bar(candles, candle_minutes)
    else:
        # Request a small buffer beyond lookback_bars: OANDA's `count`
        # includes the current in-progress candle (complete=False), which
        # is dropped above. Requesting exactly lookback_bars would return
        # lookback_bars-1 closed candles -- a deterministic off-by-one
        # that silently forced every OANDA fetch to fail validation and
        # fall back to yfinance in production (project history).
        requested = lookback_bars + 5
        candles = _fetch_raw(client, symbol, granularity, requested)

    if len(candles) < lookback_bars:
        raise MarketDataError(
            f"{symbol}: only {len(candles)} closed OANDA candles available, need {lookback_bars}"
        )
    return candles.iloc[-lookback_bars:]
