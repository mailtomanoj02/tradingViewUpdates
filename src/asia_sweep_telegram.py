"""Telegram delivery for the Asia Sweep Reversals system (CLAUDE.md section 14).

This system is Telegram-only -- no email. Every message carries the FULL
content (entry / SL / 3-target ladder / R:R / ATR / per-account
position-size table), not a "check your email" nudge.

It uses its OWN Telegram bot, separate from HalfTrend's: env vars
ASIA_SWEEP_TELEGRAM_BOT_TOKEN / ASIA_SWEEP_TELEGRAM_CHAT_IDS. Both
empty-string-safe -- either unset means the feature is disabled: the run
logs loudly to stderr and sends nothing, it never crashes (CLAUDE.md
section 2 fail-loud posture, minus turning a data problem into a crash).
"""

import os
import sys
from zoneinfo import ZoneInfo

from .email_alert import _format_position_table
from .market_data_client import SYMBOL_INFO
from .position_sizing import EURUSD_PIP, PIP_SYMBOLS
from .telegram_alert import send_telegram_notification

IST = ZoneInfo("Asia/Kolkata")

SPREAD_CAUTION = {
    "EURUSD": "⚠ Confirm live spread before entry — this is a signal, not a fill price.",
    "GBPUSD": "⚠ Confirm live spread before entry — this is a signal, not a fill price.",
    "AUDUSD": "⚠ Confirm live spread before entry — this is a signal, not a fill price.",
    "XAUUSD": "⚠ Gold spreads can widen sharply near news — confirm live spread before entry.",
}


def asia_sweep_bot_token():
    return os.environ.get("ASIA_SWEEP_TELEGRAM_BOT_TOKEN") or ""


def asia_sweep_chat_ids():
    raw = os.environ.get("ASIA_SWEEP_TELEGRAM_CHAT_IDS") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


def _decimals(symbol):
    return SYMBOL_INFO[symbol]["price_decimals"]


def _distance_str(symbol, raw_price_distance):
    if symbol in PIP_SYMBOLS:
        return f"{raw_price_distance / EURUSD_PIP:.1f} pips"
    return f"${raw_price_distance:.2f}"


def _ist(ts):
    return ts.tz_convert(IST).strftime("%d %b %Y, %I:%M %p IST")


def format_sweep_message(event, source):
    """HTML message for an Asia high/low sweep -- a heads-up (no trade yet)."""
    symbol = event["symbol"]
    sweep = event["sweep"]
    d = _decimals(symbol)
    side = sweep["side"]
    swept = sweep["swept_level"]
    emoji = "\U0001f534" if side == "HIGH" else "\U0001f7e2"
    session_label = sweep["session_date"] or "?"

    return "\n".join(
        [
            f"<b>{emoji} Asia {side} swept — {symbol} ({event['timeframe']})</b>",
            f"<i>{_ist(event['bar_time'])}</i>",
            "",
            f"Asia session ({session_label}):",
            f"  High {sweep['session_high']:.{d}f}",
            f"  Mid  {sweep['session_mid']:.{d}f}",
            f"  Low  {sweep['session_low']:.{d}f}",
            "",
            f"Price wicked the Asia {side} ({swept:.{d}f}).",
            "Watch for a CHoCH entry setup on this side.",
            "",
            f"Data source: {source}",
        ]
    )


def format_entry_message(event, matrix, source):
    """HTML message for a CHoCH entry -- the full trade plan + sizing table."""
    symbol = event["symbol"]
    entry_data = event["entry"]
    d = _decimals(symbol)
    direction = entry_data["direction"]
    emoji = "\U0001f7e2" if direction == "LONG" else "\U0001f534"
    e = entry_data["entry"]
    sl = entry_data["stop_loss"]
    rr = entry_data["risk_reward"]

    lines = [
        f"<b>{emoji} {direction} Entry — {symbol} · Asia Sweep Reversal</b>",
        f"<i>{event['timeframe']} · {_ist(event['bar_time'])}</i>",
        "",
        f"Entry: <b>{e:.{d}f}</b>",
        f"Stop Loss: {sl:.{d}f}   ({_distance_str(symbol, abs(e - sl))})",
    ]
    for i in (1, 2, 3):
        t = entry_data[f"target{i}"]
        lines.append(
            f"Target {i}: {t:.{d}f}   ({_distance_str(symbol, abs(e - t))} | R:R 1:{rr[f'target{i}']:.0f})"
        )

    lines += [
        "",
        f"Volatility (ATR): {_distance_str(symbol, entry_data['atr'])} — {entry_data['atr_label']} range",
        "",
        "<b>Position size &amp; risk — per account</b>",
        f"<pre>{_format_position_table(matrix)}</pre>",
        "",
        SPREAD_CAUTION[symbol],
        f"Data source: {source}",
    ]
    return "\n".join(lines)


def send_asia_sweep_message(html):
    """Send one HTML message via the Asia Sweep bot. Returns True if an
    attempt was made (bot configured), False if the feature is disabled.
    Never raises (send_telegram_notification swallows/logs failures).
    """
    token = asia_sweep_bot_token()
    chats = asia_sweep_chat_ids()
    if not token or not chats:
        print(
            "[asia_sweep_telegram] ASIA_SWEEP_TELEGRAM_BOT_TOKEN / "
            "ASIA_SWEEP_TELEGRAM_CHAT_IDS not set -- alert NOT sent.",
            file=sys.stderr,
        )
        return False
    send_telegram_notification(html, token=token, chat_ids=chats, parse_mode="HTML")
    return True
