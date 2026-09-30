from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.realized import Operation
from app.sheets import HistoryPoint
from app.stats import (Flow, _Lookup, compute_attribution, compute_periods, compute_risk, drawdown,
                       operation_flows, period_base, portfolio_stats, twr_index)

ENVELOPES = {"PEA Boursorama": "PEA", "CTO Trade Republic": "CTO"}


def op(day, account, kind, ticker, qty, net):
    return Operation(date.fromisoformat(day), account, kind, ticker, qty, net, 0.0, 0.0, net)


def d(iso):
    return date.fromisoformat(iso)


def test_twr_neutralise_un_apport():
    # 1 000 € achetés le 1er, +10 % le 2 (1 100 €) ; le 3, 1 100 € de plus investis et le titre perd 10 % :
    # 1 100 x 0,9 + 1 100 = 2 090 €. Rendements : +10 % puis -10 % -> TWR = 1,1 x 0,9 - 1 = -1 %,
    # alors que valeur / investi donnerait -0,5 % (2 090 / 2 100)
    series = [(d("2026-03-02"), 1000.0), (d("2026-03-03"), 1100.0), (d("2026-03-04"), 2090.0)]
    flows = [Flow(d("2026-03-04"), 1100.0, "PEA", "AAA")]
    points = twr_index(series, flows)
    assert points[1]["return"] == pytest.approx(0.10)
    assert points[2]["return"] == pytest.approx(-0.10)
    assert points[2]["index"] == pytest.approx(0.99)


def test_twr_dividende_compte_comme_gain():
    # Valeur inchangée à 1 000 € mais 20 € de dividende sortis du portefeuille : +2 %
    series = [(d("2026-03-02"), 1000.0), (d("2026-03-03"), 1000.0)]
    points = twr_index(series, [Flow(d("2026-03-03"), -20.0, "CTO", "AAA")])
    assert points[1]["return"] == pytest.approx(0.02)


def test_twr_ignore_le_jour_qui_suit_une_valeur_nulle():
    # Tout vendu (valeur 0), puis rachat de 500 € : pas de rendement infini ce jour-là
    series = [(d("2026-03-02"), 1000.0), (d("2026-03-03"), 0.0), (d("2026-03-04"), 500.0)]
    flows = [Flow(d("2026-03-03"), -1000.0, "PEA", "AAA"), Flow(d("2026-03-04"), 500.0, "PEA", "AAA")]
    points = twr_index(series, flows)
    assert points[1]["return"] == pytest.approx(0.0)
    assert points[2]["return"] is None and points[2]["index"] == pytest.approx(1.0)


def test_dates_de_reference_des_periodes():
    today = d("2026-03-31")
    assert period_base("1m", today) == d("2026-02-28")  # pas de 31 février
    assert period_base("ytd", today) == d("2025-12-31")
    assert period_base("1y", d("2028-02-29")) == d("2027-02-28")
    assert period_base("all", today) is None


def test_periodes_gain_en_euros_et_indice():
    # 31/12 : 1 000 € ; 15/01 : achat de 500 € ; 30/01 : 1 650 €. Depuis le 1er janvier :
    # gain = 1 650 - 1 000 - 500 = 150 € ; indice de 100 à 104 -> +4 %
    series = [(d("2025-12-31"), 1000.0), (d("2026-01-15"), 1600.0), (d("2026-01-30"), 1650.0)]
    flows = [Flow(d("2025-12-01"), 1000.0, "PEA", "AAA"), Flow(d("2026-01-15"), 500.0, "PEA", "AAA")]
    points = twr_index(series, [f for f in flows if f.day > series[0][0]])
    bench = _Lookup([(d("2025-12-31"), 100.0), (d("2026-01-29"), 104.0)])  # pas de cotation le 30
    periods = {p["key"]: p for p in compute_periods(points, flows, d("2026-01-30"), bench)}
    ytd = periods["ytd"]
    # Rendements : (1 600 - 500) / 1 000 - 1 = +10 %, puis 1 650 / 1 600 - 1 = +3,125 % -> +13,4375 %
    assert ytd["twr"] == pytest.approx(1.1 * 1.03125 - 1)
    assert ytd["gain"] == pytest.approx(150.0)
    assert ytd["benchmark"] == pytest.approx(0.04)
    assert ytd["annualized"] is None  # moins d'un an : pas d'annualisation
    assert periods["1y"]["available"] is False  # l'historique commence après le 30/01/2025
    # Depuis le début : tout l'argent versé compte, 1 650 - 1 500 = 150 €
    assert periods["all"]["gain"] == pytest.approx(150.0)


def test_pire_baisse_et_retour_au_sommet():
    # 100 -> 120 -> 90 -> 130 : pire baisse 90 / 120 - 1 = -25 %, sommet regagné le 4e jour
    series = [(d("2026-01-01"), 100.0), (d("2026-01-02"), 120.0), (d("2026-01-03"), 90.0), (d("2026-01-04"), 130.0)]
    dd = drawdown(series)
    assert dd["max"] == pytest.approx(-0.25)
    assert (dd["peak"], dd["trough"], dd["recovered"]) == ("2026-01-02", "2026-01-03", "2026-01-04")
    assert dd["current"] == 0.0


def _alternating(n, start=d("2026-01-01")):
    """n rendements quotidiens de +1 % et -1 % en alternance, un par jour calendaire."""
    series, value = [(start, 100.0)], 100.0
    for i in range(n):
        value *= 1.01 if i % 2 == 0 else 0.99
        series.append((start + timedelta(days=i + 1), value))
    return series


def test_volatilite_et_beta():
    # 60 rendements de ±1 % : écart-type = 0,01 x racine(60 / 59), annualisé x racine(252) = 16,01 %
    series = _alternating(60)
    points = twr_index(series, [])
    today = series[-1][0]
    # Indice qui fait la moitié des mouvements du portefeuille : bêta de 2
    bench_series, value = [(series[0][0], 100.0)], 100.0
    for i in range(60):
        value *= 1.005 if i % 2 == 0 else 0.995
        bench_series.append((series[i + 1][0], value))
    risk = compute_risk(points, today, _Lookup(bench_series))
    assert risk["volatility"] == pytest.approx(0.01 * (60 / 59) ** 0.5 * 252 ** 0.5, rel=1e-4)
    assert risk["beta"] == pytest.approx(2.0, rel=1e-3)
    assert risk["sharpe"] is None  # 60 jours d'historique : moins de 6 mois


def test_risque_non_calcule_sur_trop_peu_de_jours():
    points = twr_index(_alternating(20), [])
    risk = compute_risk(points, d("2026-01-21"), None)
    assert risk["volatility"] is None and risk["daily_returns"] == 20


def test_contribution_par_ligne():
    # Au 31/12/2025 : 10 AAA à 100 € (1 000 €). 2026 : dividende AAA de 20 € le 01/06, achat de BBB pour
    # 500 € le 02/07. Au 31/12/2026 : AAA vaut 1 100 €, BBB 450 €.
    # Gains : AAA = 1 100 - 1 000 + 20 = 120 € ; BBB = 450 - 500 = -50 €.
    # Capital moyen (Dietz) : 1 000 - 20 x 213/365 + 500 x 182/365 = 1 237,64 € -> AAA +9,70 points
    ops = [op("2025-03-01", "PEA Boursorama", "Achat", "AAA", 10, 800.0),
           op("2026-06-01", "PEA Boursorama", "Dividende", "AAA", 10, 20.0),
           op("2026-07-02", "CTO Trade Republic", "Achat", "BBB", 5, 500.0)]
    closes = {"AAA": _Lookup([(d("2025-12-30"), 100.0)])}
    current = {("PEA", "AAA"): 1100.0, ("CTO", "BBB"): 450.0}
    result = compute_attribution(ops, ENVELOPES, current, closes, d("2025-12-31"), d("2026-12-31"), {"AAA": "Alpha"})
    lines = {r["ticker"]: r for r in result["lines"]}
    assert lines["AAA"]["gain"] == pytest.approx(120.0) and lines["AAA"]["name"] == "Alpha"
    assert lines["BBB"]["gain"] == pytest.approx(-50.0)
    capital = 1000 - 20 * 213 / 365 + 500 * 182 / 365
    assert result["capital"] == pytest.approx(capital, abs=0.01)
    assert lines["AAA"]["points"] == pytest.approx(120 / capital, rel=1e-4)
    assert result["total"] == pytest.approx(70.0)
    assert result["missing"] == []


def test_contribution_signale_un_cours_manquant():
    ops = [op("2025-03-01", "PEA Boursorama", "Achat", "AAA", 10, 800.0)]
    result = compute_attribution(ops, ENVELOPES, {("PEA", "AAA"): 1100.0}, {}, d("2025-12-31"), d("2026-06-30"), {})
    assert result["missing"] == ["AAA"]


def test_flux_des_operations():
    ops = [op("2026-01-02", "PEA Boursorama", "Achat", "aaa", 1, 100.0),
           op("2026-01-03", "PEA Boursorama", "Vente", "AAA", 1, 110.0),
           op("2026-01-04", "CTO Trade Republic", "Dividende", "BBB", 1, 5.0)]
    flows = operation_flows(ops, ENVELOPES)
    assert [(f.amount, f.envelope, f.ticker) for f in flows] == [(100.0, "PEA", "AAA"), (-110.0, "PEA", "AAA"),
                                                                 (-5.0, "CTO", "BBB")]


def test_statistiques_completes_avec_point_du_jour():
    # Historique jusqu'à la veille, point du jour pris sur les positions actuelles (1 050 €)
    history = [HistoryPoint(date="2026-01-05", pea_value=1000.0, cto_value=0.0, total_value=1000.0),
               HistoryPoint(date="2026-01-06", pea_value=1020.0, cto_value=0.0, total_value=1020.0)]
    ops = [op("2026-01-05", "PEA Boursorama", "Achat", "AAA", 10, 1000.0)]
    holdings = [SimpleNamespace(envelope="PEA", value=1050.0, yahoo_ticker="AAA", ticker="AAA")]
    result = portfolio_stats(history, ops, ENVELOPES, holdings, {}, d("2026-01-07"), None, None)
    total = {p["key"]: p for p in result["envelopes"]["Total"]["periods"]}
    assert total["all"]["twr"] == pytest.approx(0.05)
    assert total["all"]["gain"] == pytest.approx(50.0)
    assert "CTO" not in result["envelopes"]  # jamais ouvert : que des zéros
    # Sans cours Yahoo, seule la contribution depuis le début reste calculable
    assert list(result["attribution"]) == ["all"]
    assert result["attribution"]["all"]["lines"][0]["gain"] == pytest.approx(50.0)
