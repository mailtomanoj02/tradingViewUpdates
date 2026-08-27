"""Asia Sweep Reversals strategy engine (CLAUDE.md section 14).

Port of reference/asia_sweep_source.pine's SIGNAL LOGIC ONLY -- the Asia
session range, the range sweep, internal market structure (pivots +
BOS/CHoCH + internalTrend), the trend-EMA filter, the CHoCH entry setup,
and the one-trade-at-a-time active-trade gating. The visualization parts
of the script (boxes, lines, labels, the EMA plot, alertcondition wiring)
are deliberately not ported.

Like src/halftrend.py this is symbol/timeframe agnostic: it runs on any
OHLC DataFrame of confirmed/closed candles, ascending by time, with a
tz-aware DatetimeIndex.

Faithful-to-the-script quirks (do NOT "fix" these -- see the porting
notes at the bottom of the .pine file):
  * The SHORT entry gates on `internal_low` being inside the Asia range
    while the stop is placed at `internal_high`; LONG mirrors it.
  * `internal_trend` (0 / 1 / -1) is genuine bar-to-bar loop state.
  * `max_bars_after_sweep` is counted from the BREAKOUT bar.
  * Active-trade gating uses the Pine single 2R take-profit
    (`reward_rr`) as the "position closed" trigger, so a new entry
    frees up on exactly the same bar TradingView's marker would --
    even though the ALERT reports a 1R/2R/3R ladder (per the user's
    spec, CLAUDE.md section 14).
"""

import math
import os
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .halftrend import atr_volatility_label, risk_reward_ratios, wilder_atr

DEFAULT_SESSION = "1900-0400"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_INTERNAL_LENGTH = 2
DEFAULT_BREAK_MODE = "Close"
DEFAULT_MAX_BARS_AFTER_SWEEP = 10
DEFAULT_STOP_BUFFER_TICKS = 0
# Pine's own default for "Enable trend filter" is TRUE, but this deployment
# defaults it OFF -- verified against the user's chart (the EURUSD SHORT in
# their screenshot, ~09:34 NY on 2026-08-27, only forms with the filter
# off). A 200-EMA "only short below / long above" filter on 1m suppresses
# this counter-trend Asia-sweep setup almost entirely (a bearish CHoCH
# right after a bullish Asia-high breakout is nearly always still above the
# EMA). Set ASIA_SWEEP_TREND_FILTER=true to restore the Pine default.
DEFAULT_TREND_FILTER = "false"
DEFAULT_TREND_EMA_LENGTH = 200
DEFAULT_TARGET_MULTIPLES = "1,2,3"
DEFAULT_REWARD_RR = 2.0

# syminfo.mintick per instrument (used only for the optional stop buffer).
MINTICK = {"EURUSD": 1e-5, "GBPUSD": 1e-5, "AUDUSD": 1e-5, "XAUUSD": 0.01}

NAN = float("nan")


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _env(symbol, key, default):
    """`{SYMBOL}_{key}` overrides `{key}` overrides `default` -- empty-string
    safe (a GitHub Actions workflow referencing a never-added secret sets
    the var to "" rather than leaving it absent).
    """
    prefix = symbol.upper()
    return os.environ.get(f"{prefix}_{key}") or os.environ.get(key) or default


def asia_sweep_params(symbol):
    """Per-instrument Asia Sweep parameters, overridable via env vars
    (global `ASIA_SWEEP_*` or per-symbol `{SYMBOL}_ASIA_SWEEP_*`).
    """
    trend_filter_raw = str(_env(symbol, "ASIA_SWEEP_TREND_FILTER", DEFAULT_TREND_FILTER)).strip().lower()
    return {
        "session_str": _env(symbol, "ASIA_SWEEP_SESSION", DEFAULT_SESSION),
        "timezone": _env(symbol, "ASIA_SWEEP_TIMEZONE", DEFAULT_TIMEZONE),
        "internal_length": int(_env(symbol, "ASIA_SWEEP_INTERNAL_LENGTH", DEFAULT_INTERNAL_LENGTH)),
        "break_mode": _env(symbol, "ASIA_SWEEP_BREAK_MODE", DEFAULT_BREAK_MODE),
        "max_bars_after_sweep": int(
            _env(symbol, "ASIA_SWEEP_MAX_BARS_AFTER_SWEEP", DEFAULT_MAX_BARS_AFTER_SWEEP)
        ),
        "stop_buffer_ticks": int(_env(symbol, "ASIA_SWEEP_STOP_BUFFER_TICKS", DEFAULT_STOP_BUFFER_TICKS)),
        "trend_filter": trend_filter_raw not in ("false", "0", "no", ""),
        "trend_ema_length": int(_env(symbol, "ASIA_SWEEP_TREND_EMA_LENGTH", DEFAULT_TREND_EMA_LENGTH)),
        "target_multiples": [
            float(x) for x in str(_env(symbol, "ASIA_SWEEP_TARGET_MULTIPLES", DEFAULT_TARGET_MULTIPLES)).split(",")
        ],
        "reward_rr": float(_env(symbol, "ASIA_SWEEP_REWARD_RR", DEFAULT_REWARD_RR)),
        "mintick": MINTICK.get(symbol.upper(), 1e-5),
    }


def _session_bounds_minutes(session_str):
    start_s, end_s = session_str.split("-")
    start = int(start_s[:2]) * 60 + int(start_s[2:])
    end = int(end_s[:2]) * 60 + int(end_s[2:])
    return start, end


def _in_session_mask(index, session_str, timezone):
    local = index.tz_convert(ZoneInfo(timezone))
    tod = local.hour * 60 + local.minute
    tod = np.asarray(tod)
    start, end = _session_bounds_minutes(session_str)
    if start <= end:
        return (tod >= start) & (tod < end)
    return (tod >= start) | (tod < end)


def _pivot_confirmations(values, length):
    """For each bar i, the pivot value confirmed at i (i.e. the local
    extreme `length` bars back), or NaN. A pivot high is the strict,
    unique maximum of the (2*length+1)-bar window centred `length` bars
    back; pivot low is the strict unique minimum. Ties produce no pivot
    (matches TradingView's ta.pivothigh / ta.pivotlow on flat extremes).
    """
    n = len(values)
    highs = np.full(n, NAN)
    lows = np.full(n, NAN)
    for p in range(length, n - length):
        window = values[p - length : p + length + 1]
        centre = values[p]
        if centre == window.max() and np.count_nonzero(window == centre) == 1:
            highs[p + length] = centre
        if centre == window.min() and np.count_nonzero(window == centre) == 1:
            lows[p + length] = centre
    return highs, lows


def compute_asia_sweep(
    df,
    session_str=DEFAULT_SESSION,
    timezone=DEFAULT_TIMEZONE,
    internal_length=DEFAULT_INTERNAL_LENGTH,
    break_mode=DEFAULT_BREAK_MODE,
    max_bars_after_sweep=DEFAULT_MAX_BARS_AFTER_SWEEP,
    stop_buffer_ticks=DEFAULT_STOP_BUFFER_TICKS,
    trend_filter=False,
    trend_ema_length=DEFAULT_TREND_EMA_LENGTH,
    target_multiples=(1.0, 2.0, 3.0),
    reward_rr=DEFAULT_REWARD_RR,
    mintick=1e-5,
    close_trade_on_new_session=True,
):
    """Run the Asia Sweep engine forward over `df` (open/high/low/close,
    ascending, tz-aware index, closed candles only).

    Returns a copy of `df` with added columns: in_session, session_high,
    session_low, session_mid, session_start, high_sweep, low_sweep,
    long_entry, short_entry, and on entry rows entry/stop_loss/
    target1/target2/target3.
    """
    result = df.copy()
    n = len(result)

    open_ = result["open"].to_numpy(dtype=float)
    high = result["high"].to_numpy(dtype=float)
    low = result["low"].to_numpy(dtype=float)
    close = result["close"].to_numpy(dtype=float)

    in_session = _in_session_mask(result.index, session_str, timezone)
    session_begins = np.zeros(n, dtype=bool)
    session_begins[1:] = in_session[1:] & ~in_session[:-1]
    session_begins[0] = bool(in_session[0])

    wick_mode = break_mode.strip().lower() == "wick"
    ema = pd.Series(close).ewm(span=trend_ema_length, adjust=False).mean().to_numpy()
    pivot_high_conf, _ = _pivot_confirmations(high, internal_length)
    _, pivot_low_conf = _pivot_confirmations(low, internal_length)

    mults = [float(m) for m in target_multiples]

    # --- output arrays ---
    out_session_high = np.full(n, NAN)
    out_session_low = np.full(n, NAN)
    out_high_sweep = np.zeros(n, dtype=bool)
    out_low_sweep = np.zeros(n, dtype=bool)
    out_long_entry = np.zeros(n, dtype=bool)
    out_short_entry = np.zeros(n, dtype=bool)
    out_entry = np.full(n, NAN)
    out_stop = np.full(n, NAN)
    out_t1 = np.full(n, NAN)
    out_t2 = np.full(n, NAN)
    out_t3 = np.full(n, NAN)
    out_session_start = [pd.NaT] * n

    # --- carried state (Pine `var`) ---
    session_high = NAN
    session_low = NAN
    session_start = pd.NaT
    internal_high = NAN
    internal_low = NAN
    internal_high_bar = -1
    internal_low_bar = -1
    internal_high_broken = False
    internal_low_broken = False
    internal_trend = 0
    asia_high_broken = False
    asia_low_broken = False
    high_sweep_marked = False
    low_sweep_marked = False
    short_setup_armed = False
    long_setup_armed = False
    asia_high_break_bar = -1
    asia_low_break_bar = -1
    active_dir = 0
    active_stop = NAN
    active_target_gate = NAN

    L = internal_length

    for i in range(n):
        # --- session range logic ---
        if session_begins[i]:
            if close_trade_on_new_session and active_dir != 0:
                active_dir = 0
                active_stop = NAN
                active_target_gate = NAN
            asia_high_broken = False
            asia_low_broken = False
            high_sweep_marked = False
            low_sweep_marked = False
            short_setup_armed = False
            long_setup_armed = False
            asia_high_break_bar = -1
            asia_low_break_bar = -1
            session_high = high[i]
            session_low = low[i]
            session_start = result.index[i]
        elif in_session[i] and not _isnan(session_high):
            session_high = max(session_high, high[i])
            session_low = min(session_low, low[i])
        # else: carry the finished session levels forward unchanged

        out_session_high[i] = session_high
        out_session_low[i] = session_low
        out_session_start[i] = session_start

        prev_high = high[i - 1] if i > 0 else high[i]
        prev_low = low[i - 1] if i > 0 else low[i]
        not_in_session = not in_session[i]
        have_session = not _isnan(session_high)

        # --- Asia breakout (arms the CHoCH entry sequence) ---
        if not_in_session and have_session and high[i] > session_high and not asia_high_broken:
            asia_high_broken = True
            short_setup_armed = True
            asia_high_break_bar = i
        if not_in_session and have_session and low[i] < session_low and not asia_low_broken:
            asia_low_broken = True
            long_setup_armed = True
            asia_low_break_bar = i

        # --- sweep signals (first wick past the completed level, once per session) ---
        if (
            not high_sweep_marked
            and have_session
            and not_in_session
            and high[i] > session_high
            and prev_high <= session_high
        ):
            out_high_sweep[i] = True
            high_sweep_marked = True
        if (
            not low_sweep_marked
            and have_session
            and not_in_session
            and low[i] < session_low
            and prev_low >= session_low
        ):
            out_low_sweep[i] = True
            low_sweep_marked = True

        # --- internal market structure ---
        if not math.isnan(pivot_high_conf[i]):
            internal_high = pivot_high_conf[i]
            internal_high_bar = i - L
            internal_high_broken = False
        if not math.isnan(pivot_low_conf[i]):
            internal_low = pivot_low_conf[i]
            internal_low_bar = i - L
            internal_low_broken = False

        bull_break_price = high[i] if wick_mode else close[i]
        bear_break_price = low[i] if wick_mode else close[i]
        bullish_internal_break = (
            not _isnan(internal_high) and not internal_high_broken and bull_break_price > internal_high
        )
        bearish_internal_break = (
            not _isnan(internal_low) and not internal_low_broken and bear_break_price < internal_low
        )
        bullish_choch = bullish_internal_break and internal_trend == -1
        bearish_choch = bearish_internal_break and internal_trend == 1

        if bullish_internal_break:
            internal_high_broken = True
            internal_trend = 1
        if bearish_internal_break:
            internal_low_broken = True
            internal_trend = -1

        # --- trend filter ---
        short_trend_allowed = (not trend_filter) or close[i] < ema[i]
        long_trend_allowed = (not trend_filter) or close[i] > ema[i]

        # --- active-trade management (stop prioritized on same-bar ambiguity) ---
        stop_loss_hit = False
        take_profit_hit = False
        if active_dir != 0:
            if active_dir == 1:
                stop_hit = low[i] <= active_stop
                target_hit = high[i] >= active_target_gate
            else:
                stop_hit = high[i] >= active_stop
                target_hit = low[i] <= active_target_gate
            stop_loss_hit = bool(stop_hit)
            take_profit_hit = bool(target_hit and not stop_hit)
            if stop_loss_hit or take_profit_hit:
                active_dir = 0
                active_stop = NAN
                active_target_gate = NAN

        # --- short CHoCH entry ---
        if (
            active_dir == 0
            and not stop_loss_hit
            and not take_profit_hit
            and short_setup_armed
            and i > asia_high_break_bar
            and i - asia_high_break_bar <= max_bars_after_sweep
            and bearish_choch
            and short_trend_allowed
            and not _isnan(internal_low)
            and session_low < internal_low < session_high
            and session_low < close[i] < session_high
        ):
            short_stop = internal_high + mintick * stop_buffer_ticks
            short_risk = short_stop - close[i]
            if short_risk > 0:
                active_dir = -1
                active_stop = short_stop
                active_target_gate = close[i] - short_risk * reward_rr
                out_short_entry[i] = True
                out_entry[i] = close[i]
                out_stop[i] = short_stop
                out_t1[i] = close[i] - short_risk * mults[0]
                out_t2[i] = close[i] - short_risk * mults[1]
                out_t3[i] = close[i] - short_risk * mults[2]
                short_setup_armed = False

        # --- long CHoCH entry ---
        if (
            active_dir == 0
            and not stop_loss_hit
            and not take_profit_hit
            and long_setup_armed
            and i > asia_low_break_bar
            and i - asia_low_break_bar <= max_bars_after_sweep
            and bullish_choch
            and long_trend_allowed
            and not _isnan(internal_high)
            and session_low < internal_high < session_high
            and session_low < close[i] < session_high
        ):
            long_stop = internal_low - mintick * stop_buffer_ticks
            long_risk = close[i] - long_stop
            if long_risk > 0:
                active_dir = 1
                active_stop = long_stop
                active_target_gate = close[i] + long_risk * reward_rr
                out_long_entry[i] = True
                out_entry[i] = close[i]
                out_stop[i] = long_stop
                out_t1[i] = close[i] + long_risk * mults[0]
                out_t2[i] = close[i] + long_risk * mults[1]
                out_t3[i] = close[i] + long_risk * mults[2]
                long_setup_armed = False

    result["in_session"] = in_session
    result["session_high"] = out_session_high
    result["session_low"] = out_session_low
    result["session_mid"] = (out_session_high + out_session_low) / 2.0
    result["session_start"] = out_session_start
    result["high_sweep"] = out_high_sweep
    result["low_sweep"] = out_low_sweep
    result["long_entry"] = out_long_entry
    result["short_entry"] = out_short_entry
    result["entry"] = out_entry
    result["stop_loss"] = out_stop
    result["target1"] = out_t1
    result["target2"] = out_t2
    result["target3"] = out_t3
    return result


def latest_events(symbol, timeframe, df, **params):
    """Inspect the LAST closed bar of `df` for a sweep and/or an entry.

    Returns:
        {
            "symbol", "timeframe", "bar_time",
            "sweep": None | {
                "side": "HIGH" | "LOW", "swept_level",
                "session_high", "session_low", "session_mid",
                "session_start", "session_date",
            },
            "entry": None | {
                "direction": "LONG" | "SHORT",
                "entry", "stop_loss", "target1", "target2", "target3",
                "risk_reward": {target1..3: ratio},
                "atr", "atr_label",
            },
        }
    """
    engine_keys = {
        "session_str", "timezone", "internal_length", "break_mode", "max_bars_after_sweep",
        "stop_buffer_ticks", "trend_filter", "trend_ema_length", "target_multiples",
        "reward_rr", "mintick", "close_trade_on_new_session",
    }
    engine_params = {k: v for k, v in params.items() if k in engine_keys}
    result = compute_asia_sweep(df, **engine_params)
    last = result.iloc[-1]

    event = {
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_time": result.index[-1],
        "sweep": None,
        "entry": None,
    }

    if bool(last["high_sweep"]) or bool(last["low_sweep"]):
        side = "HIGH" if bool(last["high_sweep"]) else "LOW"
        session_start = last["session_start"]
        event["sweep"] = {
            "side": side,
            "swept_level": last["session_high"] if side == "HIGH" else last["session_low"],
            "session_high": last["session_high"],
            "session_low": last["session_low"],
            "session_mid": last["session_mid"],
            "session_start": session_start,
            "session_date": None if pd.isna(session_start) else session_start.date().isoformat(),
        }

    if bool(last["long_entry"]) or bool(last["short_entry"]):
        direction = "LONG" if bool(last["long_entry"]) else "SHORT"
        atr_series = wilder_atr(result["high"], result["low"], result["close"], length=100)
        event["entry"] = {
            "direction": direction,
            "entry": float(last["entry"]),
            "stop_loss": float(last["stop_loss"]),
            "target1": float(last["target1"]),
            "target2": float(last["target2"]),
            "target3": float(last["target3"]),
            "risk_reward": risk_reward_ratios(
                last["entry"], last["stop_loss"], last["target1"], last["target2"], last["target3"]
            ),
            "atr": float(atr_series.iloc[-1]),
            "atr_label": atr_volatility_label(atr_series),
        }

    return event
