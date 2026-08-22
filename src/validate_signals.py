"""Mandatory validation script (CLAUDE.md section 3).

Walks recent historical candles for both EURUSD and XAUUSD and prints every
signal the HalfTrend engine detects, so it can be manually cross-checked
bar-for-bar against the live TradingView HalfTrend chart before this system
is trusted with real trading decisions. Timestamps are shown in IST, since
that's the timezone this system (and TradingView, for a trader checking it)
actually operates in.

Run with: python -m src.validate_signals
Optionally filter to an exact IST window (e.g. to reproduce someone else's
manual TradingView count over a specific range) with:
    python -m src.validate_signals --start "2026-08-18 00:00" --end "2026-08-22 02:27"
The full lookback is still fetched and warmed up first (CLAUDE.md section 3)
-- --start/--end only filter which signals are *displayed*, so warm-up
before the window start is never truncated.
"""

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .data_provider import fetch_candles
from .halftrend import compute_halftrend, strategy_params
from .market_data_client import INSTRUMENTS

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")


def _parse_ist(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=IST)


def print_signals(symbol, lookback_bars=1000, start=None, end=None):
    cfg = INSTRUMENTS[symbol]
    decimals = cfg["price_decimals"]
    params = strategy_params(symbol)
    df, source = fetch_candles(symbol, lookback_bars=lookback_bars)
    result = compute_halftrend(df, **params)
    result.index = result.index.tz_convert(IST)

    window = result
    if start is not None:
        window = window[window.index >= start]
    if end is not None:
        window = window[window.index <= end]

    signals = window[window["buy_signal"] | window["sell_signal"]]
    range_note = f"{start} to {end}" if (start or end) else "full fetched range"
    print(
        f"\n=== {symbol} ({cfg['candle_minutes']}m, source: {source}, "
        f"amplitude={params['amplitude']} channelDev={params['channel_deviation']} "
        f"baseRisk={params['base_risk_mult']}) -- displaying {range_note} (IST), "
        f"warmed up from {result.index[0]} ==="
    )
    if signals.empty:
        print("No signals detected in this window.")
        return

    for ts, row in signals.iterrows():
        direction = "LONG" if row["buy_signal"] else "SHORT"
        print(
            f"{ts}  {direction}  "
            f"entry={row['entry']:.{decimals}f}  sl={row['stop_loss']:.{decimals}f}  "
            f"t1={row['target1']:.{decimals}f}  t2={row['target2']:.{decimals}f}  "
            f"t3={row['target3']:.{decimals}f}  atr={row['atr2'] * 2:.{decimals}f}"
        )
    print(f"TOTAL: {len(signals)} signals")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_ist, default=None, help='IST, e.g. "2026-08-18 00:00"')
    parser.add_argument("--end", type=_parse_ist, default=None, help='IST, e.g. "2026-08-22 02:27"')
    parser.add_argument("--lookback", type=int, default=1000, help="candles to fetch+warm up on")
    args = parser.parse_args()

    for symbol in INSTRUMENTS:
        print_signals(symbol, lookback_bars=args.lookback, start=args.start, end=args.end)


if __name__ == "__main__":
    main()
