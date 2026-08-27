import pytest

from src.position_sizing import position_size_matrix


def _lot_size(matrix, account_size, risk_percent):
    for account in matrix["accounts"]:
        if account["account_size"] == account_size:
            for risk in account["risks"]:
                if risk["risk_percent"] == risk_percent:
                    return risk["lot_size"]
    raise AssertionError(f"no row for account={account_size} risk={risk_percent}")


@pytest.mark.parametrize(
    "symbol,entry,stop_loss,account_size,risk_percent,expected_lot",
    [
        ("EURUSD", 1.0842, 1.0821, 6000, 0.5, 0.14),
        ("EURUSD", 1.0842, 1.0821, 25000, 1, 1.19),
        ("XAUUSD", 4602.30, 4608.10, 6000, 0.5, 0.05),
        ("XAUUSD", 4602.30, 4608.10, 25000, 1, 0.43),
        # GBPUSD / AUDUSD are USD-quoted majors -- identical pip math to
        # EURUSD, so the same 21-pip stop gives the same lot sizes.
        ("GBPUSD", 1.0842, 1.0821, 6000, 0.5, 0.14),
        ("GBPUSD", 1.0842, 1.0821, 25000, 1, 1.19),
        ("AUDUSD", 1.0842, 1.0821, 6000, 0.5, 0.14),
        ("AUDUSD", 1.0842, 1.0821, 25000, 1, 1.19),
    ],
)
def test_worked_examples_from_spec(
    monkeypatch, symbol, entry, stop_loss, account_size, risk_percent, expected_lot
):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,10000,25000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,0.75,1")

    matrix = position_size_matrix(symbol, entry, stop_loss)

    assert _lot_size(matrix, account_size, risk_percent) == pytest.approx(expected_lot)


def test_matrix_covers_every_configured_account_and_risk(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,10000,25000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,0.75,1")

    matrix = position_size_matrix("EURUSD", 1.0842, 1.0821)

    assert [a["account_size"] for a in matrix["accounts"]] == [6000, 10000, 25000]
    for account in matrix["accounts"]:
        assert [r["risk_percent"] for r in account["risks"]] == [0.5, 0.75, 1]


def test_adding_a_fourth_account_or_risk_level_requires_no_code_change(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000,10000,25000,50000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5,0.75,1,1.5")

    matrix = position_size_matrix("EURUSD", 1.0842, 1.0821)

    assert len(matrix["accounts"]) == 4
    assert len(matrix["accounts"][0]["risks"]) == 4
    assert matrix["accounts"][3]["account_size"] == 50000
    assert matrix["accounts"][0]["risks"][3]["risk_percent"] == 1.5


def test_defaults_match_spec_when_env_unset(monkeypatch):
    monkeypatch.delenv("ACCOUNT_SIZES", raising=False)
    monkeypatch.delenv("RISK_PERCENTAGES", raising=False)

    matrix = position_size_matrix("EURUSD", 1.0842, 1.0821)

    assert matrix["account_sizes"] == [6000.0, 10000.0, 25000.0]
    assert matrix["risk_percentages"] == [0.5, 0.75, 1.0]


def test_stop_loss_distance_reported_in_correct_units(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5")

    eurusd = position_size_matrix("EURUSD", 1.0842, 1.0821)
    xauusd = position_size_matrix("XAUUSD", 4602.30, 4608.10)

    assert eurusd["stop_loss_distance"] == pytest.approx(21.0)  # pips
    assert xauusd["stop_loss_distance"] == pytest.approx(5.80)  # dollars


def test_zero_stop_distance_raises(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SIZES", "6000")
    monkeypatch.setenv("RISK_PERCENTAGES", "0.5")

    with pytest.raises(ValueError):
        position_size_matrix("EURUSD", 1.0842, 1.0842)


def test_unknown_symbol_raises():
    with pytest.raises(ValueError):
        position_size_matrix("USDJPY", 155.20, 155.00)
