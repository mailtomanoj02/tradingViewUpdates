"""yfinance-backed market data client.

Wraps yfinance with retry/backoff and shape validation, since it is an
unofficial, scraped API that can throttle or return malformed/empty data
without warning (see CLAUDE.md section 7). Every candle set returned here
excludes the current, still-forming bar -- only confirmed/closed candles
are ever handed to the strategy engine (CLAUDE.md section 2).

XAUUSD has no native 3-minute interval on Yahoo Finance, so it is built by
resampling 1-minute bars (see CLAUDE.md section 3, "Yahoo/yfinance lookback
caps").
"""

import time

import pandas as pd
import yfinance as yf

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5

INSTRUMENTS = {
    "EURUSD": {
        "ticker": "EURUSD=X",
        "fetch_interval": "5m",
        "fetch_period": "7d",
        "fetch_interval_minutes": 5,
        "candle_minutes": 5,
        "price_decimals": 5,
    },
    "XAUUSD": {
        "ticker": "GC=F",
        "fetch_interval": "1m",
        "fetch_period": "5d",
        "fetch_interval_minutes": 1,
        "candle_minutes": 3,
        "price_decimals": 2,
    },
}


class MarketDataError(RuntimeError):
    """Raised when candle data cannot be fetched or is unusable."""


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


def fetch_candles(symbol, lookback_bars=1000):
    """Fetch the most recent `lookback_bars` confirmed/closed candles for `symbol`.

    Returns a DataFrame indexed by bar-open time (ascending, oldest first)
    with open/high/low/close columns, ready for the HalfTrend engine.
    Raises MarketDataError if fewer than `lookback_bars` closed candles are
    available -- this is a loud failure by design (CLAUDE.md section 2):
    a short/degraded fetch must never be silently treated as "no signal".
    """
    if symbol not in INSTRUMENTS:
        raise ValueError(f"Unknown symbol: {symbol}")
    cfg = INSTRUMENTS[symbol]

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
            f"need {lookback_bars} for a warmed-up HalfTrend signal"
        )
    return candles.iloc[-lookback_bars:]
