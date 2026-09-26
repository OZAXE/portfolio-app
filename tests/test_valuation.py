import pytest

from app.data import CompanyFinancials
from app.valuation import (
    RELIABLE_RATIO_MAX,
    compute_dcf,
    compute_quality_score,
    estimate_discount_rate,
    estimate_growth_rate,
    evaluate_company,
    normalized_fcf,
)


def company(**overrides) -> CompanyFinancials:
    base = dict(
        ticker="TEST", quote_type="EQUITY", currency="EUR", financial_currency="EUR",
        current_price=100.0, market_cap=100e9, shares_outstanding=1e9,
        total_debt=10e9, total_cash=5e9, fcf_history=[4e9, 4.5e9, 5e9, 5.5e9], beta=1.0,
        sector="Industrials", industry="Specialty Industrial Machinery",
    )
    base.update(overrides)
    return CompanyFinancials(**base)


def test_dcf_reference_values():
    # Valeurs vérifiées à l'identique contre l'implémentation JavaScript de l'appli
    assert compute_dcf(2.78e9, 0.0334, 0.075) == pytest.approx(54597884104.009384)
    assert compute_dcf(1e9, 0.12, 0.11) == pytest.approx(16768084138.45507)


def test_dcf_refuses_negative_base():
    assert compute_dcf(-1e9) is None
    assert compute_dcf(None) is None


def test_normalized_fcf_averages_last_three_years():
    # Une année écrasée par les investissements (cas Amazon) ne sert pas seule de base
    assert normalized_fcf([-16.9, 32.2, 32.9, 7.7]) == pytest.approx((32.2 + 32.9 + 7.7) / 3)


def test_growth_is_blended_and_capped():
    assert estimate_growth_rate([3.8, 27.0, 60.9, 96.7]) == 0.12  # Nvidia : plafonné
    assert estimate_growth_rate([2.54, 2.87, 2.8, 2.67]) == pytest.approx(((2.67 / 2.54) ** (1 / 3) - 1 + 0.05) / 2)
    assert estimate_growth_rate([-1, 2, 3]) == 0.05  # historique inexploitable -> défaut


def test_discount_rate_from_beta_is_bounded():
    assert estimate_discount_rate(None) == 0.09
    assert estimate_discount_rate(0.1) == 0.07
    assert estimate_discount_rate(3.0) == 0.11
    assert estimate_discount_rate(1.0) == pytest.approx(0.09)


def test_shares_derived_from_market_cap():
    # Alphabet : Yahoo ne compte qu'une classe d'actions, la capitalisation donne le total
    one_class = evaluate_company(company(shares_outstanding=0.5e9))
    both = evaluate_company(company(shares_outstanding=1e9))
    assert one_class.intrinsic_value_per_share == both.intrinsic_value_per_share


def test_unreliable_when_far_from_price():
    result = evaluate_company(company(current_price=1.0, market_cap=1e9))
    assert result.intrinsic_value_per_share / 1.0 > RELIABLE_RATIO_MAX
    assert result.dcf_reliable is False


def test_no_dcf_for_banks():
    result = evaluate_company(company(sector="Financial Services", industry="Banks - Diversified"))
    assert result.intrinsic_value_per_share is None
    assert any("Banque" in n for n in result.notes)


def test_visa_keeps_dcf():
    result = evaluate_company(company(sector="Financial Services", industry="Credit Services"))
    assert result.intrinsic_value_per_share is not None


def test_currency_mismatch_blocks_dcf():
    result = evaluate_company(company(currency="GBP", financial_currency="USD"))
    assert result.intrinsic_value_per_share is None


def test_negative_average_fcf_explained():
    result = evaluate_company(company(fcf_history=[2e9, 5e9, 3e9, -9e9]))
    assert result.intrinsic_value_per_share is None
    assert any("négatif" in n for n in result.notes)


def test_etf_has_no_valuation():
    result = evaluate_company(company(quote_type="ETF"))
    assert result.quality_score is None and result.intrinsic_value_per_share is None


def test_dcf_ingredients_exposed():
    result = evaluate_company(company())
    assert result.base_fcf == pytest.approx(5e9)
    assert result.net_debt == pytest.approx(5e9)
    assert result.shares_used == pytest.approx(1e9)


@pytest.mark.parametrize("sector,industry,pe,expected_min", [
    ("Technology", "Software - Application", 32, 18),  # PER de 32 normal en logiciel
    ("Industrials", "Specialty Industrial Machinery", 32, 0),
])
def test_sector_calibrated_score(sector, industry, pe, expected_min):
    cf = company(sector=sector, industry=industry, return_on_equity=0.28, operating_margin=0.30,
                 debt_to_equity=40, trailing_pe=pe)
    score, _ = compute_quality_score(cf)
    assert score >= expected_min


def test_software_scores_higher_than_industrial_at_same_pe():
    common = dict(return_on_equity=0.15, operating_margin=0.12, debt_to_equity=60, trailing_pe=32)
    tech, _ = compute_quality_score(company(sector="Technology", industry="Software", **common))
    indus, _ = compute_quality_score(company(**common))
    assert tech > indus


def test_bank_scored_on_price_to_book():
    cf = company(sector="Financial Services", industry="Banks - Regional", return_on_equity=0.11,
                 operating_margin=0.35, debt_to_equity=300, trailing_pe=8, price_to_book=0.9)
    score, notes = compute_quality_score(cf)
    assert score == 18.0
    assert any("banque" in n for n in notes)


def test_infinite_pe_is_ignored():
    score, _ = compute_quality_score(company(trailing_pe=None, return_on_equity=0.2))
    assert score is not None
