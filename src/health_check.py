"""Market data provider health check.

Quick, independent connectivity/credential check for each configured data
provider (OANDA, yfinance) -- fetches a handful of recent candles per
instrument, not a full HalfTrend-ready lookback, so this stays fast and
never fails just because there isn't a signal-ready history available.

Run with: python -m src.health_check
"""

import os
import sys
import time

from dotenv import load_dotenv

from . import market_data_client, oanda_client
from .market_data_client import INSTRUMENTS

load_dotenv()

CHECK_LOOKBACK_BARS = 5


def _check(label, fetch_fn, symbol):
    start = time.monotonic()
    try:
        df = fetch_fn(symbol, lookback_bars=CHECK_LOOKBACK_BARS)
        elapsed = time.monotonic() - start
        last = df.iloc[-1]
        print(
            f"  [OK]   {label:8s} {symbol:7s} "
            f"latest={df.index[-1]}  close={last['close']:.5f}  ({elapsed:.2f}s)"
        )
        return True
    except Exception as exc:
        elapsed = time.monotonic() - start
        print(f"  [FAIL] {label:8s} {symbol:7s} ({elapsed:.2f}s) -- {exc}")
        return False


def main():
    print("=== Market data provider health check ===\n")

    print("yfinance:")
    yf_results = [_check("yfinance", market_data_client.fetch_candles, s) for s in INSTRUMENTS]
    yf_ok = all(yf_results)

    print("\nOANDA:")
    if not os.environ.get("OANDA_API_KEY"):
        print("  [SKIP] OANDA_API_KEY not set -- not configured, system will use yfinance only.")
        oanda_ok = None
    else:
        oanda_results = [_check("OANDA", oanda_client.fetch_candles, s) for s in INSTRUMENTS]
        oanda_ok = all(oanda_results)

    print("\n=== Summary ===")
    print(f"yfinance : {'OK' if yf_ok else 'FAILING'}")
    print(f"OANDA    : {'not configured' if oanda_ok is None else ('OK' if oanda_ok else 'FAILING')}")

    if not yf_ok and not oanda_ok:
        print("\nBoth providers are failing right now -- the alert system cannot fetch data.")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
