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

from .market_data_client import INSTRUMENTS, MarketDataError, drop_unclosed_bar, resample_candles

OANDA_TICKERS = {"EURUSD": "EUR_USD", "XAUUSD": "XAU_USD"}

# OANDA's v20 API has no native 3-minute granularity -- its minute-based
# values jump straight from M2 to M4 (verified against OANDA's own docs,
# project history). Requesting the invalid "M3" here used to make every
# single XAUUSD OANDA fetch fail and silently fall back to yfinance
# (data_provider.py's fallback logging caught it, but nobody was
# watching for it) -- meaning XAUUSD alerts were always priced off
# yfinance's GC=F futures contract (the ~1.3% premium over spot
# documented in CLAUDE.md section 7) and picked up yfinance's extra
# resampling-driven latency, even with OANDA_API_KEY configured the
# whole time. Fixed by fetching OANDA's native M1 and resampling to
# 3-minute bars ourselves, the exact same approach market_data_client.py
# already uses for the yfinance fallback.
OANDA_GRANULARITY = {"EURUSD": "M5", "XAUUSD": "M1"}


class OandaNotConfigured(RuntimeError):
    """Raised when OANDA_API_KEY is not set -- signals the caller to fall back."""


def _client():
    api_key = os.environ.get("OANDA_API_KEY")
    if not api_key:
        raise OandaNotConfigured("OANDA_API_KEY is not set")
    environment = os.environ.get("OANDA_ENVIRONMENT") or "practice"
    return API(access_token=api_key, environment=environment)


MAX_OANDA_COUNT = 5000  # OANDA's own per-request cap on the `count` param


def _fetch_one_batch(client, symbol, count, to=None):
    params = {"granularity": OANDA_GRANULARITY[symbol], "count": count, "price": "M"}
    if to is not None:
        params["to"] = to
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
    return rows, len(raw_candles)


def _fetch_raw(client, symbol, count):
    """Fetch the most recent `count` closed candles at
    OANDA_GRANULARITY[symbol], closed candles only (OANDA marks
    in-progress candles with complete=False -- those are dropped,
    matching CLAUDE.md section 2's confirmed-candles-only rule).

    Pages backward in batches of up to MAX_OANDA_COUNT when `count`
    exceeds OANDA's own per-request cap -- needed for XAUUSD's
    M1->3min resampling path at the journal's larger lookback
    (JOURNAL_LOOKBACK_BARS=3000 needs ~9000 raw M1 candles, CLAUDE.md
    section 12), which a single request can't cover.
    """
    collected = []
    to_param = None
    while len(collected) < count:
        chunk = min(count - len(collected), MAX_OANDA_COUNT)
        batch, raw_len = _fetch_one_batch(client, symbol, chunk, to=to_param)

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


def fetch_candles(symbol, lookback_bars=1000):
    """Fetch the most recent `lookback_bars` confirmed/closed candles for `symbol`.

    Same contract as market_data_client.fetch_candles: DataFrame indexed by
    bar-open time (ascending), open/high/low/close columns, closed candles
    only.
    """
    if symbol not in OANDA_TICKERS:
        raise ValueError(f"Unknown symbol: {symbol}")

    client = _client()
    candle_minutes = INSTRUMENTS[symbol]["candle_minutes"]
    needs_resample = OANDA_GRANULARITY[symbol] == "M1" and candle_minutes != 1

    if needs_resample:
        # Fetch enough native M1 bars to cover lookback_bars worth of
        # candle_minutes-sized bars after resampling, with a buffer for
        # the always-dropped in-progress bar and one partial trailing
        # bucket (mirrors market_data_client.fetch_candles's yfinance
        # resampling path exactly).
        requested = lookback_bars * candle_minutes + candle_minutes * 3 + 5
        raw = _fetch_raw(client, symbol, requested)
        candles = resample_candles(raw, candle_minutes)
        candles = drop_unclosed_bar(candles, candle_minutes)
    else:
        # Request a small buffer beyond lookback_bars: OANDA's `count`
        # includes the current in-progress candle (complete=False), which
        # is always dropped above. Requesting exactly lookback_bars
        # therefore returns lookback_bars-1 closed candles every single
        # time -- a deterministic off-by-one that was silently forcing
        # every OANDA fetch to fail validation and fall back to yfinance
        # in production (caught via real run logs, not assumed).
        requested = lookback_bars + 5
        candles = _fetch_raw(client, symbol, requested)

    if len(candles) < lookback_bars:
        raise MarketDataError(
            f"{symbol}: only {len(candles)} closed OANDA candles available, need {lookback_bars}"
        )
    return candles.iloc[-lookback_bars:]
