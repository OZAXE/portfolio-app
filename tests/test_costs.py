from datetime import date

import pandas as pd
import pytest

from app.costs import etf_costs, fees_by_year, pea_ceiling
from app.performance import chart_points
from app.realized import Operation
from etf_fees import stale

ENVELOPES = {"PEA Boursorama": "PEA", "PEA Trade Republic": "PEA", "CTO Trade Republic": "CTO"}


def op(day, account, kind, ticker, qty, gross, fees=0.0, taxes=0.0):
    net = gross + fees + taxes if kind == "Achat" else gross - fees - taxes
    return Operation(date.fromisoformat(day), account, kind, ticker, qty, gross, fees, taxes, net)


OPS = [
    op("2025-07-09", "PEA Boursorama", "Achat", "TTE.PA", 5, 266.50, fees=1.33, taxes=1.07),
    op("2025-08-01", "PEA Trade Republic", "Achat", "ESE.PA", 10, 278.04, fees=1.0),
    op("2026-03-23", "PEA Boursorama", "Vente", "TTE.PA", 5, 382.40, fees=1.91),
    op("2026-05-12", "PEA Boursorama", "Achat", "AI.PA", 2, 352.04, fees=1.76, taxes=1.41),
    op("2026-06-01", "CTO Trade Republic", "Achat", "NVDA", 1, 180.0, fees=1.0),
    op("2026-06-15", "PEA Boursorama", "Dividende", "AI.PA", 2, 6.60),
    op("2026-06-20", "CTO Trade Republic", "Dividende", "NVDA", 1, 0.24, taxes=0.10),
]


def test_pea_deposits_keep_highest_level_across_both_pea_accounts():
    result = pea_ceiling(OPS, ENVELOPES, date(2026, 9, 27))
    # 268,90 + 279,04 = 547,94 versés ; la vente rend 380,49 déjà dans le PEA, racheté ensuite en Air Liquide
    assert result["deposits"] == pytest.approx(547.94)
    assert result["remaining"] == pytest.approx(150_000 - 547.94)
    assert result["five_years"] == "2030-07-09" and result["five_years_reached"] is False


def test_no_pea():
    assert pea_ceiling([OPS[4]], ENVELOPES, date(2026, 9, 27)) is None


def test_fees_by_year():
    years = {y["year"]: y for y in fees_by_year(OPS, ENVELOPES)}
    assert years[2025]["brokerage"] == pytest.approx(2.33) and years[2025]["transaction_tax"] == 1.07
    assert years[2025]["trading_cost_pct"] == pytest.approx(3.40 / 544.54, abs=1e-5)
    assert years[2026]["brokerage"] == pytest.approx(4.67) and years[2026]["dividend_tax"] == 0.10
    assert years[2026]["total"] == pytest.approx(4.67 + 1.41 + 0.10)


def test_etf_running_costs():
    holdings = [{"ticker": "CW8.PA", "name": "Amundi MSCI World", "value": 3000.0},
                {"ticker": "ESE.PA", "name": "BNPP S&P 500", "value": 600.0}]
    result = etf_costs(holdings, {"CW8.PA": 0.38})
    assert result["annual"] == 11.4 and result["unknown"] == ["BNPP S&P 500"]
    assert result["weighted_ter"] == 0.38


def test_chart_points_track_pru():
    closes = pd.Series([10.0, 11.0, None, 12.0], index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]))
    trades = [
        {"date": "2026-01-05", "type": "Vente", "quantity": 1, "price": 11.0, "cost": 10.9},
        {"date": "2026-01-02", "type": "Achat", "quantity": 2, "price": 10.0, "cost": 21.0},
    ]
    result = chart_points(trades, closes)
    assert [p[0] for p in result["points"]] == ["2026-01-02", "2026-01-05", "2026-01-07"]  # jour sans cours écarté
    assert result["pru"] == [{"date": "2026-01-02", "pru": 10.5}, {"date": "2026-01-05", "pru": 10.5}]


def test_etf_fee_refresh_every_30_days():
    today = date(2026, 9, 27)
    assert stale(None, today) and stale({"updated": "2026-08-01"}, today)
    assert not stale({"updated": "2026-09-20"}, today)
