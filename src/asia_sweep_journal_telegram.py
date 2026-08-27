"""Combined Telegram journal digest for the Asia Sweep system (CLAUDE.md section 14).

One message per period (daily / weekly / monthly / yearly) covering all 4
pairs together -- not one message per pair. Telegram-only, full content.

Returns a LIST of message strings: a single digest that would exceed
Telegram's 4096-char limit is split pair-by-pair into consecutive
messages.

Compounding follows CLAUDE.md section 12: within a period, R is
simple-summed; across periods it compounds. For the combined
"Return by Account" line the per-pair period returns are treated as
stacking sub-returns and compounded together (running all 4 pairs in one
account) -- daily/weekly use each pair's simple r_total, monthly/yearly
use each pair's already week/month-compounded return.
"""

from .position_sizing import account_sizes, risk_percentages
from .trade_journal import compound_returns, period_return_pct

TELEGRAM_LIMIT = 4096
_SAFE_LIMIT = 3900


def _fmt_pct(value, decimals=2):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def _fmt_r(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}R"


def _outcome_line(outcome_counts):
    order = [
        ("TP3 (full target)", "TP3"),
        ("TP1+TP2 then Stop", "TP1+TP2"),
        ("TP1 then Stop (scratch)", "scratch"),
        ("Direct Stop Loss", "stop"),
    ]
    return ", ".join(f"{short} {outcome_counts.get(full, 0)}" for full, short in order)


def _pair_section(symbol, timeframe, stats, extra_line=None):
    win = f"{stats['win_rate']}%" if stats["win_rate"] is not None else "—"
    lines = [
        f"<b>{symbol}</b> ({timeframe})",
        f"  Closed {stats['total_closed']} · Win {win} · Net {_fmt_r(stats['r_total'])}",
        f"  {_outcome_line(stats['outcome_counts'])}",
    ]
    if extra_line:
        lines.append(f"  {extra_line}")
    return "\n".join(lines)


def _account_table(combined_by_risk):
    """Monospace <pre> block: dollar return per configured account x risk."""
    risks = list(combined_by_risk.keys())
    header = "Account".ljust(10) + "".join(f"{r:g}%".rjust(14) for r in risks)
    rows = [header]
    for size in account_sizes():
        cells = f"${size:,.0f}".ljust(10)
        for risk in risks:
            pct = combined_by_risk[risk]
            dollar = size * (pct / 100)
            sign = "+" if dollar > 0 else ("-" if dollar < 0 else "")
            cells += f"{sign}${abs(dollar):,.0f} ({_fmt_pct(pct, 1)})".rjust(14)
        rows.append(cells)
    return "<pre>" + "\n".join(rows) + "</pre>"


def _pack(header, sections, footer):
    """Pack sections into as few messages as possible under _SAFE_LIMIT,
    repeating the header on each continuation message.
    """
    messages = []
    current = header
    for section in sections:
        candidate = current + "\n\n" + section
        if len(candidate) > _SAFE_LIMIT and current != header:
            messages.append(current)
            current = header + " (cont.)\n\n" + section
        else:
            current = candidate
    if footer:
        if len(current + "\n\n" + footer) > _SAFE_LIMIT:
            messages.append(current)
            current = header + " (cont.)\n\n" + footer
        else:
            current = current + "\n\n" + footer
    messages.append(current)
    return messages


def render_daily_digest(date_label, per_symbol):
    """per_symbol: list of (symbol, timeframe, stats, open_count)."""
    risks = risk_percentages()
    header = f"<b>📓 Asia Sweep — Daily Journal</b>\n<i>{date_label}</i>"

    sections = []
    combined_r = 0.0
    total_open = 0
    for symbol, timeframe, stats, open_count in per_symbol:
        combined_r += stats["r_total"]
        total_open += open_count
        extra = f"{open_count} still open" if open_count else None
        sections.append(_pair_section(symbol, timeframe, stats, extra))

    combined_by_risk = {risk: period_return_pct(combined_r, risk) for risk in risks}
    footer = (
        f"<b>All pairs</b> — Net {_fmt_r(combined_r)}"
        + (f" · {total_open} open" if total_open else "")
        + "\n<b>Return by Account (all pairs)</b>\n"
        + _account_table(combined_by_risk)
    )
    return _pack(header, sections, footer)


def render_period_digest(period_kind, period_label, per_symbol):
    """period_kind: 'Weekly' | 'Monthly' | 'Yearly'.

    per_symbol: list of (symbol, timeframe, stats, pct_by_risk) where
    pct_by_risk is {risk_pct: period_return_%} for this pair -- simple
    r_total*risk for Weekly, the compounded value for Monthly/Yearly.
    """
    risks = risk_percentages()
    header = f"<b>📓 Asia Sweep — {period_kind} Journal</b>\n<i>{period_label}</i>"

    sections = []
    representative_risk = risks[0]
    for symbol, timeframe, stats, pct_by_risk in per_symbol:
        extra = f"Return {_fmt_pct(pct_by_risk[representative_risk])} at {representative_risk:g}% risk"
        sections.append(_pair_section(symbol, timeframe, stats, extra))

    # Combined: compound each pair's period return together (all pairs in one account).
    combined_by_risk = {
        risk: compound_returns([pct_by_risk[risk] for _, _, _, pct_by_risk in per_symbol])
        for risk in risks
    }
    footer = (
        f"<b>Return by Account (all pairs, {period_kind.lower()}"
        + (", compounded" if period_kind in ("Monthly", "Yearly") else "")
        + ")</b>\n"
        + _account_table(combined_by_risk)
    )
    return _pack(header, sections, footer)
