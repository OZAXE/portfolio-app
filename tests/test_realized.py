from datetime import date

import pytest

from app.realized import Operation, compute_realized

ENVELOPES = {"PEA Boursorama": "PEA", "CTO Trade Republic": "CTO"}


def op(day, account, kind, ticker, qty, gross, fees=0.0, taxes=0.0):
    net = gross + fees + taxes if kind == "Achat" else gross - fees - taxes
    return Operation(date.fromisoformat(day), account, kind, ticker, qty, gross, fees, taxes, net)


def test_weighted_average_cost_and_gain():
    ops = [
        op("2025-01-10", "CTO Trade Republic", "Achat", "AAA", 10, 100.0, fees=1.0),  # 10,10 € / action
        op("2025-03-10", "CTO Trade Republic", "Achat", "AAA", 10, 200.0, fees=1.0),  # PRU -> 15,10 €
        op("2025-06-10", "CTO Trade Republic", "Vente", "AAA", 5, 100.0, fees=1.0),   # encaissé 99 €
        op("2025-09-10", "CTO Trade Republic", "Vente", "AAA", 5, 50.0),              # PRU inchangé
    ]
    year = compute_realized(ops, ENVELOPES)["years"][0]
    sales = sorted(year["sales"], key=lambda s: s["date"])
    assert sales[0]["unit_cost"] == pytest.approx(15.10)
    assert sales[0]["gain"] == pytest.approx(99.0 - 75.5)
    assert sales[1]["gain"] == pytest.approx(50.0 - 75.5)
    cto = year["envelopes"]["CTO"]
    assert cto["realized_gain"] == pytest.approx(-2.0)
    assert cto["estimated_tax"] == 0.0  # moins-value nette : pas d'impôt estimé sur les plus-values


def test_cost_tracked_per_account():
    # Même titre sur deux comptes : chacun son PRU
    ops = [
        op("2025-01-10", "PEA Boursorama", "Achat", "AAA", 1, 10.0),
        op("2025-01-10", "CTO Trade Republic", "Achat", "AAA", 1, 20.0),
        op("2025-02-10", "PEA Boursorama", "Vente", "AAA", 1, 15.0),
    ]
    year = compute_realized(ops, ENVELOPES)["years"][0]
    assert year["envelopes"]["PEA"]["realized_gain"] == pytest.approx(5.0)
    assert "estimated_tax" not in year["envelopes"]["PEA"]  # pas d'impôt tant qu'on ne retire rien du PEA


def test_dividends_by_year_and_cto_tax_estimate():
    ops = [
        op("2025-05-02", "CTO Trade Republic", "Dividende", "KO", 10, 5.0, taxes=0.75),
        op("2026-05-02", "CTO Trade Republic", "Dividende", "KO", 10, 5.2, taxes=0.78),
        op("2026-06-01", "PEA Boursorama", "Dividende", "TTE.PA", 7, 6.0),
    ]
    years = {y["year"]: y for y in compute_realized(ops, ENVELOPES)["years"]}
    assert list(years) == [2026, 2025]
    assert years[2026]["envelopes"]["CTO"]["dividends_net"] == pytest.approx(4.42)
    # PFU 31,4 % depuis 2026, moins la retenue américaine déjà prélevée : 5,2 x 0,314 - 0,78 = 0,85
    assert years[2026]["envelopes"]["CTO"]["estimated_tax"] == pytest.approx(0.85)
    assert years[2025]["envelopes"]["CTO"]["estimated_tax"] == pytest.approx(5.0 * 0.30 - 0.75)
    assert years[2026]["envelopes"]["CTO"]["withheld_tax"] == pytest.approx(0.78)
    assert years[2026]["envelopes"]["PEA"]["dividends_gross"] == pytest.approx(6.0)


def test_impot_estime_deduit_les_retenues_trade_republic():
    # Dividende Applied Materials de l'export d'Evan : 0,47 € brut, 0,22 € retenus (15 % US + 31,4 % France).
    # 0,47 x 0,314 = 0,15 < 0,22 : rien à ajouter ; il reste l'impôt sur la plus-value (10 x 0,314 = 3,14)
    ops = [
        op("2026-01-10", "CTO Trade Republic", "Achat", "AMAT", 1, 100.0),
        op("2026-09-10", "CTO Trade Republic", "Dividende", "AMAT", 1, 0.47, taxes=0.22),
        op("2026-09-20", "CTO Trade Republic", "Vente", "AMAT", 1, 110.0),
    ]
    cto = compute_realized(ops, ENVELOPES)["years"][0]["envelopes"]["CTO"]
    assert cto["estimated_tax"] == pytest.approx(3.14)
    assert cto["withheld_tax"] == pytest.approx(0.22)


def test_same_day_buy_before_sell():
    ops = [
        op("2025-01-10", "CTO Trade Republic", "Vente", "AAA", 1, 12.0),
        op("2025-01-10", "CTO Trade Republic", "Achat", "AAA", 1, 10.0),
    ]
    sale = compute_realized(ops, ENVELOPES)["years"][0]["sales"][0]
    assert sale["gain"] == pytest.approx(2.0)
