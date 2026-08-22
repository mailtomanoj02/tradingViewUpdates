"""Position sizing & risk calculator (CLAUDE.md section 4).

Risk-based lot size and dollar-risk matrix across every configured account
size x risk percentage, for a given signal's entry/stop-loss. This is
real-money math -- a unit conversion error here is wrong in every future
email until someone catches it by hand, so keep this module exactly as
literal as the worked-example tests in tests/test_position_sizing.py.

Computes risk-based sizing only -- does not check broker margin/leverage
limits or lot-step minimums beyond 2-decimal rounding (CLAUDE.md section 4).
"""

import os

EURUSD_PIP = 0.0001
EURUSD_DOLLAR_PER_PIP_PER_LOT = 10
XAUUSD_DOLLAR_PER_POINT_PER_LOT = 100

DEFAULT_ACCOUNT_SIZES = [6000.0, 10000.0, 25000.0]
DEFAULT_RISK_PERCENTAGES = [0.5, 0.75, 1.0]


def _parse_float_list(env_var, default):
    raw = os.environ.get(env_var)
    if not raw:
        return default
    return [float(x) for x in raw.split(",")]


def account_sizes():
    """ACCOUNT_SIZES env var (comma-separated), or the spec's defaults."""
    return _parse_float_list("ACCOUNT_SIZES", DEFAULT_ACCOUNT_SIZES)


def risk_percentages():
    """RISK_PERCENTAGES env var (comma-separated), or the spec's defaults."""
    return _parse_float_list("RISK_PERCENTAGES", DEFAULT_RISK_PERCENTAGES)


def _stop_loss_distance_and_dollar_risk_per_lot(symbol, entry, stop_loss):
    """Returns (distance, dollar_risk_per_lot), where distance is in the
    unit the email actually displays: pips for EURUSD, dollars for XAUUSD
    (CLAUDE.md section 6) -- not the raw price difference.
    """
    raw_distance = abs(entry - stop_loss)
    if symbol == "EURUSD":
        pips = raw_distance / EURUSD_PIP
        return pips, pips * EURUSD_DOLLAR_PER_PIP_PER_LOT
    if symbol == "XAUUSD":
        return raw_distance, raw_distance * XAUUSD_DOLLAR_PER_POINT_PER_LOT
    raise ValueError(f"Unknown symbol: {symbol}")


def position_size_matrix(symbol, entry, stop_loss):
    """Lot size + dollar risk across every configured account size x risk %.

    Adding a 4th account size or risk level requires zero code changes --
    the matrix is generated dynamically from ACCOUNT_SIZES/RISK_PERCENTAGES.

    Returns:
        {
            "symbol": str,
            "stop_loss_distance": float,  # pips for EURUSD, dollars for XAUUSD
            "account_sizes": [float, ...],
            "risk_percentages": [float, ...],
            "accounts": [
                {"account_size": float, "risks": [
                    {"risk_percent": float, "lot_size": float, "dollar_risk": float},
                    ...
                ]},
                ...
            ],
        }
    """
    distance, dollar_risk_per_lot = _stop_loss_distance_and_dollar_risk_per_lot(
        symbol, entry, stop_loss
    )
    if dollar_risk_per_lot == 0:
        raise ValueError(f"{symbol}: entry and stop_loss are identical -- zero stop distance")

    sizes = account_sizes()
    risks = risk_percentages()

    accounts = []
    for size in sizes:
        risk_rows = []
        for risk_pct in risks:
            dollar_risk = size * (risk_pct / 100)
            lot_size = round(dollar_risk / dollar_risk_per_lot, 2)
            risk_rows.append(
                {"risk_percent": risk_pct, "lot_size": lot_size, "dollar_risk": round(dollar_risk, 2)}
            )
        accounts.append({"account_size": size, "risks": risk_rows})

    return {
        "symbol": symbol,
        "stop_loss_distance": distance,
        "account_sizes": sizes,
        "risk_percentages": risks,
        "accounts": accounts,
    }
