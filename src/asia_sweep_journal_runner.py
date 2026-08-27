"""Asia Sweep Reversals journal job -- daily, plus weekly/monthly/yearly
rollups on the right calendar boundaries (CLAUDE.md section 14).

One scheduled entrypoint, four cadences -- same structure as
journal_runner.run_daily_journal, but Telegram-only (one combined digest
across all 4 pairs per period) and reading the Asia Sweep's own persisted
log. The "trading day" here is the New York calendar date, since the
alert window and the Asia sweeps themselves are anchored to the NY clock.

Triggered once a day by cron-job.org (GitHub's own `schedule:` throttles
even at a once-daily cadence -- CLAUDE.md section 7).

Per-pair try/except isolation for the daily leg; still fail-loud (the run
raises at the end listing any pair that failed).
"""

import sys
from datetime import datetime, timedelta

from .asia_sweep import asia_sweep_params, compute_asia_sweep
from .asia_sweep_journal import ASIA_SWEEP_LOG_PATH, compute_asia_sweep_outcomes
from .asia_sweep_journal_telegram import render_daily_digest, render_period_digest
from .asia_sweep_runner import ASIA_SWEEP_SYMBOLS, ASIA_SWEEP_TIMEFRAME
from .asia_sweep_session import is_trading_day, trading_days, window_tz
from .asia_sweep_telegram import send_asia_sweep_message
from .data_provider import fetch_candles
from .journal_log import append_daily_entry, trades_in_range
from .position_sizing import risk_percentages
from .trade_journal import aggregate_trades, monthly_report, period_return_pct, yearly_report

DEFAULT_JOURNAL_LOOKBACK_BARS = 5000


def _journal_lookback_bars():
    import os

    return int(os.environ.get("ASIA_SWEEP_JOURNAL_LOOKBACK_BARS") or DEFAULT_JOURNAL_LOOKBACK_BARS)


def _is_week_end(d):
    return d.weekday() == max(trading_days())


def _week_start(d):
    return d - timedelta(days=d.weekday() - min(trading_days()))


def _is_last_trading_day_of_month(d):
    nxt = d + timedelta(days=1)
    while nxt.month == d.month:
        if is_trading_day(nxt):
            return False
        nxt += timedelta(days=1)
    return True


def _is_last_trading_day_of_year(d):
    return d.month == 12 and _is_last_trading_day_of_month(d)


def _engine_result(symbol, lookback):
    df, source = fetch_candles(symbol, lookback_bars=lookback, timeframe=ASIA_SWEEP_TIMEFRAME)
    result = compute_asia_sweep(df, **asia_sweep_params(symbol))
    return result, source


def run_asia_sweep_journal(now=None):
    tz = window_tz()
    now = now or datetime.now(tz)
    today = now.astimezone(tz).date()

    if not is_trading_day(today):
        print(f"asia_sweep journal: {today} (NY) is not a configured trading day -- skipping.")
        return

    risks = risk_percentages()
    lookback = _journal_lookback_bars()
    date_str = today.isoformat()

    per_symbol_daily = []
    failed = []
    for symbol in ASIA_SWEEP_SYMBOLS:
        try:
            result, source = _engine_result(symbol, lookback)
            trades = compute_asia_sweep_outcomes(symbol, ASIA_SWEEP_TIMEFRAME, result)
            daily_trades = [
                t for t in trades
                if t["close_time"] is not None and t["close_time"].tz_convert(tz).date() == today
            ]
            open_count = len([t for t in trades if t["r_multiple"] is None])
            stats = aggregate_trades(daily_trades)

            append_daily_entry(date_str, symbol, ASIA_SWEEP_TIMEFRAME, daily_trades, path=ASIA_SWEEP_LOG_PATH)
            per_symbol_daily.append((symbol, ASIA_SWEEP_TIMEFRAME, stats, open_count))
            print(
                f"{symbol}: journal logged (source: {source}, "
                f"{stats['total_closed']} closed today, {open_count} open)"
            )
        except Exception as exc:  # noqa: BLE001
            failed.append(symbol)
            print(f"{symbol}: asia_sweep journal FAILED -- {exc}", file=sys.stderr)

    if per_symbol_daily:
        for msg in render_daily_digest(today.strftime("%d %b %Y (%A)"), per_symbol_daily):
            send_asia_sweep_message(msg)
        print(f"asia_sweep journal: daily digest sent ({len(per_symbol_daily)} pairs).")

    if _is_week_end(today):
        _send_period("Weekly", today, risks, _week_start(today).isoformat(), date_str)
    if _is_last_trading_day_of_month(today):
        _send_period("Monthly", today, risks)
    if _is_last_trading_day_of_year(today):
        _send_period("Yearly", today, risks)

    if failed:
        raise RuntimeError(f"Asia sweep journal failed for: {', '.join(failed)} (see log above)")


def _send_period(period_kind, today, risks, week_start_str=None, week_end_str=None):
    per_symbol = []
    for symbol in ASIA_SWEEP_SYMBOLS:
        if period_kind == "Weekly":
            wt = trades_in_range(symbol, week_start_str, week_end_str, path=ASIA_SWEEP_LOG_PATH)
            stats = aggregate_trades(wt)
            pct_by_risk = {r: period_return_pct(stats["r_total"], r) for r in risks}
        elif period_kind == "Monthly":
            stats, pct_by_risk, _sub = monthly_report(
                symbol, today.year, today.month, risks, path=ASIA_SWEEP_LOG_PATH
            )
        else:  # Yearly
            stats, pct_by_risk, _sub = yearly_report(symbol, today.year, risks, path=ASIA_SWEEP_LOG_PATH)
        per_symbol.append((symbol, ASIA_SWEEP_TIMEFRAME, stats, pct_by_risk))

    if period_kind == "Weekly":
        label = f"{week_start_str} to {week_end_str}"
    elif period_kind == "Monthly":
        label = today.strftime("%B %Y")
    else:
        label = str(today.year)

    for msg in render_period_digest(period_kind, label, per_symbol):
        send_asia_sweep_message(msg)
    print(f"asia_sweep journal: {period_kind.lower()} digest sent.")
