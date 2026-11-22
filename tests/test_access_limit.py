"""Limite des codes d'accès faux par adresse IP (require_access)."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.users import User

ENZO = User(name="Enzo", token="le-bon-code", sheet_id="sheet", admin=True)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "resolve", lambda token: ENZO if token == "le-bon-code" else None)
    monkeypatch.setattr(main, "_bad_codes", main.defaultdict(list))
    return TestClient(main.app)


def test_trente_codes_faux_bloquent_l_adresse_une_heure(client):
    for i in range(main.BAD_CODE_LIMIT):
        assert client.get("/me", headers={"X-Access-Token": f"essai{i}"}).status_code == 401
    # 31e essai : refusé avant même de regarder le code, le bon compris
    assert client.get("/me", headers={"X-Access-Token": "le-bon-code"}).status_code == 429


def test_une_autre_adresse_n_est_pas_bloquee(client):
    for i in range(main.BAD_CODE_LIMIT):
        client.get("/me", headers={"X-Access-Token": f"essai{i}", "X-Forwarded-For": "1.1.1.1"})
    # Render met l'adresse réelle en dernier : « 1.1.1.1, 2.2.2.2 » vient de 2.2.2.2
    ok = client.get("/me", headers={"X-Access-Token": "le-bon-code", "X-Forwarded-For": "1.1.1.1, 2.2.2.2"})
    assert ok.status_code == 200


def test_sans_code_rien_n_est_compte(client):
    for _ in range(main.BAD_CODE_LIMIT + 5):
        assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"X-Access-Token": "le-bon-code"}).status_code == 200
