"""Daily trade-journal job core (CLAUDE.md's journal section).

Runs once per trading day (Mon-Fri), scheduled after the 21:30 IST session
close. Always sends the daily journal email and appends that day's closed
trades to the persisted log (journal/daily_log.json, journal_log.py).
On the last trading day of the week/month/year, ALSO sends the
corresponding weekly/monthly/yearly rollup email -- one scheduled job
covers all four cadences rather than four separate schedules.

Each instrument is processed independently, wrapped in its own
try/except -- a fetch/send failure on one symbol must not prevent the
other symbol's daily (or weekly/monthly/yearly) email from being sent,
mirroring the same isolation the live-check workflows get from being
separate GitHub Actions jobs (runner.py). This was a real bug (project
history): a transient OANDA error on XAUUSD crashed the whole script
mid-loop, after EURUSD's email had already sent -- silently skipping
XAUUSD's journal for that day with no separate error surfaced for it.
Still fail-loud per CLAUDE.md section 2: any per-symbol failure is
printed immediately, and the run still ends by raising (non-zero exit,
visible as a failed GitHub Actions run) if anything failed, listing
every symbol that failed.
"""

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .data_provider import fetch_candles
from .email_alert import send_html_email
from .halftrend import compute_halftrend, strategy_params
from .journal_email import render_daily_email, render_period_email
from .journal_log import append_daily_entry, trades_in_range
from .market_data_client import INSTRUMENTS
from .position_sizing import account_sizes, risk_percentages
from .session import is_trading_day
from .trade_journal import aggregate_trades, compute_trade_outcomes, monthly_report, yearly_report

IST = ZoneInfo("Asia/Kolkata")
JOURNAL_LOOKBACK_BARS = 3000


def is_last_weekday_of_month(d):
    """'weekday' here means a *configured trading day* (session.trading_days()),
    not necessarily literal Mon-Fri -- stays correct if trading days are
    ever widened to include Sat/Sun.
    """
    next_day = d + timedelta(days=1)
    while next_day.month == d.month:
        if is_trading_day(next_day):
            return False
        next_day += timedelta(days=1)
    return True


def is_last_weekday_of_year(d):
    return d.month == 12 and is_last_weekday_of_month(d)


def _week_start(d, trading_day_numbers):
    return d - timedelta(days=d.weekday() - min(trading_day_numbers))


def _is_week_end(d, trading_day_numbers):
    return d.weekday() == max(trading_day_numbers)


def run_daily_journal(now=None):
    from .session import trading_days as configured_trading_days

    now = now or datetime.now(IST)
    today = now.astimezone(IST).date()

    if not is_trading_day(today):
        print(f"journal: {today} is not a configured trading day -- skipping.")
        return

    trading_day_numbers = configured_trading_days()

    risks = risk_percentages()
    accounts = account_sizes()
    date_str = today.isoformat()

    failed_symbols = []
    for symbol, cfg in INSTRUMENTS.items():
        try:
            _run_symbol_journal(symbol, cfg, today, date_str, trading_day_numbers, risks, accounts)
        except Exception as exc:
            failed_symbols.append(symbol)
            print(f"{symbol}: journal FAILED -- {exc}", file=sys.stderr)

    if failed_symbols:
        raise RuntimeError(f"Daily journal failed for: {', '.join(failed_symbols)} (see log above for details)")


def _run_symbol_journal(symbol, cfg, today, date_str, trading_day_numbers, risks, accounts):
    timeframe = f"{cfg['candle_minutes']}m"
    params = strategy_params(symbol)
    df, source = fetch_candles(symbol, lookback_bars=JOURNAL_LOOKBACK_BARS)
    result = compute_halftrend(df, **params)
    trades = compute_trade_outcomes(symbol, timeframe, result)

    daily_trades = [
        t for t in trades if t["close_time"] is not None and t["close_time"].tz_convert(IST).date() == today
    ]
    open_count = len([t for t in trades if t["r_multiple"] is None])
    stats = aggregate_trades(daily_trades)

    html = render_daily_email(
        symbol,
        timeframe,
        today.strftime("%d %b %Y (%A)"),
        stats,
        open_count,
        daily_trades,
        cfg["price_decimals"],
        risks,
        accounts,
    )
    send_html_email(f"[{symbol}] Daily Trade Journal - {today.strftime('%d %b %Y')}", html)
    append_daily_entry(date_str, symbol, timeframe, daily_trades)
    print(f"{symbol}: daily journal sent + logged (source: {source}, {stats['total_closed']} closed, {open_count} open)")

    if _is_week_end(today, trading_day_numbers):
        week_start = _week_start(today, trading_day_numbers)
        week_trades = trades_in_range(symbol, week_start.isoformat(), date_str)
        week_stats = aggregate_trades(week_trades)
        html = render_period_email(
            symbol,
            timeframe,
            "Weekly",
            f"{week_start.strftime('%d %b')} - {today.strftime('%d %b %Y')}",
            week_stats,
            risks,
            accounts,
        )
        send_html_email(
            f"[{symbol}] Weekly Trade Journal - {week_start.strftime('%d %b')} to {today.strftime('%d %b %Y')}",
            html,
        )
        print(f"{symbol}: weekly journal sent")

    if is_last_weekday_of_month(today):
        overall, compounded, sub_returns = monthly_report(symbol, today.year, today.month, risks)
        html = render_period_email(
            symbol,
            timeframe,
            "Monthly",
            today.strftime("%B %Y"),
            overall,
            risks,
            accounts,
            sub_periods=sub_returns,
            returns_by_risk=compounded,
        )
        send_html_email(f"[{symbol}] Monthly Trade Journal - {today.strftime('%B %Y')}", html)
        print(f"{symbol}: monthly journal sent")

    if is_last_weekday_of_year(today):
        overall, compounded, sub_returns = yearly_report(symbol, today.year, risks)
        html = render_period_email(
            symbol,
            timeframe,
            "Yearly",
            str(today.year),
            overall,
            risks,
            accounts,
            sub_periods=sub_returns,
            returns_by_risk=compounded,
        )
        send_html_email(f"[{symbol}] Yearly Trade Journal - {today.year}", html)
        print(f"{symbol}: yearly journal sent")
