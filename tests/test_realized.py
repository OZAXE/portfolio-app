from datetime import date

import pytest

from app.realized import Operation, compute_realized, dividend_tax, treaty_credit

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
    # Seule la retenue américaine (15 %) a été prélevée : elle efface les 12,8 % d'impôt sur le revenu,
    # restent les prélèvements sociaux, 5,2 x 18,6 % = 0,97 en 2026 et 5 x 17,2 % = 0,86 en 2025
    assert years[2026]["envelopes"]["CTO"]["estimated_tax"] == pytest.approx(0.97)
    assert years[2025]["envelopes"]["CTO"]["estimated_tax"] == pytest.approx(0.86)
    assert years[2026]["envelopes"]["CTO"]["withheld_tax"] == pytest.approx(0.78)
    assert years[2026]["envelopes"]["CTO"]["foreign_withheld"] == pytest.approx(0.78)
    assert years[2026]["envelopes"]["PEA"]["dividends_gross"] == pytest.approx(6.0)


def test_impot_estime_deduit_les_retenues_trade_republic():
    # Dividende Applied Materials de l'export d'Evan : 0,47 € brut, 0,22 € retenus (15 % US + 31,4 % France).
    # Dû : 0,47 x 18,6 % = 0,087 ; prélevé en France 0,148 : 0,06 à récupérer, imputé sur l'impôt de la
    # plus-value (10 x 0,314 = 3,14) -> 3,08
    ops = [
        op("2026-01-10", "CTO Trade Republic", "Achat", "AMAT", 1, 100.0),
        op("2026-09-10", "CTO Trade Republic", "Dividende", "AMAT", 1, 0.47, taxes=0.22),
        op("2026-09-20", "CTO Trade Republic", "Vente", "AMAT", 1, 110.0),
    ]
    cto = compute_realized(ops, ENVELOPES)["years"][0]["envelopes"]["CTO"]
    assert cto["estimated_tax"] == pytest.approx(3.08)
    assert cto["withheld_tax"] == pytest.approx(0.22)
    assert cto["foreign_withheld"] == pytest.approx(0.07)


@pytest.mark.parametrize("withheld, french, foreign, remaining", [
    # 100 € de dividende américain en 2026 (convention : 15 %, dû = 18,6 % de prélèvements sociaux)
    (46.4, 31.4, 15.0, -12.8),  # Trade Republic : 15 % + 31,4 % -> acompte de 12,8 % à récupérer
    (46.4 - 12.8, 18.6, 15.0, 0.0),  # courtier français avec dispense d'acompte : rien à payer
    (15.0, 0.0, 15.0, 18.6),  # courtier étranger : prélèvements sociaux à payer
    (35.0 + 31.4, 31.4, 35.0, -12.8),  # retenue plus forte (Suisse) : l'excédent se réclame à l'étranger
])
def test_dividend_tax_trois_regimes_de_prelevement(withheld, french, foreign, remaining):
    tax = dividend_tax(100.0, withheld, 0.15, 2026)
    assert (tax["french"], tax["foreign"], tax["remaining"]) == pytest.approx((french, foreign, remaining))


def test_dividend_tax_sans_retenue_etrangere():
    # Rolls-Royce (Royaume-Uni, pas de retenue) : 31,4 % prélevés en France, tout est réglé
    assert dividend_tax(100.0, 31.4, treaty_credit("RR.L"), 2026)["remaining"] == pytest.approx(0.0)
    # Japon, convention à 10 % : il reste 2,8 % d'impôt sur le revenu + 18,6 %
    assert dividend_tax(100.0, 10.0, treaty_credit("7203.T"), 2026)["remaining"] == pytest.approx(21.4)
    # ETF irlandais coté à Paris : aucune retenue étrangère, pas de crédit
    assert treaty_credit("CW8.PA", "ETF") == 0.0 and treaty_credit("VOO", "ETF") == 0.15


def test_same_day_buy_before_sell():
    ops = [
        op("2025-01-10", "CTO Trade Republic", "Vente", "AAA", 1, 12.0),
        op("2025-01-10", "CTO Trade Republic", "Achat", "AAA", 1, 10.0),
    ]
    sale = compute_realized(ops, ENVELOPES)["years"][0]["sales"][0]
    assert sale["gain"] == pytest.approx(2.0)
