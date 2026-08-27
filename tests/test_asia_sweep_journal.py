import pandas as pd
import pytest

from src.asia_sweep import compute_asia_sweep
from src.asia_sweep_journal import compute_asia_sweep_outcomes
from src.journal_log import append_daily_entry, trades_in_range
from src.trade_journal import aggregate_trades
from tests.test_asia_sweep import _df, _short_entry_scenario


def _resolved_short_scenario():
    df = _short_entry_scenario()
    # after the 09:15 SHORT (entry 1.1032, stop 1.1055, T1 1.1009 / T2 1.0986 / T3 1.0963),
    # walk price straight down through all three targets.
    tail = pd.DataFrame(
        [
            (1.1032, 1.1033, 1.1005, 1.1008),  # 09:16 -> T1
            (1.1008, 1.1009, 1.0980, 1.0982),  # 09:17 -> T2
            (1.0982, 1.0983, 1.0960, 1.0962),  # 09:18 -> T3 (close)
        ],
        columns=["open", "high", "low", "close"],
        index=pd.date_range("2026-08-25 09:16", periods=3, freq="1min", tz="UTC"),
    )
    return pd.concat([df, tail])


def _result():
    return compute_asia_sweep(
        _resolved_short_scenario(),
        session_str="0900-0910", timezone="UTC", internal_length=2,
        break_mode="Close", max_bars_after_sweep=10, trend_filter=False,
        target_multiples=(1.0, 2.0, 3.0), reward_rr=2.0, mintick=1e-5,
    )


def test_outcome_walker_classifies_a_full_tp3_run():
    trades = compute_asia_sweep_outcomes("EURUSD", "1m", _result())
    assert len(trades) == 1
    t = trades[0]
    assert t["direction"] == "SHORT"
    assert t["final_exit"] == "TP3"
    assert t["outcome"] == "TP3 (full target)"
    assert t["r_multiple"] == pytest.approx(3.0)
    assert t["close_time"] is not None


def test_outcome_walker_marks_unresolved_trades_open():
    # no downstream bars -> the trade never resolves
    trades = compute_asia_sweep_outcomes("EURUSD", "1m", _result().iloc[:26])
    assert len(trades) == 1
    assert trades[0]["r_multiple"] is None
    assert trades[0]["final_exit"] == "open"


def test_aggregate_and_persist_roundtrip(tmp_path):
    log = tmp_path / "asia_sweep_daily_log.json"
    trades = compute_asia_sweep_outcomes("EURUSD", "1m", _result())

    stats = aggregate_trades(trades)
    assert stats["total_closed"] == 1
    assert stats["r_total"] == pytest.approx(3.0)
    assert stats["win_rate"] == 100.0

    append_daily_entry("2026-08-25", "EURUSD", "1m", trades, path=str(log))
    append_daily_entry("2026-08-25", "EURUSD", "1m", trades, path=str(log))  # idempotent

    back = trades_in_range("EURUSD", "2026-08-25", "2026-08-25", path=str(log))
    assert len(back) == 1
    assert back[0]["r_multiple"] == pytest.approx(3.0)


def test_no_entries_gives_no_trades():
    flat = _df([(1.10, 1.10, 1.10, 1.10)] * 30, start="2026-08-25 08:00")
    result = compute_asia_sweep(flat, session_str="0900-0910", timezone="UTC", trend_filter=False)
    assert compute_asia_sweep_outcomes("EURUSD", "1m", result) == []
