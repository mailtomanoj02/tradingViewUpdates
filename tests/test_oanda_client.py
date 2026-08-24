import pytest

from src.market_data_client import MarketDataError
from src.oanda_client import OandaNotConfigured, fetch_candles


def _candle(minute, complete):
    return {
        "time": f"2026-08-24T00:{minute:02d}:00.000000000Z",
        "complete": complete,
        "mid": {"o": "1.0800", "h": "1.0810", "l": "1.0790", "c": "1.0805"},
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
