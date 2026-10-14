"""Case « Lu » des briefs hebdo, rangée dans l'onglet « Briefs lus » du Sheet."""

from datetime import date

import pytest

from app import brief_reads


class FakeTab:
    def __init__(self, rows):
        self.rows = rows

    def get_values(self):
        return self.rows

    def col_values(self, n):
        return [r[n - 1] for r in self.rows]

    def append_row(self, row, value_input_option=None):
        assert value_input_option == "RAW"
        self.rows.append(row)

    def delete_rows(self, i):
        del self.rows[i - 1]


@pytest.fixture
def tab(monkeypatch):
    holder = {"ws": None}

    def fake_tab(sheet_id, name, headers, create):
        if holder["ws"] is None and create:
            holder["ws"] = FakeTab([headers])
        return holder["ws"]

    monkeypatch.setattr(brief_reads, "_tab", fake_tab)
    return holder


BRIEF = {"id": "abc", "date": "2026-10-10", "title": "2026-10-10.html"}


def test_sans_onglet_rien_n_est_lu(tab):
    assert brief_reads.list_reads("s") == {}
    assert brief_reads.set_read("s", BRIEF, False) == {}  # décocher ne crée pas l'onglet
    assert tab["ws"] is None


def test_cocher_cree_l_onglet_une_seule_ligne_par_brief(tab):
    assert brief_reads.set_read("s", BRIEF, True, date(2026, 10, 14)) == {"abc": "2026-10-14"}
    brief_reads.set_read("s", BRIEF, True, date(2026, 10, 15))  # recoché depuis un autre appareil : pas de doublon
    assert tab["ws"].rows == [brief_reads.READS_HEADERS, ["abc", "2026-10-10", "2026-10-14"]]


def test_decocher_retire_la_ligne(tab):
    other = {"id": "def", "date": "2026-10-03"}
    brief_reads.set_read("s", BRIEF, True, date(2026, 10, 14))
    brief_reads.set_read("s", other, True, date(2026, 10, 14))
    assert brief_reads.set_read("s", BRIEF, False) == {"def": "2026-10-14"}


def test_lecture_tolere_les_lignes_vides_ou_courtes():
    assert brief_reads.parse_reads([["", "x"], ["abc"], [" def ", "2026-10-03", "2026-10-14T09:00"]]) == {
        "abc": "", "def": "2026-10-14"}


def test_api_refuse_un_brief_absent_du_dossier(monkeypatch, tab):
    """L'identifiant écrit dans le Sheet vient de la liste Drive : un identifiant inventé est refusé (404)."""
    from fastapi.testclient import TestClient

    from app import main
    from app.users import User

    monkeypatch.setattr(main, "resolve", lambda token: User("Enzo", None, "s", briefs_folder="dossier"))
    monkeypatch.setattr(main, "list_briefs", lambda folder: [BRIEF])
    client = TestClient(main.app)
    assert client.post("/briefs/read", json={"id": "=IMPORTRANGE(1)", "read": True}).status_code == 404
    assert tab["ws"] is None
    assert client.post("/briefs/read", json={"id": "abc", "read": True}).json() == {"abc": date.today().isoformat()}
    assert client.get("/briefs/read").json() == {"abc": date.today().isoformat()}
