import os

import pandas as pd
import pytest

from src.journal_log import append_daily_entry, load_log, trades_in_range


def _trade(signal_time, close_time, outcome="TP3 (full target)", r=3.0):
    return {
        "symbol": "EURUSD",
        "timeframe": "5m",
        "direction": "LONG",
        "entry": 1.0842,
        "stop_loss": 1.0821,
        "target1": 1.0863,
        "target2": 1.0884,
        "target3": 1.0905,
        "signal_time": pd.Timestamp(signal_time, tz="UTC"),
        "close_time": pd.Timestamp(close_time, tz="UTC") if close_time else None,
        "final_exit": "TP3",
        "outcome": outcome,
        "wins_delta": 3,
        "losses_delta": 0,
        "r_multiple": r,
    }


def _log_path(tmp_path):
    return str(tmp_path / "daily_log.json")


def test_append_and_load_round_trip(tmp_path):
    path = _log_path(tmp_path)
    trades = [_trade("2026-08-18 06:00", "2026-08-18 08:00")]
    append_daily_entry("2026-08-18", "EURUSD", "5m", trades, path=path)

    log = load_log(path)
    assert len(log) == 1
    assert log[0]["date"] == "2026-08-18"
    assert log[0]["symbol"] == "EURUSD"
    assert log[0]["trades"][0]["r_multiple"] == 3.0
    assert isinstance(log[0]["trades"][0]["signal_time"], pd.Timestamp)


def test_appending_same_day_symbol_twice_is_idempotent_not_duplicated(tmp_path):
    path = _log_path(tmp_path)
    append_daily_entry("2026-08-18", "EURUSD", "5m", [_trade("2026-08-18 06:00", "2026-08-18 08:00")], path=path)
    append_daily_entry("2026-08-18", "EURUSD", "5m", [_trade("2026-08-18 06:00", "2026-08-18 08:00", r=-1.0)], path=path)

    log = load_log(path)
    entries = [e for e in log if e["date"] == "2026-08-18" and e["symbol"] == "EURUSD"]
    assert len(entries) == 1
    assert entries[0]["trades"][0]["r_multiple"] == -1.0  # the re-run's data wins, not duplicated


def test_different_symbols_same_day_both_kept(tmp_path):
    path = _log_path(tmp_path)
    append_daily_entry("2026-08-18", "EURUSD", "5m", [_trade("2026-08-18 06:00", "2026-08-18 08:00")], path=path)
    append_daily_entry("2026-08-18", "XAUUSD", "3m", [_trade("2026-08-18 06:00", "2026-08-18 08:00")], path=path)

    log = load_log(path)
    assert len(log) == 2


def test_load_missing_file_returns_empty_list(tmp_path):
    assert load_log(str(tmp_path / "nope.json")) == []


def test_trades_in_range_filters_by_date_and_symbol(tmp_path):
    path = _log_path(tmp_path)
    append_daily_entry("2026-08-17", "EURUSD", "5m", [_trade("2026-08-17 06:00", "2026-08-17 08:00")], path=path)
    append_daily_entry("2026-08-18", "EURUSD", "5m", [_trade("2026-08-18 06:00", "2026-08-18 08:00")], path=path)
    append_daily_entry("2026-08-19", "EURUSD", "5m", [_trade("2026-08-19 06:00", "2026-08-19 08:00")], path=path)
    append_daily_entry("2026-08-18", "XAUUSD", "3m", [_trade("2026-08-18 06:00", "2026-08-18 08:00")], path=path)

    trades = trades_in_range("EURUSD", "2026-08-18", "2026-08-19", path=path)
    assert len(trades) == 2

    trades_xau = trades_in_range("XAUUSD", "2026-08-18", "2026-08-19", path=path)
    assert len(trades_xau) == 1


def test_period_stats_and_returns_compounds_across_sub_ranges(tmp_path, monkeypatch):
    import src.journal_log as journal_log
    from src.trade_journal import period_stats_and_returns, compound_returns, period_return_pct

    path = _log_path(tmp_path)
    monkeypatch.setattr(journal_log, "LOG_PATH", path)

    # Week 1: one TP3 win (+3R). Week 2: one direct stop (-1R).
    append_daily_entry("2026-08-03", "EURUSD", "5m", [_trade("2026-08-03 06:00", "2026-08-03 08:00", r=3.0)], path=path)
    append_daily_entry("2026-08-10", "EURUSD", "5m", [_trade("2026-08-10 06:00", "2026-08-10 08:00", r=-1.0)], path=path)

    sub_ranges = [("Week 1", "2026-08-01", "2026-08-07"), ("Week 2", "2026-08-08", "2026-08-14")]
    overall, compounded, sub_returns = period_stats_and_returns("EURUSD", sub_ranges, [1.0])

    assert overall["total_closed"] == 2
    expected = compound_returns([period_return_pct(3.0, 1.0), period_return_pct(-1.0, 1.0)])
    assert compounded[1.0] == pytest.approx(expected)
    assert sub_returns[0] == ("Week 1", period_return_pct(3.0, 1.0))
    assert sub_returns[1] == ("Week 2", period_return_pct(-1.0, 1.0))


def test_week_ranges_in_month_clips_to_month_boundaries():
    from src.trade_journal import week_ranges_in_month

    ranges = week_ranges_in_month(2026, 8)  # Aug 2026: 1st is a Saturday, 31st is a Monday
    assert ranges[0][1] == "2026-08-03"  # first week starts at the first Monday (1st/2nd are weekend)
    assert ranges[-1][2] == "2026-08-31"  # last week ends clipped to the 31st


def test_monthly_report_compounds_its_weeks(tmp_path, monkeypatch):
    import src.journal_log as journal_log
    from src.trade_journal import monthly_report, compound_returns, period_return_pct

    path = _log_path(tmp_path)
    monkeypatch.setattr(journal_log, "LOG_PATH", path)

    append_daily_entry("2026-08-03", "EURUSD", "5m", [_trade("2026-08-03 06:00", "2026-08-03 08:00", r=3.0)], path=path)
    append_daily_entry("2026-08-17", "EURUSD", "5m", [_trade("2026-08-17 06:00", "2026-08-17 08:00", r=-1.0)], path=path)

    overall, compounded, sub_returns = monthly_report("EURUSD", 2026, 8, [1.0])

    assert overall["total_closed"] == 2
    labels = [label for label, _ in sub_returns]
    assert len(labels) == 5  # August 2026 spans 5 partial/full weeks
    # only two weeks actually have trades; the rest contribute a flat 0%
    non_zero = [pct for _, pct in sub_returns if pct != 0]
    assert sorted(non_zero) == sorted([period_return_pct(3.0, 1.0), period_return_pct(-1.0, 1.0)])


def test_yearly_report_compounds_months_which_compound_weeks(tmp_path, monkeypatch):
    import src.journal_log as journal_log
    from src.trade_journal import yearly_report

    path = _log_path(tmp_path)
    monkeypatch.setattr(journal_log, "LOG_PATH", path)

    append_daily_entry("2026-01-05", "EURUSD", "5m", [_trade("2026-01-05 06:00", "2026-01-05 08:00", r=3.0)], path=path)
    append_daily_entry("2026-06-15", "EURUSD", "5m", [_trade("2026-06-15 06:00", "2026-06-15 08:00", r=-1.0)], path=path)

    overall, compounded, sub_returns = yearly_report("EURUSD", 2026, [0.5, 1.0])

    assert overall["total_closed"] == 2
    assert len(sub_returns) == 12
    assert 1.0 in compounded and 0.5 in compounded
    # a +3R month and a -1R month should net out to a small positive compounded return at 1% risk
    assert compounded[1.0] == pytest.approx((1.03 * 0.99 - 1) * 100)
