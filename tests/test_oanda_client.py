import pandas as pd
import pytest

from src.market_data_client import MarketDataError
from src.oanda_client import OANDA_GRANULARITY, OandaNotConfigured, fetch_candles


def _candle(minute, complete):
    return {
        "time": f"2026-08-24T00:{minute:02d}:00.000000000Z",
        "complete": complete,
        "mid": {"o": "1.0800", "h": "1.0810", "l": "1.0790", "c": "1.0805"},
    }


def _minute_candle(hour, minute, o, h, l, c):
    return {
        "time": f"2020-01-01T{hour:02d}:{minute:02d}:00.000000000Z",
        "complete": True,
        "mid": {"o": str(o), "h": str(h), "l": str(l), "c": str(c)},
    }


class FakeResponse:
    def __init__(self, candles):
        self.response = {"candles": candles}


class FakeAPI:
    def __init__(self, candles, captured_params):
        self._candles = candles
        self._captured_params = captured_params

    def request(self, request):
        self._captured_params.append(dict(request.params))
        request.response = FakeResponse(self._candles).response


class PagingFakeAPI:
    """Simulates OANDA's real `count` + `to` pagination: each request
    returns up to `count` candles at/before `to` (most recent first,
    ending at `to` when given), so a client-side loop is required to
    walk further back in history -- exactly what _fetch_raw does.
    """

    def __init__(self, master_candles_ascending, captured_params):
        self._master = master_candles_ascending
        self._captured_params = captured_params

    def request(self, request):
        params = dict(request.params)
        self._captured_params.append(params)
        count = params["count"]
        to = params.get("to")

        eligible = self._master
        if to is not None:
            to_ts = pd.Timestamp(to)
            eligible = [c for c in self._master if pd.Timestamp(c["time"]) <= to_ts]

        request.response = FakeResponse(eligible[-count:]).response


def test_fetch_candles_does_not_false_fallback_when_last_candle_is_incomplete(monkeypatch):
    # Real OANDA behavior: `count=N` includes the current in-progress candle
    # (complete=False), so a naive `count=lookback_bars` request returns only
    # lookback_bars-1 *closed* candles -- this reproduces that shape and
    # confirms fetch_candles still returns the full requested lookback
    # instead of raising a false "not enough data" error (project history:
    # this was happening on every single production run).
    lookback_bars = 10
    candles = [_candle(m, complete=True) for m in range(16)] + [_candle(16, complete=False)]

    captured_params = []
    monkeypatch.setenv("OANDA_API_KEY", "dummy")
    monkeypatch.setattr(
        "src.oanda_client.API",
        lambda access_token, environment: FakeAPI(candles, captured_params),
    )

    df = fetch_candles("EURUSD", lookback_bars=lookback_bars)

    assert len(df) == lookback_bars
    # requests more than lookback_bars to leave headroom for the dropped
    # in-progress candle
    assert captured_params[0]["count"] > lookback_bars


def test_fetch_candles_raises_if_genuinely_not_enough_closed_candles(monkeypatch):
    lookback_bars = 1000
    candles = [_candle(m % 60, complete=True) for m in range(5)]

    monkeypatch.setenv("OANDA_API_KEY", "dummy")
    monkeypatch.setattr(
        "src.oanda_client.API",
        lambda access_token, environment: FakeAPI(candles, []),
    )

    with pytest.raises(MarketDataError, match="only 5 closed OANDA candles available"):
        fetch_candles("EURUSD", lookback_bars=lookback_bars)


def test_fetch_candles_without_api_key_raises_not_configured(monkeypatch):
    monkeypatch.delenv("OANDA_API_KEY", raising=False)
    with pytest.raises(OandaNotConfigured):
        fetch_candles("EURUSD", lookback_bars=10)


def test_xauusd_requests_native_m1_not_the_invalid_m3():
    # OANDA has no M3 granularity (valid minute values skip M2 -> M4) --
    # requesting it used to make every XAUUSD OANDA fetch fail and
    # silently fall back to yfinance on every single run (project
    # history). XAUUSD must request OANDA's native M1 instead.
    assert OANDA_GRANULARITY["XAUUSD"] == "M1"


def test_xauusd_resamples_oanda_m1_candles_into_3min_bars(monkeypatch):
    lookback_bars = 10
    requested_minutes = lookback_bars * 3 + 3 * 3 + 5  # matches fetch_candles's own formula

    # Supply more raw minutes than requested_minutes (45, a clean multiple
    # of 3) so every 3-minute bucket is complete -- avoids the ambiguity
    # of a partial trailing bucket, which isn't what this test is about.
    candles = [
        _minute_candle(0, m, o=100 + m, h=100 + m + 0.5, l=100 + m - 0.5, c=100 + m + 0.2)
        for m in range(45)
    ]

    captured_params = []
    monkeypatch.setenv("OANDA_API_KEY", "dummy")
    monkeypatch.setattr(
        "src.oanda_client.API",
        lambda access_token, environment: FakeAPI(candles, captured_params),
    )

    df = fetch_candles("XAUUSD", lookback_bars=lookback_bars)

    assert captured_params[0]["granularity"] == "M1"
    assert captured_params[0]["count"] == requested_minutes
    assert len(df) == lookback_bars

    # Trimming to the last lookback_bars always preserves the tail, so
    # the last bucket is deterministic regardless of how many buckets
    # got dropped from the front: raw minutes 42, 43, 44.
    last = df.iloc[-1]
    assert last["open"] == 142.0  # minute 42's open
    assert last["high"] == 144.5  # max high across minutes 42-44
    assert last["low"] == 141.5  # min low across minutes 42-44
    assert last["close"] == 144.2  # minute 44's close


def test_xauusd_raises_if_genuinely_not_enough_closed_1min_candles(monkeypatch):
    lookback_bars = 1000
    candles = [_minute_candle(0, m, o=100, h=101, l=99, c=100.5) for m in range(5)]

    monkeypatch.setenv("OANDA_API_KEY", "dummy")
    monkeypatch.setattr(
        "src.oanda_client.API",
        lambda access_token, environment: FakeAPI(candles, []),
    )

    with pytest.raises(MarketDataError, match="only .* closed OANDA candles available"):
        fetch_candles("XAUUSD", lookback_bars=lookback_bars)


def test_paginates_when_needed_count_exceeds_oandas_per_request_cap(monkeypatch):
    # JOURNAL_LOOKBACK_BARS=3000 for XAUUSD needs ~9000 raw M1 candles to
    # resample from, well past OANDA's real 5000-per-request cap
    # (CLAUDE.md section 12) -- reproduces that with a small cap (5) and
    # a small dataset so it's fast, but exercises the exact same
    # multi-request pagination path.
    monkeypatch.setattr("src.oanda_client.MAX_OANDA_COUNT", 5)

    # A clean multiple of 3 avoids an ambiguous partial trailing bucket.
    master = [
        _minute_candle(0, m, o=100 + m, h=100 + m + 0.5, l=100 + m - 0.5, c=100 + m + 0.2)
        for m in range(36)
    ]

    captured_params = []
    monkeypatch.setenv("OANDA_API_KEY", "dummy")
    monkeypatch.setattr(
        "src.oanda_client.API",
        lambda access_token, environment: PagingFakeAPI(master, captured_params),
    )

    lookback_bars = 5
    df = fetch_candles("XAUUSD", lookback_bars=lookback_bars)

    # 29 raw minutes needed (5*3 + 3*3 + 5) at a cap of 5 per request
    # forces multiple round trips, not one.
    assert len(captured_params) > 1
    assert len(df) == lookback_bars
    assert df.index.is_monotonic_increasing
    assert not df.index.duplicated().any()

    # Last bucket is deterministic (tail always preserved): raw minutes 33, 34, 35.
    last = df.iloc[-1]
    assert last["open"] == 133.0
    assert last["high"] == 135.5
    assert last["low"] == 132.5
    assert last["close"] == 135.2
