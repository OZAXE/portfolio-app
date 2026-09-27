from datetime import date

import pytest

from app.dividend_calendar import compute_calendar, project_events

TODAY = date(2026, 9, 27)


def test_last_twelve_months_repeated_one_year_later():
    history = [(date(2025, 5, 2), 3.0), (date(2025, 11, 3), 0.8), (date(2026, 5, 4), 3.2), (date(2026, 8, 3), 0.9)]
    assert project_events(history, TODAY) == [(date(2026, 11, 3), 0.8), (date(2027, 5, 4), 3.2), (date(2027, 8, 3), 0.9)]


def test_leap_day_projected_to_february_28():
    assert project_events([(date(2026, 2, 28), 1.0)], date(2026, 3, 1)) == [(date(2027, 2, 28), 1.0)]
    assert project_events([(date(2024, 2, 29), 1.0)], date(2024, 3, 1)) == [(date(2025, 2, 28), 1.0)]


def test_calendar_amounts_months_and_net_by_envelope():
    holdings = [
        {"ticker": "TTE.PA", "name": "TotalEnergies", "envelope": "PEA", "quantity": 10},
        {"ticker": "KO", "name": "Coca-Cola", "envelope": "CTO", "quantity": 4},
        {"ticker": "CW8.PA", "name": "MSCI World", "envelope": "PEA", "quantity": 2},  # ETF capitalisant
    ]
    histories = {
        "TTE.PA": [(date(2025, 12, 30), 0.85), (date(2026, 3, 31), 0.85)],
        "KO": [(date(2025, 11, 28), 0.5), (date(2026, 3, 13), 0.5)],
    }
    result = compute_calendar(holdings, histories, {"TTE.PA": 1.0, "KO": 0.9, "CW8.PA": 1.0}, TODAY)
    assert [e["ticker"] for e in result["events"]] == ["KO", "TTE.PA", "KO", "TTE.PA"]
    assert result["events"][0] == {
        "date": "2026-11-28", "ticker": "KO", "name": "Coca-Cola", "envelope": "CTO", "per_share": 0.5,
        "quantity": 4, "gross": 1.8, "net": pytest.approx(1.8 * (1 - 0.314), abs=0.01), "frequency": "semestriel",
    }
    assert result["annual_gross"] == pytest.approx(17.0 + 3.6)
    assert result["envelopes"]["PEA"] == {"gross": 17.0, "net": 17.0}  # rien de prélevé dans le PEA
    assert [m["month"] for m in result["months"]][:4] == ["2026-09", "2026-10", "2026-11", "2026-12"]
    assert len(result["months"]) == 13 and result["months"][-1]["month"] == "2027-09"
    assert result["months"][3]["gross"] == 8.5  # décembre : TotalEnergies


def test_missing_exchange_rate_reported():
    holdings = [{"ticker": "SHEL.L", "name": "Shell", "envelope": "CTO", "quantity": 3}]
    result = compute_calendar(holdings, {"SHEL.L": [(date(2026, 8, 14), 0.26)]}, {"SHEL.L": None}, TODAY)
    assert result["events"] == [] and result["missing"] == ["SHEL.L"]
