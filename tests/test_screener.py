import json
from datetime import datetime, timedelta, timezone

import pytest

import financials
import run


def test_price_scale_inferred_for_pence():
    record = {"price": 46.645}
    run.infer_price_scale(record, 4664.5)
    assert record["price_scale"] == 0.01
    run.infer_price_scale(record := {"price": 100.0}, 100.0)
    assert record["price_scale"] == 1.0


def test_margin_recomputed_with_new_price():
    record = {"intrinsic_value": 100.0, "price_scale": 1.0}
    run.refresh_with_price(record, 80.0)
    assert record["margin_of_safety"] == 20.0 and record["dcf_reliable"] is True
    run.refresh_with_price(record, 300.0)
    assert record["dcf_reliable"] is False


def test_weekly_history_appends_once_per_week(tmp_path):
    path = tmp_path / "history.json"
    stocks = {"AAA": {"price": 10.0, "intrinsic_value": 12.0, "margin_of_safety": 16.7, "quality_score": 14.0, "dcf_reliable": True},
              "BBB": {"error": "x"}}
    run.update_history(path, stocks)
    run.update_history(path, stocks)  # même semaine : pas de second relevé
    history = json.loads(path.read_text())
    assert len(history["dates"]) == 1
    assert history["series"]["AAA"] == [[10.0, 12.0, 16.7, 14.0, 1]]
    assert history["series"]["BBB"] == [None]


def test_new_ticker_history_is_aligned(tmp_path):
    path = tmp_path / "history.json"
    old = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    path.write_text(json.dumps({"dates": [old], "series": {"AAA": [[1, 1, 0, 10, 1]]}}))
    run.update_history(path, {"AAA": {"price": 2.0}, "NEW": {"price": 5.0}})
    series = json.loads(path.read_text())["series"]
    assert len(series["NEW"]) == 2 and series["NEW"][0] is None


def test_sec_annual_facts_keep_full_years_and_latest_filing():
    facts = [
        {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "val": 100, "filed": "2025-02-01"},
        {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "val": 105, "filed": "2026-02-01"},  # retraité
        {"form": "10-K", "start": "2024-10-01", "end": "2024-12-31", "val": 30, "filed": "2025-02-01"},  # trimestre
        {"form": "10-Q", "start": "2024-01-01", "end": "2024-12-31", "val": 1, "filed": "2025-02-01"},
    ]
    assert financials._annual_facts(facts, instant=False) == {2024: 105}


def test_financial_history_merge_keeps_archived_years():
    existing = {"currency": "EUR", "years": [{"year": 2020, "revenue": 10.0}, {"year": 2021, "revenue": 11.0}]}
    fresh = {"currency": "EUR", "source": "Yahoo", "years": {2021: {"revenue": 11.5}, 2022: {"revenue": 12.0, "net_income": 1.2}}}
    merged = financials.merge(existing, fresh)
    assert [(y["year"], y["revenue"]) for y in merged["years"]] == [(2020, 10.0), (2021, 11.5), (2022, 12.0)]
    assert merged["years"][-1]["net_margin"] == pytest.approx(0.1)
