"""HalfTrend strategy engine.

Line-for-line port of reference/halftrend_source.pine's core signal logic
(CLAUDE.md section 3). Symbol/timeframe agnostic: works on any OHLC
DataFrame of confirmed/closed candles, ascending by time.

Do not simplify or "clean up" the trend/nextTrend state machine below --
it is a direct translation of the Pine script's var-persisted state, not
an approximation of it. See CLAUDE.md section 3 for the full annotated
walkthrough this was ported from.
"""

import os

import numpy as np
import pandas as pd

DEFAULT_AMPLITUDE = 20
DEFAULT_CHANNEL_DEVIATION = 2.0
DEFAULT_BASE_RISK_MULT = 3.0


def strategy_params(symbol):
    """Per-instrument HalfTrend parameters, overridable via env vars
    (e.g. EURUSD_AMPLITUDE, EURUSD_CHANNEL_DEVIATION, EURUSD_BASE_RISK_MULT).

    Falls back to the Pine script's declared defaults (CLAUDE.md section 3)
    for anything not set. Different instruments can be tuned independently
    without any code change -- just set the matching env var.
    """
    prefix = symbol.upper()
    return {
        "amplitude": int(os.environ.get(f"{prefix}_AMPLITUDE", DEFAULT_AMPLITUDE)),
        "channel_deviation": float(
            os.environ.get(f"{prefix}_CHANNEL_DEVIATION", DEFAULT_CHANNEL_DEVIATION)
        ),
        "base_risk_mult": float(
            os.environ.get(f"{prefix}_BASE_RISK_MULT", DEFAULT_BASE_RISK_MULT)
        ),
    }


def wilder_atr(high, low, close, length=100):
    """Wilder-smoothed ATR (Pine's ta.atr) -- NOT a plain rolling mean.

    rma[i] = rma[i-1] + (tr[i] - rma[i-1]) / length, seeded with tr[0].
    This is exactly pandas' ewm(alpha=1/length, adjust=False).mean().
    """
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False).mean()


def compute_halftrend(df, amplitude=20, channel_deviation=2.0, base_risk_mult=3.0):
    """Run the HalfTrend engine over `df`.

    `df` must have open/high/low/close columns, ascending by time,
    containing only confirmed/closed candles.

    Returns a copy of `df` with added columns: atr2, trend (0=bullish,
    1=bearish), up, down, ht_line, buy_signal, sell_signal, and (on signal
    rows only) entry/stop_loss/target1/target2/target3.

    channel_deviation is accepted for config fidelity with the source
    script but has no effect here -- in the original it only drives the
    atrHigh/atrLow visualization bands, which this port intentionally
    omits (CLAUDE.md section 3, "channelDeviation note").
    """
    high, low, close = df["high"], df["low"], df["close"]

    atr2 = wilder_atr(high, low, close, length=100) / 2
    # Pine's highPrice/lowPrice = the actual high/low AT the bar with the
    # highest-high / lowest-low in the window -- which, by definition, is
    # just that window's max/min value. Equivalent to ta.highest/ta.lowest.
    high_price = high.rolling(amplitude).max()
    low_price = low.rolling(amplitude).min()
    highma = high.rolling(amplitude).mean()
    lowma = low.rolling(amplitude).mean()
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    n = len(df)
    trend = np.zeros(n, dtype=int)
    next_trend = np.zeros(n, dtype=int)
    max_low_price = np.full(n, np.nan)
    min_high_price = np.full(n, np.nan)
    up = np.full(n, np.nan)
    down = np.full(n, np.nan)

    warmed_up = (
        atr2.notna() & high_price.notna() & low_price.notna() & highma.notna() & lowma.notna()
    )

    start = None
    for i in range(n):
        if not warmed_up.iloc[i]:
            continue

        if start is None:
            start = i
            max_low_price[i] = low.iloc[i]
            min_high_price[i] = high.iloc[i]
            up[i] = max_low_price[i]
            down[i] = 0.0
            continue

        prev_trend = trend[i - 1]
        t = prev_trend
        nt = next_trend[i - 1]
        mlp = max_low_price[i - 1]
        mhp = min_high_price[i - 1]
        prev_up = up[i - 1]
        prev_down = down[i - 1]

        pl = prev_low.iloc[i] if not pd.isna(prev_low.iloc[i]) else low.iloc[i]
        ph = prev_high.iloc[i] if not pd.isna(prev_high.iloc[i]) else high.iloc[i]

        if nt == 1:
            mlp = max(low_price.iloc[i], mlp)
            if highma.iloc[i] < mlp and close.iloc[i] < pl:
                t = 1
                nt = 0
                mhp = high_price.iloc[i]
        else:
            mhp = min(high_price.iloc[i], mhp)
            if lowma.iloc[i] > mhp and close.iloc[i] > ph:
                t = 0
                nt = 1
                mlp = low_price.iloc[i]

        trend[i] = t
        next_trend[i] = nt
        max_low_price[i] = mlp
        min_high_price[i] = mhp

        if t == 0:
            up[i] = prev_down if prev_trend != 0 else (
                mlp if pd.isna(prev_up) else max(mlp, prev_up)
            )
            down[i] = prev_down
        else:
            down[i] = prev_up if prev_trend != 1 else (
                mhp if pd.isna(prev_down) else min(mhp, prev_down)
            )
            up[i] = prev_up

    result = df.copy()
    result["atr2"] = atr2
    result["trend"] = np.where(warmed_up, trend, np.nan)
    result["up"] = up
    result["down"] = down
    result["ht_line"] = np.where(result["trend"] == 0, up, down)

    prev_trend_series = result["trend"].shift(1)
    result["buy_signal"] = (result["trend"] == 0) & (prev_trend_series == 1)
    result["sell_signal"] = (result["trend"] == 1) & (prev_trend_series == 0)

    dist = result["atr2"] * base_risk_mult
    result["entry"] = np.nan
    result["stop_loss"] = np.nan
    result["target1"] = np.nan
    result["target2"] = np.nan
    result["target3"] = np.nan

    long_rows = result["buy_signal"]
    result.loc[long_rows, "entry"] = close[long_rows]
    result.loc[long_rows, "stop_loss"] = close[long_rows] - dist[long_rows]
    result.loc[long_rows, "target1"] = close[long_rows] + dist[long_rows]
    result.loc[long_rows, "target2"] = close[long_rows] + dist[long_rows] * 2
    result.loc[long_rows, "target3"] = close[long_rows] + dist[long_rows] * 3

    short_rows = result["sell_signal"]
    result.loc[short_rows, "entry"] = close[short_rows]
    result.loc[short_rows, "stop_loss"] = close[short_rows] + dist[short_rows]
    result.loc[short_rows, "target1"] = close[short_rows] - dist[short_rows]
    result.loc[short_rows, "target2"] = close[short_rows] - dist[short_rows] * 2
    result.loc[short_rows, "target3"] = close[short_rows] - dist[short_rows] * 3

    return result


def risk_reward_ratios(entry, stop_loss, target1, target2, target3):
    """R:R = |target - entry| / |stopLoss - entry| per target (CLAUDE.md section 5).

    By construction (targets are 1x/2x/3x the stop distance from entry)
    this should always come out to ~1.0/2.0/3.0 -- computing it explicitly
    rather than hardcoding those labels is a correctness check on the
    target math itself, not just a display value.
    """
    stop_distance = abs(stop_loss - entry)
    return {
        "target1": abs(target1 - entry) / stop_distance,
        "target2": abs(target2 - entry) / stop_distance,
        "target3": abs(target3 - entry) / stop_distance,
    }


def atr_volatility_label(atr_series, window=50, band=0.10):
    """'below-average' / 'normal' / 'above-average', by comparing the latest
    raw ATR value to its own recent rolling average (CLAUDE.md section 5) --
    a simple, honest gut-check, not a volatility model. Deliberately not
    more sophisticated than this: see CLAUDE.md section 7 on not overselling
    its precision.

    Uses a +/-`band` (default 10%) tolerance around the trailing `window`-bar
    mean. If fewer than `window` bars are available, uses whatever history
    there is rather than raising -- this label degrades gracefully, it isn't
    part of the signal/risk math itself.
    """
    atr_series = atr_series.dropna()
    if atr_series.empty:
        raise ValueError("no ATR history available")

    available = min(window, len(atr_series))
    baseline = atr_series.iloc[-available:].mean()
    current = atr_series.iloc[-1]
    if baseline == 0:
        return "normal"

    ratio = current / baseline
    if ratio < 1 - band:
        return "below-average"
    if ratio > 1 + band:
        return "above-average"
    return "normal"


def latest_signal(
    symbol, timeframe, df, amplitude=20, channel_deviation=2.0, base_risk_mult=3.0, atr_window=50
):
    """Check whether the most recent (last row) closed candle in `df` is a signal.

    Returns a dict with keys: symbol, timeframe, signal_time, direction
    ("LONG" | "SHORT" | None), entry, stop_loss, target1-3, atr (the raw
    ATR value, i.e. atr2 * 2), atr_label, risk_reward (dict of target1-3
    ratios, or None when direction is None). entry/stop_loss/targets/atr/
    atr_label are populated from the HalfTrend baseline context even when
    direction is None, so callers always have current volatility context
    available.
    """
    result = compute_halftrend(df, amplitude, channel_deviation, base_risk_mult)
    last = result.iloc[-1]

    if bool(last["buy_signal"]):
        direction = "LONG"
    elif bool(last["sell_signal"]):
        direction = "SHORT"
    else:
        direction = None

    signal = {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal_time": result.index[-1],
        "direction": direction,
        "entry": last["entry"] if direction else None,
        "stop_loss": last["stop_loss"] if direction else None,
        "target1": last["target1"] if direction else None,
        "target2": last["target2"] if direction else None,
        "target3": last["target3"] if direction else None,
        "atr": last["atr2"] * 2,
        "atr_label": atr_volatility_label(result["atr2"] * 2, window=atr_window),
        "risk_reward": None,
    }

    if direction:
        signal["risk_reward"] = risk_reward_ratios(
            signal["entry"],
            signal["stop_loss"],
            signal["target1"],
            signal["target2"],
            signal["target3"],
        )

    return signal
