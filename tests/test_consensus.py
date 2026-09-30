from datetime import datetime, timezone

import pytest

from app.data import CompanyFinancials, _fill_consensus, _normalize_minor_currency


def london(price_pence):
    cf = CompanyFinancials(ticker="ULVR.L", currency="GBp", current_price=price_pence)
    _normalize_minor_currency(cf)
    return cf


def test_objectifs_de_cours_ramenes_en_livres():
    # Unilever coté 4 500 pence ; objectif moyen 5 000 pence = 50 £ (+11 %)
    cf = london(4500)
    _fill_consensus(cf, {"numberOfAnalystOpinions": 20, "targetMeanPrice": 5000, "targetLowPrice": 4000,
                         "targetHighPrice": 5800, "recommendationMean": 2.3})
    assert (cf.target_mean_price, cf.target_low_price, cf.target_high_price) == (50, 40, 58)
    assert cf.recommendation_mean == 2.3 and cf.analyst_count == 20


def test_objectif_aberrant_ou_trop_peu_d_analystes_ignore():
    cf = CompanyFinancials(ticker="X", currency="EUR", current_price=100)
    _fill_consensus(cf, {"numberOfAnalystOpinions": 12, "targetMeanPrice": 9000})  # 90 fois le cours
    assert cf.target_mean_price is None
    cf = CompanyFinancials(ticker="Y", currency="EUR", current_price=100)
    _fill_consensus(cf, {"numberOfAnalystOpinions": 2, "targetMeanPrice": 120, "recommendationMean": 2})
    assert cf.target_mean_price is None and cf.recommendation_mean is None and cf.analyst_count == 2


def test_date_des_resultats():
    stamp = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc).timestamp()
    cf = CompanyFinancials(ticker="AI.PA", currency="EUR", current_price=170)
    _fill_consensus(cf, {"earningsTimestampStart": stamp})
    assert cf.earnings_date == "2026-10-23"
