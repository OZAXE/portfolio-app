import json

import pytest
from fastapi.testclient import TestClient

from app import main, users
from app.sheets import parse_history_v2, parse_positions_v2
from app.users import User

POSITIONS = [
    ["Ticker", "Nom", "Compte", "Enveloppe", "Quantité", "PRU €", "Investi €", "Cours", "Devise",
     "Taux €", "Valeur €", "Plus-value €", "Plus-value %", "Secteur", "Zone"],
    ["AI.PA", "Air Liquide", "PEA Boursorama", "PEA", 7, 170.33, 1192.31, 167.5, "EUR", 1, 1172.5, -19.81, -0.0166, "Industrie", "France"],
    ["NVDA", "NVIDIA", "CTO Trade Republic", "CTO", 0.970148, 158.15, 153.43, 225.07, "USD", 0.8779, 191.69, 38.26, 0.2494, "Technologie", "États-Unis"],
    ["OLD.PA", "Vendue", "PEA Boursorama", "PEA", 0, 10, 0, 12, "EUR", 1, 0, 0, "", "", ""],  # entièrement vendue
    ["", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
]


def test_positions_v2_skip_sold_lines():
    lines = parse_positions_v2(POSITIONS)
    assert [(h.yahoo_ticker, h.envelope, q, h.name) for h, q in lines] == [
        ("AI.PA", "PEA", 7, "Air Liquide"), ("NVDA", "CTO", 0.970148, "NVIDIA")]


def test_history_v2_rows():
    rows = [["Date", "Valeur PEA", "Investi PEA", "Valeur CTO", "Investi CTO"],
            [46290, 2038.85, 2025.22, 521.62, 440.17], [46147, 1698.4, 1635.59, 479.48, 427.04]]
    points = parse_history_v2(rows)
    assert [p.date for p in points] == ["2026-05-05", "2026-09-25"]
    assert points[-1].total_value == pytest.approx(2560.47)
    assert points[-1].total_pct == pytest.approx(2560.47 / 2465.39 - 1)


@pytest.fixture
def two_users(monkeypatch):
    team = [User("Enzo", "code-enzo", "sheet-enzo", admin=True, briefs_folder="folder-enzo"),
            User("Paul", "code-paul", "sheet-paul")]
    monkeypatch.setattr(users, "USERS", team)
    seen = []
    monkeypatch.setattr(main, "get_portfolio_positions", lambda sheet_id: seen.append(sheet_id) or [])
    return seen


def test_each_code_reads_its_own_sheet(two_users):
    client = TestClient(main.app)
    assert client.get("/portfolio", headers={"X-Access-Token": "code-paul"}).status_code == 200
    assert client.get("/portfolio", headers={"X-Access-Token": "code-enzo"}).status_code == 200
    assert two_users == ["sheet-paul", "sheet-enzo"]


def test_unknown_code_refused(two_users):
    client = TestClient(main.app)
    assert client.get("/portfolio").status_code == 401
    assert client.get("/portfolio", headers={"X-Access-Token": "nope"}).status_code == 401


def test_admin_only_for_admin(two_users):
    client = TestClient(main.app)
    r = client.post("/admin/sheet/setup?target=x", headers={"X-Access-Token": "code-paul"})
    assert r.status_code == 403


def test_friend_without_briefs_gets_empty_list(two_users):
    client = TestClient(main.app)
    assert client.get("/briefs", headers={"X-Access-Token": "code-paul"}).json() == []
    assert client.get("/me", headers={"X-Access-Token": "code-paul"}).json() == {"name": "Paul", "admin": False, "briefs": False}


def test_users_json_config(monkeypatch):
    monkeypatch.setenv("USERS_JSON", json.dumps([{"name": "A", "token": "t", "sheet_id": "s", "admin": True}]))
    loaded = users.load_users()
    assert loaded == [User("A", "t", "s", admin=True)]


def test_operation_validation_errors_are_400(two_users, monkeypatch):
    from app import operations

    def fake_add(sheet_id, payload, sector="", zone=""):
        raise operations.OperationError("Quantité doit être positif")

    monkeypatch.setattr(main, "add_operation", fake_add)
    client = TestClient(main.app)
    r = client.post("/operations", json={"type": "Achat"}, headers={"X-Access-Token": "code-paul"})
    assert r.status_code == 400 and "Quantité" in r.json()["detail"]
