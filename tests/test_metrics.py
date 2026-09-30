"""Ratios complémentaires : ROIC, croissance, couverture des intérêts, cash-flow libre, dette nette / EBITDA."""

from datetime import date

import pytest

import financials
import run
from app.data import CompanyFinancials
from app.metrics import archive_metrics, cagr, fcf_yield, interest_coverage, net_debt_to_ebitda, roic, tax_rate
from app.valuation import evaluate_company


def test_roic_resultat_apres_impot_sur_capital_investi():
    # Résultat opérationnel 10 Md, impôt 2,1 / 10 = 21 %, fonds propres 40, dettes 15 + 5, trésorerie 10 :
    # 10 x 0,79 / (40 + 20 - 10) = 7,9 / 50 = 15,8 %
    year = {"operating_income": 10e9, "pretax_income": 10e9, "income_tax": 2.1e9, "equity": 40e9,
            "long_term_debt": 15e9, "short_term_debt": 5e9, "cash": 10e9}
    assert roic(year) == pytest.approx(0.158)
    # Sans taux d'impôt publié : 25 % -> 7,5 / 50 = 15 % ; crédit d'impôt (impôt négatif) : taux ramené à 0
    assert roic({**year, "income_tax": None}) == pytest.approx(0.15)
    assert tax_rate({"income_tax": -1e9, "pretax_income": 10e9}) == 0
    # Pas de ligne de dette (entreprise sans dette) : dette nulle -> 7,9 / 30 = 26,3 %
    assert roic({**year, "long_term_debt": None, "short_term_debt": None}) == pytest.approx(0.2633, abs=1e-4)
    # Trésorerie inconnue, ou plus de trésorerie que de capitaux investis : pas de ROIC
    assert roic({**year, "cash": None}) is None
    assert roic({**year, "cash": 70e9}) is None


def test_croissance_annuelle_moyenne():
    # 100 -> 161,05 en 5 ans : 1,6105^(1/5) - 1 = +10 % par an
    assert cagr({2020: 100, 2021: 120, 2025: 161.051}) == (pytest.approx(0.10), 5)
    # 4 exercices seulement (Yahoo) : sur 3 ans, 100 -> 133,1 = +10 %
    assert cagr({2022: 100, 2023: 110, 2024: 121, 2025: 133.1}) == (pytest.approx(0.10), 3)
    # 2 ans d'écart seulement, ou départ en perte : pas de croissance en %
    assert cagr({2024: 100, 2025: 120}) is None
    assert cagr({2020: -5, 2025: 100}) is None


def test_couverture_des_interets():
    # Résultat opérationnel 12 Md, intérêts 1,5 Md : couverts 8 fois
    assert interest_coverage({"operating_income": 12e9, "interest_expense": -1.5e9}) == 8
    assert interest_coverage({"operating_income": 12e9}) is None


def test_ratios_de_l_archive():
    years = [{"year": y, "revenue": 100e9 * 1.08 ** (y - 2020), "operating_income": 10e9, "equity": 40e9,
              "long_term_debt": 20e9, "cash": 10e9, "interest_expense": 2e9} for y in range(2020, 2026)]
    years[-1]["operating_income"] = 12e9
    result = archive_metrics(years)
    # Dernier exercice : 12 x 0,75 / 50 = 18 % ; médiane des 5 derniers (15, 15, 15, 15, 18) = 15 %
    assert result["roic"] == pytest.approx(0.18) and result["roic_median"] == pytest.approx(0.15)
    assert result["roic_years"] == 5 and result["interest_coverage"] == 6.0
    assert result["revenue_cagr"] == pytest.approx(0.08) and result["revenue_years"] == 5
    assert archive_metrics(None)["roic"] is None


def test_cash_flow_libre_et_dette_nette():
    # 5 € de cash-flow libre par action pour un cours de 100 € : 5 % ; 80 % : donnée aberrante
    assert fcf_yield(5, 100) == 0.05 and fcf_yield(80, 100) is None
    # Dette 30, trésorerie 10, EBITDA 10 : 2 ans d'EBITDA ; plus de trésorerie que de dettes : négatif
    assert net_debt_to_ebitda(30e9, 10e9, 10e9) == 2.0
    assert net_debt_to_ebitda(5e9, 10e9, 10e9) == -0.5
    assert net_debt_to_ebitda(30e9, 10e9, -1e9) is None


def company(**overrides) -> CompanyFinancials:
    base = dict(ticker="TEST", quote_type="EQUITY", currency="EUR", financial_currency="EUR", current_price=100.0,
                market_cap=100e9, shares_outstanding=1e9, total_debt=30e9, total_cash=10e9, ebitda=10e9,
                free_cash_flow=4e9, fcf_history=[4e9, 4e9, 4e9], sector="Industrials",
                industry="Specialty Industrial Machinery")
    base.update(overrides)
    return CompanyFinancials(**base)


YEARS = [{"year": y, "revenue": 100 * 1.1 ** (y - 2020), "operating_income": 10e9, "equity": 40e9,
          "long_term_debt": 20e9, "cash": 10e9} for y in range(2020, 2026)]


def test_evaluation_ajoute_les_ratios():
    v = evaluate_company(company(), {"eps_cagr": 0.12, "eps_years": 5}, YEARS)
    # Cash-flow libre 4 Md / 1 Md d'actions = 4 € par action, cours 100 € : 4 %
    assert (v.fcf_per_share, v.fcf_yield, v.net_debt_ebitda) == (4.0, 0.04, 2.0)
    assert v.roic == pytest.approx(0.15) and v.revenue_cagr == pytest.approx(0.10) and v.eps_cagr == 0.12
    # Banque : ni ROIC, ni cash-flow libre, ni dette nette / EBITDA ; la croissance reste
    bank = evaluate_company(company(sector="Financial Services", industry="Banks - Diversified"), None, YEARS)
    assert (bank.roic, bank.fcf_yield, bank.net_debt_ebitda) == (None, None, None)
    assert bank.revenue_cagr == pytest.approx(0.10)
    # Comptes en dollars non convertis, cotation en livres : pas de rendement du cash-flow libre
    assert evaluate_company(company(currency="GBP", financial_currency="USD")).fcf_yield is None


def test_croissance_du_bpa_sur_la_base_actuelle():
    # Bénéfice 1 000 -> 1 400 en 5 ans, actions 100 -> 95 (rachats), mais division par 2 en 2023 non retraitée
    # dans les rapports d'avant (50 actions affichées jusqu'en 2022) : BPA 10 -> 14,74, soit +8,1 % par an
    years = [{"year": 2020, "net_income": 1000, "shares": 50}, {"year": 2022, "net_income": 1200, "shares": 49},
             {"year": 2025, "net_income": 1400, "shares": 95}]
    result = financials.historical_pe(years, {}, [(date(2023, 3, 1), 2.0)], shares_now=95)
    assert result["eps_cagr"] == pytest.approx((1400 / 95 / 10) ** 0.2 - 1, abs=1e-4)
    assert result["eps_years"] == 5


def test_rendement_du_cash_flow_libre_suit_le_cours():
    record = {"price_scale": 1.0, "fcf_per_share": 4.0}
    run.refresh_with_price(record, 80.0)
    assert record["fcf_yield"] == 0.05
