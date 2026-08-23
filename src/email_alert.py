"""Email formatting + sending (CLAUDE.md section 6).

One email per instrument, sent immediately and independently the moment
its own signal fires -- EURUSD and XAUUSD are never combined (CLAUDE.md
section 2). Delivery via Gmail SMTP with an App Password.
"""

import os
import smtplib
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from .journal_email import BORDER, CARD_BG, GRAY, GREEN, RED, _wrap
from .market_data_client import INSTRUMENTS
from .position_sizing import EURUSD_PIP
from .telegram_alert import format_telegram_message, send_telegram_notification

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


def format_html_body(signal, matrix, source):
    """HTML email body -- same content/numbers as format_body, styled to
    match the trade-journal emails (journal_email.py). Table-based, inline
    styles only, for consistent rendering across email clients.
    """
    symbol = signal["symbol"]
    if not signal["direction"]:
        raise ValueError(f"{symbol}: no active signal -- nothing to format")

    cfg = INSTRUMENTS[symbol]
    decimals = cfg["price_decimals"]
    entry = signal["entry"]
    stop_loss = signal["stop_loss"]
    rr = signal["risk_reward"]
    direction = signal["direction"]
    accent = GREEN if direction == "LONG" else RED
    signal_time_ist = signal["signal_time"].tz_convert(IST)

    header = f"""
    <div style="background:{accent};border-radius:8px 8px 0 0;padding:20px 24px;">
      <div style="color:#ffffff;font-size:20px;font-weight:800;">{symbol} {direction} Signal</div>
      <div style="color:#ffffff;opacity:0.85;font-size:13px;margin-top:4px;">
        {cfg['candle_minutes']}m &middot; Entry Formed &middot; {signal_time_ist.strftime('%d %b %Y, %I:%M %p IST')}
      </div>
      <div style="color:#ffffff;opacity:0.7;font-size:11px;margin-top:6px;">Data Source: {source}</div>
    </div>
    """

    def price_row(label, value, note, color=GRAY, bg=None):
        bg_style = f"background:{bg};" if bg else ""
        return f"""<tr style="{bg_style}">
          <td style="padding:10px 12px;font-size:13px;color:{GRAY};border-top:1px solid {BORDER};">{label}</td>
          <td style="padding:10px 12px;font-size:15px;font-weight:700;text-align:right;border-top:1px solid {BORDER};">{value:.{decimals}f}</td>
          <td style="padding:10px 12px;font-size:12px;color:{color};text-align:right;border-top:1px solid {BORDER};white-space:nowrap;">{note}</td>
        </tr>"""

    price_rows = [price_row("Entry", entry, "", bg=CARD_BG)]
    price_rows.append(price_row("Stop Loss", stop_loss, _price_distance_str(symbol, entry, stop_loss), color=RED))
    for i in (1, 2, 3):
        target = signal[f"target{i}"]
        dist_str = _price_distance_str(symbol, entry, target)
        price_rows.append(
            price_row(f"Target {i}", target, f"{dist_str} | R:R 1:{rr[f'target{i}']:.0f}", color=GREEN)
        )

    atr_str = _distance_str(symbol, _to_display_units(symbol, signal["atr"]))

    pos_headers = ["Account"] + [f"{r:g}%" for r in matrix["risk_percentages"]]
    pos_header_cells = "".join(
        f'<th style="text-align:{"left" if i == 0 else "right"};padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">{h}</th>'
        for i, h in enumerate(pos_headers)
    )
    pos_rows = []
    for account in matrix["accounts"]:
        cells = f'<td style="padding:8px 10px;font-size:13px;color:{GRAY};border-top:1px solid {BORDER};">${account["account_size"]:,.0f}</td>'
        for risk in account["risks"]:
            cells += (
                f'<td style="padding:8px 10px;font-size:13px;text-align:right;border-top:1px solid {BORDER};">'
                f'{risk["lot_size"]:.2f} lot <span style="color:{GRAY};">(${round(risk["dollar_risk"]):,})</span></td>'
            )
        pos_rows.append(f"<tr>{cells}</tr>")

    body = f"""
    {header}
    <div style="padding:20px 24px;">
      <table style="width:100%;border-collapse:collapse;">{"".join(price_rows)}</table>

      <div style="margin-top:16px;background:{CARD_BG};border:1px solid {BORDER};border-radius:8px;padding:12px 16px;font-size:13px;color:{GRAY};">
        Volatility (ATR): <strong style="color:#0f172a;">{atr_str}</strong> &mdash; {signal['atr_label']} range
      </div>

      <div style="font-size:13px;font-weight:700;color:{GRAY};text-transform:uppercase;margin:20px 0 4px;">Position Size &amp; Risk — per account</div>
      <table style="width:100%;border-collapse:collapse;">
        <tr>{pos_header_cells}</tr>
        {"".join(pos_rows)}
      </table>

      <div style="margin-top:20px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 16px;font-size:13px;color:#92400e;">
        {SPREAD_CAUTION[symbol]}
      </div>
    </div>
    """
    return _wrap(body)


def send_email(subject, body):
    _send(subject, MIMEText(body, "plain"))


def send_html_email(subject, html_body):
    _send(subject, MIMEText(html_body, "html"))


def _send(subject, msg):
    sender = os.environ["GMAIL_SENDER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["ALERT_RECIPIENT_EMAIL"]

    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def send_signal_alert(signal, matrix, source):
    """Format and send one alert email for one instrument's signal (HTML),
    plus a best-effort Telegram nudge (see telegram_alert.py) if
    TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_IDS are configured -- a Telegram
    failure never blocks or fails this, since the email above is the
    real, guaranteed alert.
    """
    subject = format_subject(signal["symbol"], signal["direction"])
    html = format_html_body(signal, matrix, source)
    send_html_email(subject, html)
    send_telegram_notification(format_telegram_message(signal))
    return subject, html
