from datetime import date

import pytest

import financials
import run
from app.valuation import blend_fair_value, historical_pe_fair_value


def test_actions_ramenees_a_la_base_actuelle_apres_une_division():
    # Apple, division par 4 le 31/08/2020 ; ~17 milliards d'actions aujourd'hui.
    # 10-K de 2019 d'origine : 4,6 milliards -> x 4 = 18,4 (plus proche de 17 que 4,6)
    splits = [(date(2020, 8, 31), 4.0)]
    assert financials.adjusted_shares(4.6e9, 2019, splits, 17e9) == pytest.approx(18.4e9)
    # Exercice 2019 déjà retraité par un 10-K plus récent (18,5 milliards) : laissé tel quel
    assert financials.adjusted_shares(18.5e9, 2019, splits, 17e9) == pytest.approx(18.5e9)
    # Exercice postérieur à la division : aucune correction possible
    assert financials.adjusted_shares(16e9, 2021, splits, 17e9) == pytest.approx(16e9)


def test_per_historique_mediane_et_bpa():
    # Bénéfice 100, 10 actions -> BPA 10 chaque année. Cours moyens 200, 220, 180, 250, 300 :
    # PER 20, 22, 18, 25, 30 -> médiane 22. 2020 à perte et 2026 (5 mois de cours) écartés.
    years = [{"year": 2020, "net_income": -5, "shares": 10}] + [
        {"year": y, "net_income": 100, "shares": 10} for y in range(2021, 2026)]
    closes = {2020: [100] * 12, 2021: [200] * 12, 2022: [220] * 12, 2023: [180] * 12,
              2024: [240, 260] * 6, 2025: [300] * 12, 2026: [320] * 5}
    result = financials.historical_pe(years, closes, [])
    assert [p["pe"] for p in result["years"]] == [20, 22, 18, 25, 30]
    assert result["median"] == 22 and result["eps"] == 10 and result["eps_year"] == 2025
    assert historical_pe_fair_value(result) == pytest.approx(220)


def test_per_historique_exige_trois_annees():
    years = [{"year": 2024, "net_income": 100, "shares": 10}, {"year": 2025, "net_income": 100, "shares": 10}]
    result = financials.historical_pe(years, {2024: [200] * 12, 2025: [210] * 12}, [])
    assert result["median"] is None and historical_pe_fair_value(result) is None


def test_per_historique_ecarte_un_per_aberrant():
    # Bénéfice quasi nul en 2023 (PER de 2 000) : écarté, médiane sur 2021, 2022, 2024 = 20
    years = [{"year": y, "net_income": 1 if y == 2023 else 100, "shares": 10} for y in range(2021, 2025)]
    closes = {y: [200] * 12 for y in range(2021, 2025)}
    assert financials.historical_pe(years, closes, [])["median"] == 20


def test_prix_juste_moyenne_avec_le_per_historique():
    # Cours 100 ; DCF 120, PER du secteur 80, PER historique 130 -> (120 + 80 + 130) / 3 = 110
    fair = blend_fair_value(100, 120, 80, None, 130)
    assert fair["fair_value"] == pytest.approx(110)
    # PER historique à 3 fois le cours : écarté comme les autres méthodes
    assert blend_fair_value(100, 120, 80, None, 300)["fair_value"] == pytest.approx(100)


def test_prix_juste_recalcule_au_cours_du_jour_avec_le_per_historique():
    record = {"intrinsic_value": 120.0, "fair_value_pe": 80.0, "fair_value_pb": None, "fair_value_hist_pe": 130.0}
    run.refresh_with_price(record, 100.0)
    assert record["fair_value"] == pytest.approx(110)


def test_screener_lit_le_per_historique_archive(tmp_path):
    (tmp_path / "financials").mkdir()
    (tmp_path / "financials" / "AI.PA.json").write_text('{"pe_history": {"median": 28.0, "eps": 6.5}}', encoding="utf-8")
    assert run.load_pe_history(tmp_path, "AI.PA") == {"median": 28.0, "eps": 6.5}
    assert run.load_pe_history(tmp_path, "MC.PA") is None


def test_bpa_actuel_sur_le_nombre_d_actions_du_screener():
    # Air Liquide : exercice 2025 donné sur l'ancienne base (578,6 millions d'actions), alors que les cours
    # Yahoo sont corrigés de l'attribution gratuite de juin 2025 (1 pour 10) : 638 millions d'actions aujourd'hui
    # dans le screener. BPA actuel = 3 517,9 M€ / 638 M = 5,51 € (Yahoo : 168,88 / PER 30,43 = 5,55 €)
    years = [{"year": 2023, "net_income": 3078e6, "shares": 635.2e6}, {"year": 2024, "net_income": 3306.1e6, "shares": 635.8e6},
             {"year": 2025, "net_income": 3517.9e6, "shares": 578.6e6}]
    closes = {2023: [148] * 12, 2024: [150] * 12, 2025: [172] * 12}
    result = financials.historical_pe(years, closes, [(date(2025, 6, 10), 1.1)], shares_now=638e6)
    assert result["eps"] == pytest.approx(5.514, abs=5e-4)
    # 2025 : 578,6 M x 1,1 = 636,5 M (plus proche de 638 M) -> BPA 5,53, PER 172 / 5,527 = 31,1
    # 2024 : 635,8 M déjà sur la nouvelle base -> BPA 5,20, PER 150 / 5,20 = 28,8
    assert result["years"][1:] == [{"year": 2024, "pe": 28.8}, {"year": 2025, "pe": 31.1}]


def test_rachats_d_actions_sur_cinq_ans():
    # 100 millions d'actions en 2020, 90 en 2025 : (90 / 100)^(1/5) - 1 = -2,09 % par an
    years = [{"year": y, "net_income": 1, "shares": 100e6 - 2e6 * (y - 2020)} for y in range(2020, 2026)]
    trend = financials.shares_trend(years, [], 90e6)
    assert trend == {"shares_cagr": pytest.approx(-0.0209, abs=1e-4), "shares_years": 5}
    # Division par 2 en 2023 non retraitée dans les rapports d'avant : neutralisée (200 M x 2 = 400 M)
    years = [{"year": 2021, "net_income": 1, "shares": 200e6}, {"year": 2022, "net_income": 1, "shares": 200e6},
             {"year": 2023, "net_income": 1, "shares": 396e6}]
    assert financials.shares_trend(years, [(date(2023, 3, 1), 2.0)], 396e6)["shares_cagr"] == pytest.approx(-0.005, abs=1e-3)
    assert financials.shares_trend(years[:1], [], 200e6) == {"shares_cagr": None, "shares_years": None}
