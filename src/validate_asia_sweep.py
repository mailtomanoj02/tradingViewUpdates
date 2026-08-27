"""Mandatory validation script for the Asia Sweep Reversals port (CLAUDE.md sections 3/9/14).

Walks recent historical 1m candles for all 4 pairs (XAUUSD, EURUSD,
GBPUSD, AUDUSD) and prints every sweep and every CHoCH entry the engine
detects, so it can be cross-checked bar-for-bar against the live
TradingView "Asia Sweep Reversals" chart before this system is trusted.

A Pine->Python port that looks right and trades wrong is the single
biggest risk here -- do not skip this.

Run with:
    python -m src.validate_asia_sweep
    python -m src.validate_asia_sweep --start "2026-08-25 00:00" --end "2026-08-28 23:59"
    python -m src.validate_asia_sweep --ny-window     # only events during NY 04:00-12:00

Timestamps are shown in IST (the operator's timezone) and NY time (the
strategy's own timezone) side by side.
"""

import argparse
from datetime import datetime, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .asia_sweep import asia_sweep_params, compute_asia_sweep
from .asia_sweep_runner import ASIA_SWEEP_SYMBOLS, ASIA_SWEEP_TIMEFRAME
from .data_provider import fetch_candles
from .market_data_client import SYMBOL_INFO

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")

NY_WINDOW_START = time(4, 0)
NY_WINDOW_END = time(12, 0)


def _parse_ist(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=IST)


def _in_ny_window(ts):
    ny = ts.tz_convert(NY)
    return ny.weekday() < 5 and NY_WINDOW_START <= ny.time() <= NY_WINDOW_END


def _stamp(ts):
    return f"{ts.tz_convert(IST).strftime('%d %b %H:%M IST')} / {ts.tz_convert(NY).strftime('%H:%M NY')}"


def validate_symbol(symbol, lookback_bars, start, end, ny_window_only):
    decimals = SYMBOL_INFO[symbol]["price_decimals"]
    params = asia_sweep_params(symbol)
    df, source = fetch_candles(symbol, lookback_bars=lookback_bars, timeframe=ASIA_SWEEP_TIMEFRAME)
    result = compute_asia_sweep(df, **params)

    events = result[
        result["high_sweep"] | result["low_sweep"] | result["long_entry"] | result["short_entry"]
    ]
    if start is not None:
        events = events[events.index >= start]
    if end is not None:
        events = events[events.index <= end]
    if ny_window_only:
        events = events[[_in_ny_window(ts) for ts in events.index]]

    print(
        f"\n=== {symbol} ({ASIA_SWEEP_TIMEFRAME}, source: {source}, "
        f"session={params['session_str']} tz={params['timezone']} "
        f"internalLen={params['internal_length']} break={params['break_mode']} "
        f"maxBars={params['max_bars_after_sweep']} trendFilter={params['trend_filter']}) "
        f"-- warmed up from {result.index[0].tz_convert(IST)} ==="
    )

    sweeps = entries = 0
    for ts, row in events.iterrows():
        if row["high_sweep"] or row["low_sweep"]:
            sweeps += 1
            side = "HIGH" if row["high_sweep"] else "LOW"
            level = row["session_high"] if side == "HIGH" else row["session_low"]
            print(
                f"  {_stamp(ts)}  SWEEP {side}  level={level:.{decimals}f}  "
                f"(Asia H {row['session_high']:.{decimals}f} / L {row['session_low']:.{decimals}f})"
            )
        if row["long_entry"] or row["short_entry"]:
            entries += 1
            direction = "LONG " if row["long_entry"] else "SHORT"
            print(
                f"  {_stamp(ts)}  ENTRY {direction}  entry={row['entry']:.{decimals}f}  "
                f"sl={row['stop_loss']:.{decimals}f}  t1={row['target1']:.{decimals}f}  "
                f"t2={row['target2']:.{decimals}f}  t3={row['target3']:.{decimals}f}"
            )

    print(f"  --> {sweeps} sweeps, {entries} entries")
    return sweeps, entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_ist, default=None, help='IST, e.g. "2026-08-25 00:00"')
    parser.add_argument("--end", type=_parse_ist, default=None, help='IST, e.g. "2026-08-28 23:59"')
    parser.add_argument("--lookback", type=int, default=5000, help="1m candles to fetch + warm up on")
    parser.add_argument(
        "--ny-window",
        action="store_true",
        help="only show events during NY 04:00-12:00 Mon-Fri (the alert-active window)",
    )
    args = parser.parse_args()

    totals = {}
    for symbol in ASIA_SWEEP_SYMBOLS:
        totals[symbol] = validate_symbol(symbol, args.lookback, args.start, args.end, args.ny_window)

    print("\n=== SUMMARY ===")
    for symbol, (sweeps, entries) in totals.items():
        print(f"  {symbol:7s}  {sweeps:3d} sweeps  {entries:3d} entries")


if __name__ == "__main__":
    main()
