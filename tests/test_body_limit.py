"""Protections de l'API : taille maximale des requêtes et ticker validé avant d'interroger Yahoo."""

import pytest
from fastapi.testclient import TestClient

from app import main, signup, users
from app.data import CompanyFinancials
from app.users import User

FRONT = "https://portfolio-front-8t6m.onrender.com"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "MAX_BODY_BYTES", 100)
    monkeypatch.setattr(main, "_signup_hits", main.defaultdict(list))
    monkeypatch.setattr(signup, "start", lambda sheet: {"sheet": sheet})  # route sans code d'accès, sans Google
    return TestClient(main.app)


def test_requete_trop_grosse_refusee_avec_le_message_et_cors(client):
    """Limite abaissée à 100 octets : un JSON de ~150 octets est refusé avant d'atteindre la route, avec les
    en-têtes CORS pour que le front affiche le message au lieu d'une erreur réseau."""
    response = client.post("/signup/start", json={"sheet": "x" * 140}, headers={"Origin": FRONT})
    assert response.status_code == 413
    assert "30 Mo" in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == FRONT


def test_envoi_par_blocs_sans_taille_annoncee_compte_aussi(client):
    """Sans Content-Length (envoi par blocs), les morceaux sont comptés : 3 x 50 octets > 100."""
    response = client.post("/signup/start", content=(b"x" * 50 for _ in range(3)),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_petite_requete_arrive_intacte_a_la_route(client):
    """Sous la limite, le corps lu par la protection est rejoué tel quel à la route."""
    response = client.post("/signup/start", json={"sheet": "abc"})
    assert response.status_code == 200 and response.json() == {"sheet": "abc"}


def test_analyse_refuse_un_ticker_invalide_sans_appeler_yahoo(monkeypatch):
    calls = []
    monkeypatch.setattr(users, "USERS", [User("Enzo", "code", "sheet", admin=True)])
    monkeypatch.setattr(main, "_financials_cache", {})
    monkeypatch.setattr(main, "fetch_company_financials",
                        lambda t: calls.append(t) or CompanyFinancials(ticker=t, name="Air Liquide", current_price=170.0))
    monkeypatch.setattr(main, "_archive", lambda t: {})
    client = TestClient(main.app)
    headers = {"X-Access-Token": "code"}
    assert client.get("/analysis/<script>", headers=headers).status_code == 400
    assert client.get("/analysis/" + "A" * 30, headers=headers).status_code == 400  # 20 caractères au plus
    assert client.get("/analysis/ai.pa", headers=headers).status_code == 200  # mis en majuscules, accepté
    assert calls == ["AI.PA"]
