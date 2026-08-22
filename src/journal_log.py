"""Persisted daily journal log (CLAUDE.md's journal section).

A small git-committed JSON file is the "database" here -- deliberately,
per the trade-off discussed with the user: individual trade detection
stays fully recomputed from raw candles each run (no live open-trade
tracking between runs), but the small daily summaries themselves need to
persist so weekly/monthly/yearly reports don't require re-fetching months
or years of intraday history that our data sources don't even retain
(yfinance: ~7 days at 1m, ~60 days at 5m). If this ever needs to scale
beyond a flat file, swap this module for a real DB -- nothing above this
layer needs to change.
"""

import json
import os

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "journal", "daily_log.json")


def _serialize_trade(trade):
    t = dict(trade)
    t["signal_time"] = trade["signal_time"].isoformat()
    t["close_time"] = trade["close_time"].isoformat() if trade["close_time"] else None
    return t


def _deserialize_trade(t):
    import pandas as pd

    trade = dict(t)
    trade["signal_time"] = pd.Timestamp(t["signal_time"])
    trade["close_time"] = pd.Timestamp(t["close_time"]) if t["close_time"] else None
    return trade


def load_log(path=None):
    path = path or LOG_PATH
    if not os.path.exists(path):
        return []
    with open(path) as f:
        raw = json.load(f)
    for entry in raw:
        entry["trades"] = [_deserialize_trade(t) for t in entry["trades"]]
    return raw


def append_daily_entry(date_str, symbol, timeframe, trades, path=None):
    """Append (or replace, if today's entry for this symbol already exists
    -- re-running the same day's job must be idempotent, not duplicate
    entries) one day's closed-trade list to the log.
    """
    path = path or LOG_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log = load_log(path)
    log = [e for e in log if not (e["date"] == date_str and e["symbol"] == symbol)]
    log.append(
        {
            "date": date_str,
            "symbol": symbol,
            "timeframe": timeframe,
            "trades": [_serialize_trade(t) for t in trades],
        }
    )
    log.sort(key=lambda e: (e["date"], e["symbol"]))

    with open(path, "w") as f:
        json.dump(log, f, indent=2, default=str)

    return log


def trades_in_range(symbol, start_date_str, end_date_str, path=None):
    """All trades from log entries for `symbol` with date in [start, end] (inclusive, 'YYYY-MM-DD' strings)."""
    log = load_log(path or LOG_PATH)
    trades = []
    for entry in log:
        if entry["symbol"] == symbol and start_date_str <= entry["date"] <= end_date_str:
            trades.extend(entry["trades"])
    return trades
