from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src import journal_runner

IST = ZoneInfo("Asia/Kolkata")


def test_is_trading_day():
    assert journal_runner.is_trading_day(date(2026, 8, 21)) is True  # Friday
    assert journal_runner.is_trading_day(date(2026, 8, 22)) is False  # Saturday
    assert journal_runner.is_trading_day(date(2026, 8, 23)) is False  # Sunday
    assert journal_runner.is_trading_day(date(2026, 8, 24)) is True  # Monday


def test_is_last_weekday_of_month():
    # Jan 2026's 31st is a Saturday -- the 30th (Friday) is the last weekday.
    assert journal_runner.is_last_weekday_of_month(date(2026, 1, 30)) is True
    assert journal_runner.is_last_weekday_of_month(date(2026, 1, 29)) is False
    # Aug 2026's 31st is itself a Monday (a weekday) -- so the 28th (Friday) is NOT last.
    assert journal_runner.is_last_weekday_of_month(date(2026, 8, 28)) is False
    assert journal_runner.is_last_weekday_of_month(date(2026, 8, 31)) is True


def test_is_last_weekday_of_year():
    assert journal_runner.is_last_weekday_of_year(date(2026, 12, 31)) is True  # Thu
    assert journal_runner.is_last_weekday_of_year(date(2026, 11, 28)) is False  # last weekday of Nov, not Dec


def _fake_signal_df():
    return pd.DataFrame({"high": [1, 2, 3], "low": [1, 2, 3]})


def test_weekend_skips_everything(monkeypatch, capsys):
    called = {"fetch": False}
    monkeypatch.setattr(journal_runner, "fetch_candles", lambda *a, **k: called.__setitem__("fetch", True))

    journal_runner.run_daily_journal(now=datetime(2026, 8, 22, 22, 0, tzinfo=IST))  # Saturday

    assert called["fetch"] is False
    assert "not a configured trading day" in capsys.readouterr().out.lower()


def test_weekday_sends_daily_only_on_non_friday_non_month_end(monkeypatch, capsys):
    # Wednesday, not month-end
    monkeypatch.setattr(journal_runner, "fetch_candles", lambda *a, **k: (_fake_signal_df(), "OANDA"))
    monkeypatch.setattr(journal_runner, "strategy_params", lambda s: {})
    monkeypatch.setattr(journal_runner, "compute_halftrend", lambda df, **k: df)
    monkeypatch.setattr(journal_runner, "compute_trade_outcomes", lambda *a, **k: [])
    monkeypatch.setattr(journal_runner, "aggregate_trades", lambda trades: {
        "total_closed": 0, "wins": 0, "losses": 0, "win_rate": None, "r_total": 0.0, "outcome_counts": {}
    })
    monkeypatch.setattr(journal_runner, "append_daily_entry", lambda *a, **k: None)
    monkeypatch.setattr(journal_runner, "render_daily_email", lambda *a, **k: "<html>daily</html>")

    sent_subjects = []
    monkeypatch.setattr(journal_runner, "send_html_email", lambda subject, html: sent_subjects.append(subject))

    journal_runner.run_daily_journal(now=datetime(2026, 8, 19, 22, 0, tzinfo=IST))  # Wednesday

    # 2 instruments x 1 daily email each, no weekly/monthly/yearly
    assert len(sent_subjects) == 2
    assert all("Daily Trade Journal" in s for s in sent_subjects)


def test_friday_also_sends_weekly(monkeypatch):
    monkeypatch.setattr(journal_runner, "fetch_candles", lambda *a, **k: (_fake_signal_df(), "OANDA"))
    monkeypatch.setattr(journal_runner, "strategy_params", lambda s: {})
    monkeypatch.setattr(journal_runner, "compute_halftrend", lambda df, **k: df)
    monkeypatch.setattr(journal_runner, "compute_trade_outcomes", lambda *a, **k: [])
    monkeypatch.setattr(journal_runner, "aggregate_trades", lambda trades: {
        "total_closed": 0, "wins": 0, "losses": 0, "win_rate": None, "r_total": 0.0, "outcome_counts": {}
    })
    monkeypatch.setattr(journal_runner, "append_daily_entry", lambda *a, **k: None)
    monkeypatch.setattr(journal_runner, "trades_in_range", lambda *a, **k: [])
    monkeypatch.setattr(journal_runner, "render_daily_email", lambda *a, **k: "<html>daily</html>")
    monkeypatch.setattr(journal_runner, "render_period_email", lambda *a, **k: "<html>period</html>")

    sent_subjects = []
    monkeypatch.setattr(journal_runner, "send_html_email", lambda subject, html: sent_subjects.append(subject))

    journal_runner.run_daily_journal(now=datetime(2026, 8, 21, 22, 0, tzinfo=IST))  # Friday, not month-end

    assert len(sent_subjects) == 4  # 2 instruments x (daily + weekly)
    assert sum("Weekly Trade Journal" in s for s in sent_subjects) == 2


def test_month_end_also_sends_monthly(monkeypatch):
    monkeypatch.setattr(journal_runner, "fetch_candles", lambda *a, **k: (_fake_signal_df(), "OANDA"))
    monkeypatch.setattr(journal_runner, "strategy_params", lambda s: {})
    monkeypatch.setattr(journal_runner, "compute_halftrend", lambda df, **k: df)
    monkeypatch.setattr(journal_runner, "compute_trade_outcomes", lambda *a, **k: [])
    monkeypatch.setattr(journal_runner, "aggregate_trades", lambda trades: {
        "total_closed": 0, "wins": 0, "losses": 0, "win_rate": None, "r_total": 0.0, "outcome_counts": {}
    })
    monkeypatch.setattr(journal_runner, "append_daily_entry", lambda *a, **k: None)
    monkeypatch.setattr(
        journal_runner, "monthly_report", lambda *a, **k: ({"total_closed": 0, "wins": 0, "losses": 0, "win_rate": None, "r_total": 0.0, "outcome_counts": {}}, {1.0: 0.0}, [])
    )
    monkeypatch.setattr(journal_runner, "render_daily_email", lambda *a, **k: "<html>daily</html>")
    monkeypatch.setattr(journal_runner, "render_period_email", lambda *a, **k: "<html>period</html>")

    sent_subjects = []
    monkeypatch.setattr(journal_runner, "send_html_email", lambda subject, html: sent_subjects.append(subject))

    journal_runner.run_daily_journal(now=datetime(2026, 8, 31, 22, 0, tzinfo=IST))  # Mon Aug 31, actual month-end

    assert sum("Monthly Trade Journal" in s for s in sent_subjects) == 2


def test_one_symbols_failure_does_not_block_the_other_symbols_journal(monkeypatch, capsys):
    # Project history: a transient OANDA error on XAUUSD crashed the whole
    # script mid-loop, silently skipping XAUUSD's journal for that day even
    # though EURUSD's had already been sent -- this reproduces that and
    # confirms both symbols are now handled independently.
    def flaky_fetch(symbol, lookback_bars):
        if symbol == "XAUUSD":
            raise RuntimeError("Insufficient authorization to perform request.")
        return _fake_signal_df(), "OANDA"

    monkeypatch.setattr(journal_runner, "fetch_candles", flaky_fetch)
    monkeypatch.setattr(journal_runner, "strategy_params", lambda s: {})
    monkeypatch.setattr(journal_runner, "compute_halftrend", lambda df, **k: df)
    monkeypatch.setattr(journal_runner, "compute_trade_outcomes", lambda *a, **k: [])
    monkeypatch.setattr(journal_runner, "aggregate_trades", lambda trades: {
        "total_closed": 0, "wins": 0, "losses": 0, "win_rate": None, "r_total": 0.0, "outcome_counts": {}
    })
    monkeypatch.setattr(journal_runner, "append_daily_entry", lambda *a, **k: None)
    monkeypatch.setattr(journal_runner, "render_daily_email", lambda *a, **k: "<html>daily</html>")

    sent_subjects = []
    monkeypatch.setattr(journal_runner, "send_html_email", lambda subject, html: sent_subjects.append(subject))

    with pytest.raises(RuntimeError, match="XAUUSD"):
        journal_runner.run_daily_journal(now=datetime(2026, 8, 19, 22, 0, tzinfo=IST))  # Wednesday

    # EURUSD's daily email still sent despite XAUUSD failing.
    assert len(sent_subjects) == 1
    assert "[EURUSD]" in sent_subjects[0]
    assert "XAUUSD: journal FAILED" in capsys.readouterr().err
