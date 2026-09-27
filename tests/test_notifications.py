import pytest
from fastapi.testclient import TestClient

from app import main, notifications, users
from app.notifications import check_price_alerts
from app.users import User
from notify import price_alert_events

ALERTS = [
    {"id": "a1", "ticker": "NVDA", "direction": "Sous", "price": 180.0, "note": "renforcer", "triggered": None},
    {"id": "a2", "ticker": "AI.PA", "direction": "Au-dessus", "price": 200.0, "note": "", "triggered": None},
    {"id": "a3", "ticker": "V", "direction": "Sous", "price": 400.0, "note": "", "triggered": "2026-09-01"},  # déjà envoyée
]


def test_price_alerts_triggered_at_close():
    triggered = check_price_alerts(ALERTS, {"NVDA": 175.2, "AI.PA": 167.5, "V": 320.0})
    assert [a["id"] for a in triggered] == ["a1"]
    assert triggered[0]["current"] == 175.2
    assert check_price_alerts(ALERTS, {"NVDA": None}) == []  # cours inconnu : rien


def test_threshold_reached_exactly_counts():
    assert [a["id"] for a in check_price_alerts(ALERTS, {"AI.PA": 200.0})] == ["a2"]


def test_notification_message():
    events = price_alert_events(ALERTS, {"NVDA": 175.2})
    assert events == [{"type": "prix", "origin": "alerte", "name": "NVDA", "id": "a1",
                       "message": "NVDA passe sous 180 : dernier cours 175.20 (renforcer)"}]


@pytest.fixture
def team(monkeypatch):
    monkeypatch.setattr(users, "USERS", [User("Enzo", "code-enzo", "sheet-enzo", admin=True), User("Paul", "code-paul", "sheet-paul")])
    monkeypatch.setattr(main, "get_portfolio_positions", lambda sheet_id: [])
    monkeypatch.setattr(main, "get_watchlist", lambda sheet_id: ["MC.PA"] if sheet_id == "sheet-paul" else [])
    monkeypatch.setattr(notifications, "get_topic", lambda sheet_id: "sujet-de-paul" if sheet_id == "sheet-paul" else None)
    monkeypatch.setattr(notifications, "list_price_alerts", lambda sheet_id: ALERTS if sheet_id == "sheet-paul" else [])


def test_night_job_endpoint_reserved_to_admin(team):
    client = TestClient(main.app)
    assert client.get("/notifications/users", headers={"X-Access-Token": "code-paul"}).status_code == 403
    body = client.get("/notifications/users", headers={"X-Access-Token": "code-enzo"}).json()
    paul = next(u for u in body if u["name"] == "Paul")
    assert paul["topic"] == "sujet-de-paul" and paul["watchlist"] == ["MC.PA"]
    assert [a["id"] for a in paul["price_alerts"]] == ["a1", "a2"]  # les alertes déjà déclenchées ne sont pas renvoyées


def test_topic_validation():
    with pytest.raises(notifications.OperationError):
        notifications.set_topic("sheet", "trop court")
