import pandas as pd
import pytest

from src.email_alert import format_body, format_subject
from src.position_sizing import position_size_matrix


def _eurusd_signal():
    entry, stop_loss = 1.0842, 1.0821
    dist = entry - stop_loss
    return {
        "symbol": "EURUSD",
        "timeframe": "5m",
        "signal_time": pd.Timestamp("2026-08-22 05:05:00", tz="UTC"),  # 10:35 AM IST
        "direction": "LONG",
        "entry": entry,
        "stop_loss": stop_loss,
        "target1": entry + dist,
        "target2": entry + dist * 2,
        "target3": entry + dist * 3,
        "atr": 0.00019,
        "atr_label": "normal",
        "risk_reward": {"target1": 1.0, "target2": 2.0, "target3": 3.0},
    }


def _xauusd_signal():
    entry, stop_loss = 4602.30, 4608.10
    dist = stop_loss - entry
    return {
        "symbol": "XAUUSD",
        "timeframe": "3m",
        "signal_time": pd.Timestamp("2026-08-22 05:32:00", tz="UTC"),
        "direction": "SHORT",
        "entry": entry,
        "stop_loss": stop_loss,
        "target1": entry - dist,
        "target2": entry - dist * 2,
        "target3": entry - dist * 3,
        "atr": 4.9,
        "atr_label": "above-average",
        "risk_reward": {"target1": 1.0, "target2": 2.0, "target3": 3.0},
    }


def test_subject_format():
    assert format_subject("EURUSD", "LONG") == "[EURUSD] LONG Signal - Entry Formed"
    assert format_subject("XAUUSD", "SHORT") == "[XAUUSD] SHORT Signal - Entry Formed"


def test_eurusd_body_shows_pips_and_ist_time(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,10000,25000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,0.75,1")
    signal = _eurusd_signal()
    matrix = position_size_matrix("EURUSD", signal["entry"], signal["stop_loss"])

    body = format_body(signal, matrix, "OANDA")

    assert "LONG ENTRY - EURUSD (5m)" in body
    assert "10:35 AM IST" in body
    assert "Data Source: OANDA" in body
    assert "Entry: 1.08420" in body
    assert "pips" in body
    assert "$" not in body.split("POSITION SIZE")[0]  # no dollar signs before the table for EURUSD
    assert "R:R 1:1" in body and "R:R 1:2" in body and "R:R 1:3" in body
    assert "Confirm live spread before entry" in body


def test_xauusd_body_shows_dollars_and_gold_caution(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,10000,25000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,0.75,1")
    signal = _xauusd_signal()
    matrix = position_size_matrix("XAUUSD", signal["entry"], signal["stop_loss"])

    body = format_body(signal, matrix, "Yahoo Finance (yfinance, unofficial)")

    assert "SHORT ENTRY - XAUUSD (3m)" in body
    assert "Data Source: Yahoo Finance (yfinance, unofficial)" in body
    assert "Entry: 4602.30" in body
    assert "$5.80" in body
    assert "Gold spreads can widen sharply near news" in body
    assert "above-average range" in body


def test_table_reflects_configured_accounts_and_risks_not_hardcoded(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,10000,25000,50000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,0.75,1,1.5")
    signal = _eurusd_signal()
    matrix = position_size_matrix("EURUSD", signal["entry"], signal["stop_loss"])

    body = format_body(signal, matrix, "OANDA")

    assert "$50,000" in body
    assert "1.5%" in body


def test_worked_example_lot_sizes_appear_in_body(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,25000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,1")
    signal = _eurusd_signal()
    matrix = position_size_matrix("EURUSD", signal["entry"], signal["stop_loss"])

    body = format_body(signal, matrix, "OANDA")

    assert "0.14 lot" in body
    assert "1.19 lot" in body


def test_format_body_raises_when_no_active_signal(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5")
    signal = _eurusd_signal()
    signal["direction"] = None
    matrix = position_size_matrix("EURUSD", 1.0842, 1.0821)

    with pytest.raises(ValueError):
        format_body(signal, matrix, "OANDA")
