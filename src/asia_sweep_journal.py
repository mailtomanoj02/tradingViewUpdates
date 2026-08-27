"""Asia Sweep Reversals trade-outcome detection (CLAUDE.md section 14).

The scoring itself is unchanged from the HalfTrend journal -- this reuses
trade_journal.simulate_trade_outcome / outcome_label verbatim (the same
elif-ordered TP1/TP2/TP3 checks, the TP1-then-stopped "scratch"
cancellation, -1R for a stop / +3R for a full TP3 run / unresolved
otherwise). The only difference is where the entries come from:
compute_asia_sweep's `long_entry`/`short_entry` columns instead of
compute_halftrend's `buy_signal`/`sell_signal`.

Trade records are the exact same shape as compute_trade_outcomes returns,
so journal_log.py, aggregate_trades and the compounding helpers all work
on them unchanged.
"""

import os

from .journal_log import LOG_PATH
from .trade_journal import outcome_label, simulate_trade_outcome

# Separate persisted log from HalfTrend's journal/daily_log.json -- the
# HalfTrend file stays frozen once its pingers are disabled.
ASIA_SWEEP_LOG_PATH = os.path.join(os.path.dirname(LOG_PATH), "asia_sweep_daily_log.json")


def compute_asia_sweep_outcomes(symbol, timeframe, result):
    """Detect every entry in an already-computed `compute_asia_sweep`
    result and simulate each one's outcome from the bars that follow it
    within the same DataFrame.

    Returns a list of trade records (oldest first), each identical in
    shape to trade_journal.compute_trade_outcomes' records.
    """
    signal_rows = result[result["long_entry"] | result["short_entry"]]
    trades = []

    for signal_time, row in signal_rows.iterrows():
        direction = "LONG" if row["long_entry"] else "SHORT"
        future = result.loc[result.index > signal_time]
        future_bars = list(zip(future.index, future["high"], future["low"]))

        outcome = simulate_trade_outcome(
            direction,
            row["entry"],
            row["stop_loss"],
            row["target1"],
            row["target2"],
            row["target3"],
            future_bars,
        )

        trades.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "direction": direction,
                "entry": row["entry"],
                "stop_loss": row["stop_loss"],
                "target1": row["target1"],
                "target2": row["target2"],
                "target3": row["target3"],
                "signal_time": signal_time,
                "close_time": outcome["close_time"],
                "final_exit": outcome["final_exit"],
                "outcome": outcome_label(
                    outcome["final_exit"], outcome["wins_delta"], outcome["losses_delta"]
                ),
                "wins_delta": outcome["wins_delta"],
                "losses_delta": outcome["losses_delta"],
                "r_multiple": outcome["r_multiple"],
            }
        )

    return trades
