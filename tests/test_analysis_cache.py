"""Analyses du portefeuille : fondamentaux Yahoo gardés quelques heures, titres interrogés en parallèle."""

import threading

import pytest
from fastapi.testclient import TestClient

from app import main, users
from app.data import CompanyFinancials, SOURCE_UNAVAILABLE_ERROR
from app.sheets import Position
from app.users import User


@pytest.fixture
def api(monkeypatch):
    calls = []
    lock = threading.Lock()

    def fake_fetch(ticker):
        with lock:
            calls.append(ticker)
        if ticker == "DOWN.PA":
            return CompanyFinancials(ticker=ticker, raw_error=SOURCE_UNAVAILABLE_ERROR)
        return CompanyFinancials(ticker=ticker, name=f"Société {ticker}", current_price=100.0)

    monkeypatch.setattr(users, "USERS", [User("Enzo", "code", "sheet", admin=True)])
    monkeypatch.setattr(main, "fetch_company_financials", fake_fetch)
    monkeypatch.setattr(main, "get_portfolio_positions", lambda sheet_id: [
        Position("AI.PA", 3, "PEA"), Position("NVDA", 2, "CTO"), Position("DOWN.PA", 1, "PEA")])
    monkeypatch.setattr(main, "_financials_cache", {})
    client = TestClient(main.app)
    return client, calls


def test_second_opening_does_not_call_yahoo_again(api):
    client, calls = api
    first = client.get("/portfolio/analysis", headers={"X-Access-Token": "code"}).json()
    assert [a["ticker"] for a in first] == ["AI.PA", "NVDA", "DOWN.PA"]  # ordre du Sheet conservé
    assert first[0]["financials"]["name"] == "Société AI.PA" and first[0]["quantity"] == 3
    client.get("/portfolio/analysis", headers={"X-Access-Token": "code"})
    client.get("/analysis/nvda", headers={"X-Access-Token": "code"})
    assert sorted(calls) == ["AI.PA", "DOWN.PA", "DOWN.PA", "NVDA"]  # seul l'échec est retenté


def test_cache_expires(api, monkeypatch):
    client, calls = api
    client.get("/analysis/AI.PA", headers={"X-Access-Token": "code"})
    monkeypatch.setattr(main, "FINANCIALS_CACHE_SECONDS", 0)
    client.get("/analysis/AI.PA", headers={"X-Access-Token": "code"})
    assert calls == ["AI.PA", "AI.PA"]


def test_cached_object_is_not_shared(api):
    first = main.cached_financials("AI.PA")
    first.name = "modifié"
    assert main.cached_financials("AI.PA").name == "Société AI.PA"


def test_yahoo_endpoints_need_an_access_code(api):
    client, calls = api
    assert client.get("/analysis/AI.PA").status_code == 401
    assert client.get("/fx/USD").status_code == 401
    assert calls == []
