from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app import history, main, notifications, users
from app.history import SnapshotError, history_row, snapshot_totals, weekly_gain
from app.sheets import SHEETS_EPOCH, parse_history_v2
from app.users import User
from snapshot import market_day, weekly_message

HEADER = ["TICKER", "NOM", "TYPE", "ENVELOPPE", "QUANTITÉ", "PRU", "INVESTI", "COURS", "DEVISE", "TAUX", "VALEUR"]


def position(ticker, envelope, quantity, invested, value):
    return [ticker, ticker, "Action", envelope, quantity, 0, invested, 0, "EUR", 1, value]


def serial(d: date) -> int:
    return (d - SHEETS_EPOCH).days


def test_totals_by_envelope():
    rows = [HEADER, position("AI.PA", "PEA", 3, 500, 560), position("NVDA", "CTO", 2, 300, 350),
            position("ENGI.PA", "PEA", 10, 150, 170), position("MC.PA", "PEA", 0, 0, "")]  # vendue : ignorée
    totals = snapshot_totals(rows)
    assert totals == {"PEA": {"value": 730, "invested": 650}, "CTO": {"value": 350, "invested": 300}}


def test_price_error_cancels_snapshot():
    with pytest.raises(SnapshotError, match="NVDA"):
        snapshot_totals([HEADER, position("NVDA", "CTO", 2, 300, "#N/A")])


def test_history_row_uses_date_serial_and_formulas():
    row = history_row(date(2026, 9, 25), {"PEA": {"value": 730.004, "invested": 650}, "CTO": {"value": 350, "invested": 300}}, 12)
    assert row == [serial(date(2026, 9, 25)), 730.0, 650, 350, 300, "=B12+D12", "=C12+E12", "=F12/G12-1"]


def points(*rows):
    return parse_history_v2([["Date"]] + [[serial(d), pea, pea_in, cto, cto_in] for d, pea, pea_in, cto, cto_in in rows])


def test_weekly_gain_excludes_contributions():
    pts = points((date(2026, 9, 25), 1000, 900, 500, 450), (date(2026, 9, 28), 1010, 900, 505, 450),
                 (date(2026, 10, 2), 1250, 1100, 520, 450))  # 200 € versés sur le PEA dans la semaine
    w = weekly_gain(pts, date(2026, 10, 2))
    assert w["start"] == "2026-09-25" and w["end"] == "2026-10-02"
    assert w["gain"] == 70  # (1770 - 1550) - (1500 - 1350)
    assert w["contributions"] == 200 and w["value"] == 1770
    assert w["gain_pct"] == pytest.approx(70 / 1500)


def test_weekly_gain_accepts_old_saturday_snapshot():
    pts = points((date(2026, 9, 26), 1000, 900, 500, 450), (date(2026, 10, 2), 1100, 900, 500, 450))
    assert weekly_gain(pts, date(2026, 10, 2))["start"] == "2026-09-26"


def test_weekly_gain_needs_recent_reference():
    assert weekly_gain(points((date(2026, 10, 2), 1100, 900, 500, 450)), date(2026, 10, 2)) is None
    old = points((date(2026, 9, 11), 1000, 900, 500, 450), (date(2026, 10, 2), 1100, 900, 500, 450))
    assert weekly_gain(old, date(2026, 10, 2)) is None  # trois semaines sans relevé


def test_market_day_skips_weekend():
    assert market_day(datetime(2026, 10, 3, 3)) == date(2026, 10, 2)  # nuit de vendredi à samedi
    assert market_day(datetime(2026, 10, 4, 3)) is None  # samedi
    assert market_day(datetime(2026, 10, 5, 3)) is None  # dimanche
    assert market_day(datetime(2026, 10, 6, 3)) == date(2026, 10, 5)


def test_weekly_message():
    title, message, tag = weekly_message({"gain": 70, "gain_pct": 70 / 1500, "value": 1770, "contributions": 200})
    assert title == "Ta semaine en bourse : en hausse" and tag == "chart_with_upwards_trend"
    assert message == "+70,00 € (+4,7 %) de plus-value cette semaine.\nValeur du portefeuille : 1 770 €.\nVersements de la semaine (200 €) non comptés."
    title, message, tag = weekly_message({"gain": -1234.5, "gain_pct": -0.02, "value": 60000, "contributions": 0})
    assert title.endswith("en baisse") and message.startswith("-1 234 € (-2,0 %)")


class FakeWorksheet:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    def get_values(self, value_render_option=None):
        return self.rows

    def update(self, range_name, values, value_input_option):
        self.updates.append((range_name, values))


@pytest.fixture
def sheet(monkeypatch):
    tabs = {
        "Historique": FakeWorksheet([["Date"], [serial(date(2026, 9, 25)), 1000, 900, 500, 450]]),
        "Positions": FakeWorksheet([HEADER, position("AI.PA", "PEA", 3, 900, 1100), position("NVDA", "CTO", 2, 450, 480)]),
    }
    monkeypatch.setattr(history, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(history, "is_v2", lambda s: True)
    monkeypatch.setattr(history, "_worksheet", lambda s, name: tabs[name])
    return tabs


def test_record_snapshot_appends_once(sheet):
    result = history.record_snapshot("sheet", date(2026, 10, 2))
    assert result["recorded"] and result["weekly"]["gain"] == 80
    assert sheet["Historique"].updates[0][0] == "A3"
    sheet["Historique"].rows.append(sheet["Historique"].updates[0][1][0][:5])
    again = history.record_snapshot("sheet", date(2026, 10, 2))  # workflow relancé
    assert not again["recorded"] and again["reason"] == "relevé déjà présent"
    assert len(sheet["Historique"].updates) == 1


def test_snapshot_endpoint_is_admin_only(monkeypatch):
    monkeypatch.setattr(users, "USERS", [User("Enzo", "code-enzo", "sheet-enzo", admin=True), User("Paul", "code-paul", "sheet-paul")])
    monkeypatch.setattr(notifications, "get_topic", lambda sheet_id: None)

    def fake_record(sheet_id, day):
        if sheet_id == "sheet-paul":
            raise SnapshotError("valeur illisible pour NVDA")
        return {"recorded": True, "reason": None, "weekly": None}

    monkeypatch.setattr(history, "record_snapshot", fake_record)
    client = TestClient(main.app)
    assert client.post("/history/snapshot?day=2026-10-02", headers={"X-Access-Token": "code-paul"}).status_code == 403
    response = client.post("/history/snapshot?day=2026-10-02", headers={"X-Access-Token": "code-enzo"})
    assert response.status_code == 200
    enzo, paul = response.json()
    assert enzo["recorded"] and "NVDA" in paul["error"]
    assert client.post("/history/snapshot?day=hier", headers={"X-Access-Token": "code-enzo"}).status_code == 400
