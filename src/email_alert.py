"""Email formatting + sending (CLAUDE.md section 6).

One email per instrument, sent immediately and independently the moment
its own signal fires -- EURUSD and XAUUSD are never combined (CLAUDE.md
section 2). Delivery via Gmail SMTP with an App Password.
"""

import os
import smtplib
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from .market_data_client import INSTRUMENTS
from .position_sizing import EURUSD_PIP

IST = ZoneInfo("Asia/Kolkata")

SPREAD_CAUTION = {
    "EURUSD": "⚠ Confirm live spread before entry — this is a signal, not a fill price.",
    "XAUUSD": "⚠ Gold spreads can widen sharply near news — confirm live spread before entry.",
}


def _to_display_units(symbol, raw_value):
    """Pips for EURUSD, dollars for XAUUSD -- the unit the email actually shows (CLAUDE.md section 6)."""
    if symbol == "EURUSD":
        return raw_value / EURUSD_PIP
    return raw_value


def _distance_str(symbol, display_value):
    if symbol == "EURUSD":
        return f"{display_value:.1f} pips"
    return f"${display_value:.2f}"


def _price_distance_str(symbol, price_a, price_b):
    return _distance_str(symbol, _to_display_units(symbol, abs(price_a - price_b)))


def _format_position_table(matrix):
    """Box-drawn account-size x risk-% table, generated dynamically from
    matrix['account_sizes']/matrix['risk_percentages'] -- never a hardcoded
    3x3 shape (CLAUDE.md section 4/6).
    """
    headers = ["Account"] + [f"{r:g}%" for r in matrix["risk_percentages"]]
    rows = []
    for account in matrix["accounts"]:
        cells = [f"${account['account_size']:,.0f}"]
        for risk in account["risks"]:
            cells.append(f"{risk['lot_size']:.2f} lot (${round(risk['dollar_risk']):,})")
        rows.append(cells)

    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]

    def border(left, mid, right):
        return left + mid.join("─" * (w + 2) for w in widths) + right

    def row_line(cells):
        return "│ " + " │ ".join(c.ljust(w) for c, w in zip(cells, widths)) + " │"

    lines = [border("┌", "┬", "┐"), row_line(headers), border("├", "┼", "┤")]
    lines += [row_line(row) for row in rows]
    lines.append(border("└", "┴", "┘"))
    return "\n".join(lines)


def format_subject(symbol, direction):
    return f"[{symbol}] {direction} Signal - Entry Formed"


def format_body(signal, matrix, source):
    """Plain-text email body matching CLAUDE.md section 6's canonical format."""
    symbol = signal["symbol"]
    if not signal["direction"]:
        raise ValueError(f"{symbol}: no active signal -- nothing to format")

    cfg = INSTRUMENTS[symbol]
    decimals = cfg["price_decimals"]
    entry = signal["entry"]
    stop_loss = signal["stop_loss"]
    rr = signal["risk_reward"]

    signal_time_ist = signal["signal_time"].tz_convert(IST)

    lines = [
        f"{signal['direction']} ENTRY - {symbol} ({signal['timeframe']})",
        f"Signal Time: {signal_time_ist.strftime('%d %b %Y, %I:%M %p IST')}",
        f"Data Source: {source}",
        "",
        f"Entry: {entry:.{decimals}f}",
        f"Stop Loss: {stop_loss:.{decimals}f}   ({_price_distance_str(symbol, entry, stop_loss)})",
    ]
    for i in (1, 2, 3):
        target = signal[f"target{i}"]
        dist_str = _price_distance_str(symbol, entry, target)
        lines.append(f"Target {i}: {target:.{decimals}f}    ({dist_str} | R:R 1:{rr[f'target{i}']:.0f})")

    atr_str = _distance_str(symbol, _to_display_units(symbol, signal["atr"]))
    lines += [
        "",
        f"Volatility (ATR): {atr_str} — {signal['atr_label']} range",
        "",
        "POSITION SIZE & RISK — per account",
        _format_position_table(matrix),
        "",
        SPREAD_CAUTION[symbol],
    ]
    return "\n".join(lines)


def send_email(subject, body):
    sender = os.environ["GMAIL_SENDER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["ALERT_RECIPIENT_EMAIL"]

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def send_signal_alert(signal, matrix, source):
    """Format and send one alert email for one instrument's signal."""
    subject = format_subject(signal["symbol"], signal["direction"])
    body = format_body(signal, matrix, source)
    send_email(subject, body)
    return subject, body
