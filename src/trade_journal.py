"""Trade outcome simulation + journal aggregation.

Deliberately out of the original build spec (CLAUDE.md sections 2/7 call
position/PnL tracking explicitly out of scope) -- added later at the
user's explicit request. See CLAUDE.md's journal section for the full
design record and the trade-offs this required.

simulate_trade_outcome() replicates reference/halftrend_source.pine's own
win/loss/scratch bookkeeping EXACTLY (elif-ordered TP1/TP2/TP3 checks, the
TP1-then-stopped "scratch" cancellation, same-bar ambiguity and all) --
this is deliberate fidelity to the user's existing indicator, not
independently-designed logic. It is a stylized WIN-COUNT scheme, not a
PnL model: touching TP1/TP2 does not reduce risk or lock in profit on a
single non-partial position, so the actual money outcome (r_multiple) is
always determined by whichever of SL/TP3 the position actually exits at
-- -1R for a stop, +3R for a full run to target 3, or None if the trade
hasn't resolved within the given forward window (still open).
"""


def simulate_trade_outcome(direction, entry, stop_loss, target1, target2, target3, future_bars):
    """Walk forward through `future_bars` (an iterable of (timestamp, high, low)
    tuples, chronological, starting the bar AFTER the signal bar) and
    determine this trade's outcome.

    Returns:
        {
            "wins_delta": int,       # Pine-script-style win count contribution
            "losses_delta": int,     # Pine-script-style loss count contribution
            "final_exit": "SL" | "TP3" | "open",
            "close_time": Timestamp | None,   # when SL or TP3 was hit
            "r_multiple": -1.0 | 3.0 | None,  # actual PnL outcome; None if still open
        }
    """
    wins = 0
    losses = 0
    tp1_hit = False
    active_tp1, active_tp2, active_tp3 = target1, target2, target3
    active_sl = stop_loss
    trade_open = True
    final_exit = "open"
    close_time = None

    for ts, high, low in future_bars:
        if not trade_open:
            break

        if direction == "LONG":
            if active_tp1 is not None and high >= active_tp1:
                wins += 1
                active_tp1 = None
                tp1_hit = True
            elif active_tp2 is not None and high >= active_tp2:
                wins += 1
                active_tp2 = None
            elif active_tp3 is not None and high >= active_tp3:
                wins += 1
                active_tp3 = None
                trade_open = False
                active_sl = None
                final_exit = "TP3"
                close_time = ts

            if trade_open and active_sl is not None and low <= active_sl:
                losses += 1
                trade_open = False
                active_sl = None
                final_exit = "SL"
                close_time = ts
                if tp1_hit:
                    wins -= 1
                    losses -= 1
        else:  # SHORT -- mirrored
            if active_tp1 is not None and low <= active_tp1:
                wins += 1
                active_tp1 = None
                tp1_hit = True
            elif active_tp2 is not None and low <= active_tp2:
                wins += 1
                active_tp2 = None
            elif active_tp3 is not None and low <= active_tp3:
                wins += 1
                active_tp3 = None
                trade_open = False
                active_sl = None
                final_exit = "TP3"
                close_time = ts

            if trade_open and active_sl is not None and high >= active_sl:
                losses += 1
                trade_open = False
                active_sl = None
                final_exit = "SL"
                close_time = ts
                if tp1_hit:
                    wins -= 1
                    losses -= 1

    r_multiple = {"SL": -1.0, "TP3": 3.0}.get(final_exit)

    return {
        "wins_delta": wins,
        "losses_delta": losses,
        "final_exit": final_exit,
        "close_time": close_time,
        "r_multiple": r_multiple,
    }


def outcome_label(final_exit, wins_delta, losses_delta):
    """Human-readable label matching the four outcomes the user described:
    direct stop, TP1-then-stop, TP1+TP2-then-stop, or a full TP3 run.
    (TP2 is never reached without TP1 having been touched first -- the
    elif-ordered checks require it, which also matches reality: price
    can't reach TP2 without passing through TP1's level.)
    """
    if final_exit == "TP3":
        return "TP3 (full target)"
    if final_exit == "SL":
        if wins_delta == 0 and losses_delta == 1:
            return "Direct Stop Loss"
        if wins_delta == 0 and losses_delta == 0:
            return "TP1 then Stop (scratch)"
        if wins_delta >= 1 and losses_delta == 0:
            return "TP1+TP2 then Stop"
    return "Open / Unresolved"


def aggregate_trades(trades):
    """Summary stats for a list of trade records (already filtered to the
    desired period/date). Only trades with a resolved r_multiple count --
    still-open trades are reported separately by the caller.
    """
    closed = [t for t in trades if t["r_multiple"] is not None]
    wins = sum(t["wins_delta"] for t in closed)
    losses = sum(t["losses_delta"] for t in closed)
    r_total = sum(t["r_multiple"] for t in closed)
    outcome_counts = {}
    for t in closed:
        outcome_counts[t["outcome"]] = outcome_counts.get(t["outcome"], 0) + 1
    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else None
    return {
        "total_closed": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "r_total": r_total,
        "outcome_counts": outcome_counts,
    }


def period_return_pct(r_total, risk_pct):
    """Simple (non-compounding) % return for one period at a given risk-per-trade %.

    risk_pct is already a percentage number (1.0 means "1%"), and r_total is
    a dimensionless R-multiple sum -- so the result is risk_pct*r_total
    directly (e.g. +3R at 1% risk/trade = +3%), NOT divided by 100 again.
    That /100 conversion belongs in position_sizing.py's dollar-risk math
    (a real percentage-of-a-dollar-amount calculation), not here.
    """
    return r_total * risk_pct


def compound_returns(pct_list):
    """Compound a list of period % returns (e.g. weeks -> a month, months -> a year)."""
    factor = 1.0
    for pct in pct_list:
        factor *= 1 + pct / 100
    return (factor - 1) * 100


def period_stats_and_returns(symbol, sub_ranges, risks):
    """Combine several date sub-ranges (e.g. weeks within a month, months
    within a year) from the persisted log (journal_log.py) into one report.

    sub_ranges: list of (label, start_date_str, end_date_str), each
    'YYYY-MM-DD' inclusive.

    Returns (overall_stats, compounded_returns_by_risk, sub_period_returns):
      - overall_stats: aggregate_trades() across ALL trades in every
        sub-range combined (counts/win-rate/outcome-breakdown don't care
        about period boundaries)
      - compounded_returns_by_risk: {risk_pct: %} -- each sub-range's
        SIMPLE return is compounded across sub-ranges (CLAUDE.md's journal
        design: within a period trades are summed, across periods they
        compound)
      - sub_period_returns: [(label, %)] at the first configured risk
        tier, for the breakdown table
    """
    from .journal_log import trades_in_range

    all_trades = []
    sub_r_totals = []
    for label, start, end in sub_ranges:
        trades = trades_in_range(symbol, start, end)
        all_trades.extend(trades)
        sub_r_totals.append((label, aggregate_trades(trades)["r_total"]))

    overall_stats = aggregate_trades(all_trades)

    compounded_by_risk = {
        risk: compound_returns([period_return_pct(r_total, risk) for _, r_total in sub_r_totals])
        for risk in risks
    }

    representative_risk = risks[0]
    sub_period_returns = [(label, period_return_pct(r_total, representative_risk)) for label, r_total in sub_r_totals]

    return overall_stats, compounded_by_risk, sub_period_returns


def week_ranges_in_month(year, month):
    """(label, start_date_str, end_date_str) for each Mon-Fri week overlapping
    this month, clipped to the month's own start/end.
    """
    import calendar
    from datetime import date, timedelta

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    ranges = []
    cursor = first_day - timedelta(days=first_day.weekday())  # Monday on/before the 1st
    week_num = 1
    while cursor <= last_day:
        week_start = max(cursor, first_day)
        week_end = min(cursor + timedelta(days=4), last_day)  # Mon + 4 = Fri
        if week_start <= week_end:
            ranges.append((f"Week {week_num}", week_start.isoformat(), week_end.isoformat()))
            week_num += 1
        cursor += timedelta(days=7)
    return ranges


def monthly_report(symbol, year, month, risks):
    """Monthly return per risk tier, compounded from that month's weekly returns."""
    sub_ranges = week_ranges_in_month(year, month)
    return period_stats_and_returns(symbol, sub_ranges, risks)


def yearly_report(symbol, year, risks):
    """Yearly return per risk tier, compounded from each month's (already
    week-compounded) monthly return -- a genuine two-level compound, not a
    flat sum of the whole year's trades.
    """
    import calendar

    from .journal_log import trades_in_range

    monthly_pct_by_risk = {risk: [] for risk in risks}
    sub_period_returns = []
    all_trades = []

    for month in range(1, 13):
        sub_ranges = week_ranges_in_month(year, month)
        overall, compounded, _ = period_stats_and_returns(symbol, sub_ranges, risks)
        all_trades.extend(trades_in_range(symbol, sub_ranges[0][1], sub_ranges[-1][2]))
        for risk in risks:
            monthly_pct_by_risk[risk].append(compounded[risk])
        sub_period_returns.append((calendar.month_abbr[month], compounded[risks[0]]))

    overall_stats = aggregate_trades(all_trades)
    yearly_compounded = {risk: compound_returns(monthly_pct_by_risk[risk]) for risk in risks}
    return overall_stats, yearly_compounded, sub_period_returns


def compute_trade_outcomes(symbol, timeframe, result):
    """Detect every signal in an already-computed `compute_halftrend` result
    and simulate each one's outcome using the bars that follow it within
    the same DataFrame.

    Returns a list of trade records (oldest first), each:
        {symbol, timeframe, direction, entry, stop_loss, target1/2/3,
         signal_time, close_time, final_exit, outcome, wins_delta,
         losses_delta, r_multiple}
    """
    signal_rows = result[result["buy_signal"] | result["sell_signal"]]
    trades = []

    for signal_time, row in signal_rows.iterrows():
        direction = "LONG" if row["buy_signal"] else "SHORT"
        future = result.loc[result.index > signal_time]
        future_bars = list(zip(future.index, future["high"], future["low"]))

        outcome = simulate_trade_outcome(
            direction, row["entry"], row["stop_loss"], row["target1"], row["target2"], row["target3"], future_bars
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
                "outcome": outcome_label(outcome["final_exit"], outcome["wins_delta"], outcome["losses_delta"]),
                "wins_delta": outcome["wins_delta"],
                "losses_delta": outcome["losses_delta"],
                "r_multiple": outcome["r_multiple"],
            }
        )

    return trades
