from datetime import date

import pytest

from app.realized import Operation
from app.returns import compute_returns, xirr

ENVELOPES = {"PEA Boursorama": "PEA", "CTO Trade Republic": "CTO"}
TODAY = date(2026, 1, 1)


def op(day, account, kind, ticker, qty, gross, fees=0.0):
    net = gross + fees if kind == "Achat" else gross - fees
    return Operation(date.fromisoformat(day), account, kind, ticker, qty, gross, fees, 0.0, net)


def test_xirr_single_investment():
    # 1 000 € devenus 1 100 € en exactement un an : 10 % par an
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 1100)]) == pytest.approx(0.10, abs=1e-6)


def test_xirr_accounts_for_timing_of_contributions():
    # 1 000 € il y a un an, 1 000 € il y a six mois, 2 100 € aujourd'hui
    rate = xirr([(date(2025, 1, 1), -1000), (date(2025, 7, 2), -1000), (date(2026, 1, 1), 2100)])
    assert rate == pytest.approx(0.0667, abs=1e-3)  # nettement plus que les 5 % de gain / investi


def test_xirr_undefined_cases():
    assert xirr([(date(2025, 1, 1), -1000)]) is None  # aucun flux positif
    assert xirr([(date(2025, 1, 1), -1000), (date(2025, 1, 1), 1100)]) is None  # durée nulle


def test_total_envelope_and_position_returns():
    ops = [
        op("2025-01-01", "PEA Boursorama", "Achat", "AAA", 10, 1000.0),
        op("2025-01-01", "CTO Trade Republic", "Achat", "BBB", 5, 500.0),
        op("2025-07-02", "CTO Trade Republic", "Dividende", "BBB", 5, 20.0),
    ]
    result = compute_returns(ops, ENVELOPES, {"AAA": 110.0, "BBB": 100.0}, TODAY)
    pea, cto = result["envelopes"]["PEA"], result["envelopes"]["CTO"]
    assert pea["value"] == 1100.0 and pea["gain"] == 100.0
    assert pea["xirr"] == pytest.approx(0.10, abs=1e-6)
    assert pea["period_return"] == pytest.approx(0.10, abs=1e-6)  # un an pile : annualisé = période
    assert cto["gain"] == 20.0 and cto["dividends"] == 20.0  # dividendes compris dans le gain total
    assert result["positions"]["BBB"]["xirr"] > 0
    assert result["total"]["gain"] == 120.0 and result["total"]["bought"] == 1500.0


def test_same_ticker_on_two_envelopes_valued_separately():
    ops = [
        op("2025-01-01", "PEA Boursorama", "Achat", "AAA", 2, 200.0),
        op("2025-01-01", "CTO Trade Republic", "Achat", "AAA", 1, 100.0),
    ]
    result = compute_returns(ops, ENVELOPES, {"AAA": 150.0}, TODAY)
    assert result["envelopes"]["PEA"]["value"] == 300.0
    assert result["envelopes"]["CTO"]["value"] == 150.0
    assert result["positions"]["AAA"]["value"] == 450.0


def test_fully_sold_position_and_missing_price():
    ops = [
        op("2025-01-01", "CTO Trade Republic", "Achat", "AAA", 1, 100.0),
        op("2025-06-01", "CTO Trade Republic", "Vente", "AAA", 1, 120.0),
        op("2025-01-01", "PEA Boursorama", "Achat", "ZZZ", 1, 50.0),
    ]
    result = compute_returns(ops, ENVELOPES, {"ZZZ": None}, TODAY)
    assert result["positions"]["AAA"]["gain"] == 20.0 and result["positions"]["AAA"]["value"] == 0.0
    assert result["positions"]["ZZZ"]["incomplete"] is True
    assert result["total"]["incomplete"] is True
