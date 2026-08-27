"""yfinance-backed market data client.

Wraps yfinance with retry/backoff and shape validation, since it is an
unofficial, scraped API that can throttle or return malformed/empty data
without warning (see CLAUDE.md section 7). Every candle set returned here
excludes the current, still-forming bar -- only confirmed/closed candles
are ever handed to a strategy engine (CLAUDE.md section 2).

Each symbol has a *default* fetch recipe (interval / lookback period /
resampling) tuned to the system that historically owned it -- EURUSD 5m
and XAUUSD 3m for HalfTrend. A caller can override the recipe by passing
`timeframe` (one of TIMEFRAME_FETCH's keys), which the Asia Sweep system
uses to pull every pair at 1m regardless of the symbol's default
(CLAUDE.md section 14). XAUUSD / "3m" has no native 3-minute interval on
Yahoo, so it is built by resampling 1-minute bars.
"""

import time

import pandas as pd
import yfinance as yf

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5

# Per-symbol static info + the DEFAULT fetch recipe (used when no explicit
# `timeframe` is passed to fetch_candles). INSTRUMENTS is the HalfTrend set
# ONLY (EURUSD 5m, XAUUSD 3m) -- several HalfTrend modules iterate it as
# "the instruments this system watches", so it must stay exactly these
# two. GBPUSD/AUDUSD live in ASIA_SWEEP_ONLY and are only ever reached
# with an explicit timeframe. SYMBOL_INFO is the merged lookup used
# internally for ticker / price_decimals.
INSTRUMENTS = {
    "EURUSD": {
        "ticker": "EURUSD=X",
        "fetch_interval": "5m",
        "fetch_period": "60d",  # Yahoo's real cap for 5m bars -- the journal's larger lookback needs this headroom
        "fetch_interval_minutes": 5,
        "candle_minutes": 5,
        "price_decimals": 5,
    },
    "XAUUSD": {
        "ticker": "GC=F",
        "fetch_interval": "1m",
        "fetch_period": "7d",  # Yahoo's real cap for 1m bars
        "fetch_interval_minutes": 1,
        "candle_minutes": 3,
        "price_decimals": 2,
    },
}

ASIA_SWEEP_ONLY = {
    "GBPUSD": {
        "ticker": "GBPUSD=X",
        "fetch_interval": "1m",
        "fetch_period": "7d",
        "fetch_interval_minutes": 1,
        "candle_minutes": 1,
        "price_decimals": 5,
    },
    "AUDUSD": {
        "ticker": "AUDUSD=X",
        "fetch_interval": "1m",
        "fetch_period": "7d",
        "fetch_interval_minutes": 1,
        "candle_minutes": 1,
        "price_decimals": 5,
    },
}

SYMBOL_INFO = {**INSTRUMENTS, **ASIA_SWEEP_ONLY}

# Explicit-timeframe fetch recipes. `fetch_interval`/`fetch_period` are what
# we actually request from Yahoo; `candle_minutes` is the bar size we return
# after any resampling. "3m" is built from 1m bars (no native 3m interval).
TIMEFRAME_FETCH = {
    "1m": {"fetch_interval": "1m", "fetch_period": "7d", "fetch_interval_minutes": 1, "candle_minutes": 1},
    "3m": {"fetch_interval": "1m", "fetch_period": "7d", "fetch_interval_minutes": 1, "candle_minutes": 3},
    "5m": {"fetch_interval": "5m", "fetch_period": "60d", "fetch_interval_minutes": 5, "candle_minutes": 5},
}


class MarketDataError(RuntimeError):
    """Raised when candle data cannot be fetched or is unusable."""


def fetch_recipe(symbol, timeframe=None):
    """The fetch recipe for `symbol`: the symbol's default, or the
    TIMEFRAME_FETCH override when `timeframe` is given.
    """
    if symbol not in SYMBOL_INFO:
        raise ValueError(f"Unknown symbol: {symbol}")
    base = SYMBOL_INFO[symbol]
    if timeframe is None:
        return dict(base)
    if timeframe not in TIMEFRAME_FETCH:
        raise ValueError(f"Unknown timeframe: {timeframe}")
    return {**base, **TIMEFRAME_FETCH[timeframe]}


def _standardize(raw):
    df = raw.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
    return df[["open", "high", "low", "close"]]


def _fetch_with_retry(ticker, period, interval):
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            raw = yf.Ticker(ticker).history(period=period, interval=interval)
            if raw is None or raw.empty:
                raise MarketDataError(f"{ticker} {interval}: empty response from yfinance")
            return _standardize(raw)
        except Exception as exc:
            last_error = exc
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise MarketDataError(f"{ticker} {interval}: failed after {RETRY_ATTEMPTS} attempts") from last_error


def drop_unclosed_bar(df, candle_minutes):
    """Drop the last row if it's still an in-progress (not yet closed) bar."""
    if df.empty:
        return df
    bar_open = df.index[-1]
    now = pd.Timestamp.now(tz=df.index.tz)
    if (now - bar_open).total_seconds() < candle_minutes * 60:
        return df.iloc[:-1]
    return df


def resample_candles(df, candle_minutes):
    """Aggregate finer-grained OHLC bars up to `candle_minutes` bars."""
    return (
        df.resample(f"{candle_minutes}min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )


def fetch_candles(symbol, lookback_bars=1000, timeframe=None):
    """Fetch the most recent `lookback_bars` confirmed/closed candles for `symbol`.

    `timeframe` (e.g. "1m") overrides the symbol's default fetch recipe --
    see TIMEFRAME_FETCH. When omitted, the symbol's INSTRUMENTS default is
    used (EURUSD 5m, XAUUSD 3m, GBPUSD/AUDUSD 1m).

    Returns a DataFrame indexed by bar-open time (ascending, oldest first)
    with open/high/low/close columns, ready for a strategy engine.
    Raises MarketDataError if fewer than `lookback_bars` closed candles are
    available -- this is a loud failure by design (CLAUDE.md section 2):
    a short/degraded fetch must never be silently treated as "no signal".
    """
    cfg = fetch_recipe(symbol, timeframe)

    raw = _fetch_with_retry(cfg["ticker"], cfg["fetch_period"], cfg["fetch_interval"])
    raw = drop_unclosed_bar(raw, cfg["fetch_interval_minutes"])

    if cfg["candle_minutes"] != cfg["fetch_interval_minutes"]:
        candles = resample_candles(raw, cfg["candle_minutes"])
        candles = drop_unclosed_bar(candles, cfg["candle_minutes"])
    else:
        candles = raw

    if len(candles) < lookback_bars:
        raise MarketDataError(
            f"{symbol}: only {len(candles)} closed {cfg['candle_minutes']}m candles available, "
            f"need {lookback_bars} for a warmed-up signal"
        )
    return candles.iloc[-lookback_bars:]
