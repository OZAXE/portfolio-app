"""Courbe de cours de la fiche (API /prices) et présentation des entreprises archivée par le screener."""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import run
from app import main, prices, users
from app.data import CompanyFinancials, _fill_from_info
from app.users import User


class FakeTicker:
    """yf.Ticker réduit à history() : Unilever cotée en pence à Londres."""
    calls = 0

    def __init__(self, ticker):
        self.ticker = ticker
        self.history_metadata = {}

    def history(self, period, auto_adjust):
        FakeTicker.calls += 1
        assert auto_adjust is False  # cours réellement échangés, dividendes non réinvestis
        if self.ticker == "INCONNU":
            return pd.DataFrame()
        self.history_metadata = {"currency": "GBp"}
        days = pd.to_datetime(["2026-09-25", "2026-09-26", "2026-09-29"])
        return pd.DataFrame({"Close": [4664.5, float("nan"), 4700.0]}, index=days)


@pytest.fixture
def api(monkeypatch):
    import yfinance

    FakeTicker.calls = 0
    monkeypatch.setattr(users, "USERS", [User("Enzo", "code", "sheet", admin=True)])
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    monkeypatch.setattr(main, "_prices_cache", {})
    return TestClient(main.app)


def test_jours_vides_et_cours_nuls_ecartes():
    # Yahoo renvoie parfois NaN ou 0 un jour férié local : ni l'un ni l'autre ne doit creuser la courbe
    closes = pd.Series([10.0, float("nan"), 0.0, 12.34567], index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]))
    assert prices.closes_to_points(closes) == [["2026-01-02", 10.0], ["2026-01-07", 12.3457]]


def test_courbe_de_londres_en_livres(api):
    # 4 664,5 pence = 46,645 £, même unité que le cours affiché sur la fiche
    body = api.get("/prices/ulvr.l", headers={"X-Access-Token": "code"}).json()
    assert body["currency"] == "GBP"
    assert body["points"] == [["2026-09-25", 46.645], ["2026-09-29", 47.0]]


def test_courbe_gardee_en_cache(api):
    for _ in range(2):
        assert api.get("/prices/ULVR.L", headers={"X-Access-Token": "code"}).status_code == 200
    assert FakeTicker.calls == 1


def test_ticker_sans_cours_renvoie_404_et_n_est_pas_garde(api):
    for _ in range(2):
        assert api.get("/prices/INCONNU", headers={"X-Access-Token": "code"}).status_code == 404
    assert FakeTicker.calls == 2


def test_courbe_reservee_aux_utilisateurs(api):
    assert api.get("/prices/ULVR.L").status_code == 401


def test_presentation_lue_dans_quote_summary():
    cf = CompanyFinancials(ticker="AI.PA")
    _fill_from_info(cf, {"longBusinessSummary": "  L'Air Liquide S.A. provides gases.  ", "website": "https://www.airliquide.com",
                         "fullTimeEmployees": 66300})
    assert (cf.summary, cf.website, cf.employees) == ("L'Air Liquide S.A. provides gases.", "https://www.airliquide.com", 66300)


def test_presentation_absente_reste_vide():
    cf = CompanyFinancials(ticker="XYZ")
    _fill_from_info(cf, {"longBusinessSummary": "", "fullTimeEmployees": 0})
    assert cf.summary is None and cf.employees is None


def test_screener_archive_la_presentation_par_action(tmp_path):
    cf = CompanyFinancials(ticker="AI.PA", summary="L'Air Liquide S.A. provides gases.", employees=66300)
    run.save_profile(tmp_path, "AI.PA", run.company_profile(cf))
    saved = json.loads((tmp_path / "profiles" / "AI.PA.json").read_text(encoding="utf-8"))
    assert saved["summary"] == "L'Air Liquide S.A. provides gases." and saved["employees"] == 66300


def test_sans_nouvelle_presentation_l_ancienne_est_gardee(tmp_path):
    # quoteSummary bloqué une nuit (ratios recalculés depuis les états financiers) : pas de texte, on garde l'ancien
    run.save_profile(tmp_path, "AI.PA", {"summary": "ancienne"})
    run.save_profile(tmp_path, "AI.PA", run.company_profile(CompanyFinancials(ticker="AI.PA")))
    assert json.loads((tmp_path / "profiles" / "AI.PA.json").read_text(encoding="utf-8"))["summary"] == "ancienne"
