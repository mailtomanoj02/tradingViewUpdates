import pandas as pd
import pytest

from src.asia_sweep_journal_telegram import render_daily_digest, render_period_digest
from src.asia_sweep_telegram import (
    format_entry_message,
    format_sweep_message,
    send_asia_sweep_message,
)
from src.position_sizing import position_size_matrix

TS = pd.Timestamp("2026-08-25 13:15", tz="UTC")


def _entry_event(symbol="GBPUSD"):
    return {
        "symbol": symbol,
        "timeframe": "1m",
        "bar_time": TS,
        "sweep": None,
        "entry": {
            "direction": "SHORT",
            "entry": 1.2650,
            "stop_loss": 1.2665,
            "target1": 1.2635,
            "target2": 1.2620,
            "target3": 1.2605,
            "risk_reward": {"target1": 1.0, "target2": 2.0, "target3": 3.0},
            "atr": 0.00082,
            "atr_label": "normal",
        },
    }


def _sweep_event(symbol="XAUUSD"):
    return {
        "symbol": symbol,
        "timeframe": "1m",
        "bar_time": TS,
        "sweep": {
            "side": "HIGH",
            "swept_level": 4602.50,
            "session_high": 4602.50,
            "session_low": 4590.00,
            "session_mid": 4596.25,
            "session_start": pd.Timestamp("2026-08-24 23:00", tz="UTC"),
            "session_date": "2026-08-24",
        },
        "entry": None,
    }


def test_entry_message_has_full_plan_and_sizing_table(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,10000,25000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,0.75,1")
    event = _entry_event()
    matrix = position_size_matrix("GBPUSD", event["entry"]["entry"], event["entry"]["stop_loss"])
    msg = format_entry_message(event, matrix, "OANDA")

    assert "SHORT Entry — GBPUSD" in msg
    assert "Entry: <b>1.26500</b>" in msg
    assert "Stop Loss: 1.26650" in msg
    assert "R:R 1:3" in msg
    assert "<pre>" in msg and "</pre>" in msg  # monospace sizing table
    assert "0.5%" in msg or "0.5" in msg
    assert "Data source: OANDA" in msg
    assert "spread" in msg.lower()


def test_entry_message_gold_uses_dollar_distances_and_gold_caution(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000")
    monkeypatch.setenv("RISK_PERCENTAGES", "1")
    event = _entry_event("XAUUSD")
    event["entry"].update(entry=4602.30, stop_loss=4608.10, target1=4596.5, target2=4590.7, target3=4584.9)
    matrix = position_size_matrix("XAUUSD", 4602.30, 4608.10)
    msg = format_entry_message(event, matrix, "OANDA")
    assert "$5.80" in msg
    assert "Gold spreads" in msg


def test_sweep_message_is_a_heads_up_without_sizing():
    msg = format_sweep_message(_sweep_event(), "Yahoo Finance (yfinance, unofficial)")
    assert "Asia HIGH swept — XAUUSD" in msg
    assert "4602.50" in msg
    assert "4590.00" in msg
    assert "<pre>" not in msg
    assert "2026-08-24" in msg


def test_send_is_noop_and_returns_false_without_bot_config(monkeypatch, capsys):
    monkeypatch.delenv("ASIA_SWEEP_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ASIA_SWEEP_TELEGRAM_CHAT_IDS", raising=False)
    assert send_asia_sweep_message("hi") is False
    assert "not set" in capsys.readouterr().err


def test_send_uses_the_asia_sweep_bot_and_html_parse_mode(monkeypatch):
    monkeypatch.setenv("ASIA_SWEEP_TELEGRAM_BOT_TOKEN", "999:XYZ")
    monkeypatch.setenv("ASIA_SWEEP_TELEGRAM_CHAT_IDS", "-1003768821764")
    captured = {}

    def fake_send(message, token=None, chat_ids=None, parse_mode=None):
        captured.update(message=message, token=token, chat_ids=chat_ids, parse_mode=parse_mode)

    monkeypatch.setattr("src.asia_sweep_telegram.send_telegram_notification", fake_send)
    assert send_asia_sweep_message("<b>hi</b>") is True
    assert captured["token"] == "999:XYZ"
    assert captured["chat_ids"] == ["-1003768821764"]
    assert captured["parse_mode"] == "HTML"


# --- journal digest --------------------------------------------------------

def _stats(closed, wins, losses, r_total, outcomes):
    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) else None
    return {
        "total_closed": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "r_total": r_total,
        "outcome_counts": outcomes,
    }


def test_daily_digest_is_one_combined_message_covering_all_pairs(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,25000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,1")
    per_symbol = [
        ("XAUUSD", "1m", _stats(2, 2, 1, 1.0, {"TP3 (full target)": 1, "Direct Stop Loss": 1}), 0),
        ("EURUSD", "1m", _stats(1, 0, 1, -1.0, {"Direct Stop Loss": 1}), 1),
        ("GBPUSD", "1m", _stats(0, 0, 0, 0.0, {}), 0),
        ("AUDUSD", "1m", _stats(3, 3, 0, 3.0, {"TP3 (full target)": 1, "TP1+TP2 then Stop": 2}), 0),
    ]
    msgs = render_daily_digest("25 Aug 2026 (Tuesday)", per_symbol)
    assert len(msgs) == 1
    body = msgs[0]
    for sym in ("XAUUSD", "EURUSD", "GBPUSD", "AUDUSD"):
        assert sym in body
    assert "All pairs" in body
    assert "Return by Account" in body
    # combined net R = 1 - 1 + 0 + 3 = 3R
    assert "+3.0R" in body


def test_period_digest_marks_monthly_as_compounded(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "10000")
    monkeypatch.setenv("RISK_PERCENTAGES", "1")
    per_symbol = [
        (s, "1m", _stats(1, 1, 0, 3.0, {"TP3 (full target)": 1}), {1.0: 3.0})
        for s in ("XAUUSD", "EURUSD", "GBPUSD", "AUDUSD")
    ]
    msgs = render_period_digest("Monthly", "August 2026", per_symbol)
    assert any("compounded" in m for m in msgs)
