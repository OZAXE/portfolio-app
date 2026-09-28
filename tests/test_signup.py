from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main, signup, users
from app.signup import SignupError, parse_sheet_id, token_hash, valid_codes, verification_code
from app.users import User

SECRET = b"secret-de-test"
TODAY = date(2026, 9, 28)
SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"


class FakeWorksheet:
    def __init__(self, title, rows):
        self.title, self.rows = title, rows

    def get_values(self):
        return self.rows

    def col_values(self, col):
        return [r[col - 1] if len(r) >= col else "" for r in self.rows]

    def cell(self, row, col):
        return type("Cell", (), {"value": self.rows[row - 1][col - 1] if len(self.rows[row - 1]) >= col else ""})()

    def update_cell(self, row, col, value):
        self.rows[row - 1] += [""] * (col - len(self.rows[row - 1]))
        self.rows[row - 1][col - 1] = value

    def append_row(self, values, value_input_option=None):
        self.rows.append(list(values))

    def update(self, range_name, values):
        self.rows[:len(values)] = [list(v) for v in values]


class FakeSheet:
    def __init__(self, tabs):
        self.tabs = {t.title: t for t in tabs}

    def worksheets(self):
        return list(self.tabs.values())

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWorksheet(title, [])
        return self.tabs[title]


@pytest.fixture
def world(monkeypatch):
    owner = FakeSheet([FakeWorksheet("Opérations", [])])
    friend = FakeSheet([FakeWorksheet("Opérations", [])])
    sheets = {"sheet-owner": owner, SHEET: friend}

    def open_sheet(sheet_id, write=False):
        if sheet_id not in sheets:
            raise PermissionError("403")
        return sheets[sheet_id]

    monkeypatch.setattr(signup, "_open_sheet", open_sheet)
    monkeypatch.setattr(signup, "_secret", lambda: SECRET)
    monkeypatch.setattr(signup, "service_account_email", lambda: "robot@projet.iam.gserviceaccount.com")
    monkeypatch.setattr(users, "USERS", [User("Enzo", "code-enzo", "sheet-owner", admin=True)])
    monkeypatch.setattr(signup, "_cache", {"at": 0.0, "users": []})
    monkeypatch.delenv("SIGNUP_OPEN", raising=False)
    monkeypatch.delenv("REGISTRY_SHEET_ID", raising=False)
    return sheets


def type_code(sheet, code):
    ws = sheet.tabs["Réglages"]
    ws.update_cell(ws.col_values(1).index("code_inscription") + 1, 2, code)


def test_parse_sheet_id():
    assert parse_sheet_id(f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=0") == SHEET
    assert parse_sheet_id(SHEET) == SHEET
    with pytest.raises(SignupError):
        parse_sheet_id("https://exemple.com")


def test_code_depends_on_sheet_and_day():
    code = verification_code(SHEET, TODAY, SECRET)
    assert code.startswith("PI-") and len(code) == 9
    assert code != verification_code("autre-sheet-123456789012", TODAY, SECRET)
    assert code in valid_codes(SHEET, date(2026, 9, 29), SECRET)  # commencé la veille
    assert code not in valid_codes(SHEET, date(2026, 9, 30), SECRET)


def test_signup_then_login(world):
    started = signup.start(SHEET, TODAY)
    assert started["existing"] is None
    with pytest.raises(SignupError, match="incorrect"):
        signup.finish(SHEET, "Paul", TODAY)  # code pas encore collé
    type_code(world[SHEET], started["code"])
    result = signup.finish(SHEET, "Paul", TODAY)
    assert result["name"] == "Paul" and not result["recovered"]

    row = world["sheet-owner"].tabs["Utilisateurs"].rows[1]
    assert row[0] == "Paul" and row[1] == token_hash(result["token"]) and row[2] == SHEET
    assert result["token"] not in row  # jamais le code en clair
    assert users.resolve(result["token"]).sheet_id == SHEET
    assert users.resolve("mauvais-code") is None
    assert [u.name for u in users.all_users()] == ["Enzo", "Paul"]


def test_lost_code_replaces_token(world):
    type_code(world[SHEET], signup.start(SHEET, TODAY)["code"])
    first = signup.finish(SHEET, "Paul", TODAY)
    started = signup.start(SHEET, TODAY)
    assert started["existing"] == "Paul"
    type_code(world[SHEET], started["code"])
    second = signup.finish(SHEET, "", TODAY)
    assert second["recovered"] and second["name"] == "Paul"
    assert users.resolve(first["token"]) is None and users.resolve(second["token"]).name == "Paul"
    assert len(world["sheet-owner"].tabs["Utilisateurs"].rows) == 2


def test_refusals(world, monkeypatch):
    with pytest.raises(SignupError, match="robot@projet"):
        signup.start("1PasPartageAvecLeRobot_0123456789", TODAY)
    with pytest.raises(SignupError, match="administrateur"):
        signup._check_sheet("sheet-owner")  # Sheet d'un utilisateur de USERS_JSON
    with pytest.raises(SignupError, match="modèle"):
        signup.start(signup.TEMPLATE_SHEET_ID, TODAY)
    type_code(world[SHEET], signup.start(SHEET, TODAY)["code"])
    with pytest.raises(SignupError, match="déjà pris"):
        signup.finish(SHEET, "enzo", TODAY)
    monkeypatch.setenv("MAX_SIGNUPS", "0")
    with pytest.raises(SignupError, match="maximum"):
        signup.finish(SHEET, "Paul", TODAY)
    monkeypatch.setenv("SIGNUP_OPEN", "0")
    with pytest.raises(SignupError, match="fermées"):
        signup.start(SHEET, TODAY)


def test_not_a_template_copy(world):
    world[SHEET].tabs.pop("Opérations")
    with pytest.raises(SignupError, match="copie du modèle"):
        signup.start(SHEET, TODAY)


def test_signup_endpoints(world, monkeypatch):
    monkeypatch.setattr(main, "SIGNUP_LIMIT", 3)
    main._signup_hits.clear()
    client = TestClient(main.app)
    info = client.get("/signup/info").json()
    assert info["open"] and info["service_account"].startswith("robot@") and info["template_copy_url"].endswith("/copy")
    assert client.post("/signup/start", json={"sheet": "n'importe quoi"}).status_code == 400
    code = client.post("/signup/start", json={"sheet": SHEET}).json()["code"]
    type_code(world[SHEET], code)
    token = client.post("/signup/finish", json={"sheet": SHEET, "name": "Paul"}).json()["token"]
    assert client.get("/me", headers={"X-Access-Token": token}).json() == {"name": "Paul", "admin": False, "briefs": False}
    assert client.post("/signup/start", json={"sheet": SHEET}).status_code == 429
