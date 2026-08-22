"""HTML email templates for the trade journal (daily/weekly/monthly/yearly).

Table-based layout with inline styles only -- email clients (especially
Gmail) strip <style> blocks and mishandle flexbox/grid, so this
deliberately avoids both in favor of the one layout approach that renders
consistently everywhere.
"""

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

GREEN = "#15803d"
RED = "#b91c1c"
GRAY = "#475569"
BORDER = "#e2e8f0"
CARD_BG = "#f8fafc"
HEADER_BG = "#0f172a"


def _r_color(value):
    if value is None:
        return GRAY
    return GREEN if value > 0 else (RED if value < 0 else GRAY)


def _fmt_pct(value, decimals=2):
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def _fmt_r(value):
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}R"


def _stat_card(label, value, color=GRAY):
    return f"""
    <td style="padding:8px;">
      <div style="background:{CARD_BG};border:1px solid {BORDER};border-radius:8px;padding:14px 16px;text-align:center;">
        <div style="font-size:12px;color:{GRAY};text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:{color};">{value}</div>
      </div>
    </td>
    """


def _header(title, subtitle):
    return f"""
    <div style="background:{HEADER_BG};border-radius:8px 8px 0 0;padding:20px 24px;">
      <div style="color:#ffffff;font-size:18px;font-weight:700;">{title}</div>
      <div style="color:#94a3b8;font-size:13px;margin-top:4px;">{subtitle}</div>
    </div>
    """


def _outcome_counts_row(outcome_counts):
    order = ["TP3 (full target)", "TP1+TP2 then Stop", "TP1 then Stop (scratch)", "Direct Stop Loss"]
    cells = []
    for label in order:
        count = outcome_counts.get(label, 0)
        color = GREEN if "TP3" in label or "TP1+TP2" in label else (GRAY if "scratch" in label else RED)
        cells.append(_stat_card(label, count, color))
    return "".join(cells)


def _returns_by_risk(r_total, risk_percentages):
    return {risk: r_total * risk for risk in risk_percentages}


def _account_return_table(returns_by_risk, account_sizes):
    """Dollar return per configured account size x risk tier (not just an
    abstract %) -- same account-row/risk-column shape as the position-size
    table in the alert emails (email_alert.py), so the two are visually
    consistent.
    """
    risks = list(returns_by_risk.keys())
    header_cells = f'<th style="text-align:left;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">Account</th>' + "".join(
        f'<th style="text-align:right;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">{r:g}% risk</th>'
        for r in risks
    )
    rows = []
    for account in account_sizes:
        cells = f'<td style="padding:8px 10px;font-size:13px;color:{GRAY};border-top:1px solid {BORDER};">${account:,.0f}</td>'
        for risk in risks:
            pct = returns_by_risk[risk]
            dollar = account * (pct / 100)
            color = _r_color(dollar)
            sign = "+" if dollar > 0 else ("-" if dollar < 0 else "")
            cells += (
                f'<td style="padding:8px 10px;font-size:13px;text-align:right;border-top:1px solid {BORDER};">'
                f'<span style="font-weight:700;color:{color};">{sign}${abs(dollar):,.2f}</span>'
                f'<span style="color:{GRAY};font-size:11px;"> ({_fmt_pct(pct)})</span></td>'
            )
        rows.append(f"<tr>{cells}</tr>")
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:8px;">
      <tr>{header_cells}</tr>
      {"".join(rows)}
    </table>
    """


def _trades_table(trades, decimals):
    if not trades:
        return f'<div style="color:{GRAY};padding:12px 0;">No trades in this period.</div>'

    rows = []
    for t in trades:
        outcome = t["outcome"]
        r_color = _r_color(t["r_multiple"])
        close_str = t["close_time"].tz_convert(IST).strftime("%d %b, %I:%M %p") if t["close_time"] else "still open"
        rows.append(
            f"""<tr>
              <td style="padding:8px 10px;border-top:1px solid {BORDER};font-size:13px;color:{GRAY};">{t['signal_time'].tz_convert(IST).strftime('%d %b, %I:%M %p')}</td>
              <td style="padding:8px 10px;border-top:1px solid {BORDER};font-size:13px;font-weight:600;">{t['direction']}</td>
              <td style="padding:8px 10px;border-top:1px solid {BORDER};font-size:13px;">{t['entry']:.{decimals}f}</td>
              <td style="padding:8px 10px;border-top:1px solid {BORDER};font-size:13px;">{outcome}</td>
              <td style="padding:8px 10px;border-top:1px solid {BORDER};font-size:13px;color:{GRAY};">{close_str}</td>
              <td style="padding:8px 10px;border-top:1px solid {BORDER};font-size:13px;font-weight:700;color:{r_color};text-align:right;">{_fmt_r(t['r_multiple'])}</td>
            </tr>"""
        )

    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:8px;">
      <tr>
        <th style="text-align:left;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">Signal Time</th>
        <th style="text-align:left;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">Dir</th>
        <th style="text-align:left;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">Entry</th>
        <th style="text-align:left;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">Outcome</th>
        <th style="text-align:left;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">Closed</th>
        <th style="text-align:right;padding:8px 10px;font-size:11px;color:{GRAY};text-transform:uppercase;">R</th>
      </tr>
      {"".join(rows)}
    </table>
    """


def _wrap(body_html):
    return f"""<div style="max-width:640px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
      <div style="border:1px solid {BORDER};border-radius:8px;overflow:hidden;">
        {body_html}
      </div>
      <div style="color:#94a3b8;font-size:11px;padding:16px 8px;text-align:center;">
        Signal-only system. Not investment advice. Outcomes simulated from candle data, not live executions.
      </div>
    </div>"""


def render_daily_email(symbol, timeframe, date_label, stats, open_count, trades, decimals, risk_percentages, account_sizes):
    header = _header(f"{symbol} Daily Journal", f"{date_label} · {timeframe}")
    stat_cards = (
        _stat_card("Trades Closed", stats["total_closed"])
        + _stat_card("Win Rate", f"{stats['win_rate']}%" if stats["win_rate"] is not None else "—")
        + _stat_card("Still Open", open_count)
        + _stat_card("Net R", _fmt_r(stats["r_total"]), _r_color(stats["r_total"]))
    )
    body = f"""
    {header}
    <div style="padding:20px 24px;">
      <table style="width:100%;border-collapse:collapse;"><tr>{stat_cards}</tr></table>
      <div style="font-size:13px;font-weight:700;color:{GRAY};text-transform:uppercase;margin:20px 0 4px;">Outcome Breakdown</div>
      <table style="width:100%;border-collapse:collapse;"><tr>{_outcome_counts_row(stats["outcome_counts"])}</tr></table>
      <div style="font-size:13px;font-weight:700;color:{GRAY};text-transform:uppercase;margin:20px 0 4px;">Today's Return by Account</div>
      {_account_return_table(_returns_by_risk(stats["r_total"], risk_percentages), account_sizes)}
      <div style="font-size:13px;font-weight:700;color:{GRAY};text-transform:uppercase;margin:20px 0 4px;">Trades Closed Today</div>
      {_trades_table(trades, decimals)}
    </div>
    """
    return _wrap(body)


def render_period_email(
    symbol,
    timeframe,
    period_kind,
    period_label,
    stats,
    risk_percentages,
    account_sizes,
    sub_periods=None,
    returns_by_risk=None,
):
    """period_kind: 'Weekly' | 'Monthly' | 'Yearly'. sub_periods: optional
    list of (label, return_pct_at_default_risk) for a mini breakdown table
    (weeks within a month, months within a year). returns_by_risk: optional
    {risk_pct: compounded %} -- pass this for Monthly/Yearly (compounded
    across sub-periods) instead of letting the table compute a simple
    r_total*risk (which is only correct for a single base period).
    """
    header = _header(f"{symbol} {period_kind} Journal", period_label)
    stat_cards = (
        _stat_card("Trades Closed", stats["total_closed"])
        + _stat_card("Win Rate", f"{stats['win_rate']}%" if stats["win_rate"] is not None else "—")
        + _stat_card("Net R", _fmt_r(stats["r_total"]), _r_color(stats["r_total"]))
    )
    sub_table = ""
    if sub_periods:
        rows = "".join(
            f'<tr><td style="padding:8px 12px;border-top:1px solid {BORDER};color:{GRAY};">{label}</td>'
            f'<td style="padding:8px 12px;border-top:1px solid {BORDER};text-align:right;font-weight:600;color:{_r_color(pct)};">{_fmt_pct(pct)}</td></tr>'
            for label, pct in sub_periods
        )
        sub_table = f"""
        <div style="font-size:13px;font-weight:700;color:{GRAY};text-transform:uppercase;margin:20px 0 4px;">Breakdown</div>
        <table style="width:100%;border-collapse:collapse;">{rows}</table>
        """
    body = f"""
    {header}
    <div style="padding:20px 24px;">
      <table style="width:100%;border-collapse:collapse;"><tr>{stat_cards}</tr></table>
      <div style="font-size:13px;font-weight:700;color:{GRAY};text-transform:uppercase;margin:20px 0 4px;">Outcome Breakdown</div>
      <table style="width:100%;border-collapse:collapse;"><tr>{_outcome_counts_row(stats["outcome_counts"])}</tr></table>
      <div style="font-size:13px;font-weight:700;color:{GRAY};text-transform:uppercase;margin:20px 0 4px;">Return by Account (this {period_kind.lower()}{", compounded" if returns_by_risk else ""})</div>
      {_account_return_table(returns_by_risk if returns_by_risk else _returns_by_risk(stats["r_total"], risk_percentages), account_sizes)}
      {sub_table}
    </div>
    """
    return _wrap(body)
