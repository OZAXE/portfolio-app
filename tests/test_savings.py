from datetime import date

import pytest

from app.operations import OperationError
from app.setup_edit import validate_savings
from app.sheets import parse_savings


def test_onglet_epargne_etendu():
    # Assurance-vie : valeur 12 400 €, 11 000 € versés, valeur du 15/09/2026 (numéro de série 46280)
    rows = [["Nom", "Montant", "Type", "Versé €", "Mis à jour"],
            ["Livret A", 3600.7, "", "", ""],
            ["AV Linxea Spirit", 12400, "Assurance-vie", 11000, 46280],
            ["PER Yomoni", 2500, "PER", "", "2026-06-30"],
            ["Ligne sans montant", "", "Autre", "", ""]]
    savings = parse_savings(rows)
    assert [(s["name"], s["type"], s["invested"], s["updated"]) for s in savings] == [
        ("Livret A", "Livret", None, None),
        ("AV Linxea Spirit", "Assurance-vie", 11000, "2026-09-15"),
        ("PER Yomoni", "PER", None, "2026-06-30"),
    ]


def test_ancien_onglet_livret_ne_lit_que_nom_et_montant():
    # Ancien Sheet : autres colonnes remplies de notes, ignorées
    savings = parse_savings([["LDDS", 1200, "note perso", 99, "x"]], extended=False)
    assert savings == [{"name": "LDDS", "amount": 1200, "type": "Livret", "invested": None, "updated": None}]


def test_validation_de_l_epargne():
    today = date(2026, 9, 30)
    rows = validate_savings([{"name": " AV  Linxea ", "amount": "12400.456", "type": "Assurance-vie", "invested": 11000},
                             {"name": "Livret A", "amount": 3600, "updated": "2026-01-02"}], today)
    assert rows == [["AV Linxea", 12400.46, "Assurance-vie", 11000.0, "2026-09-30"],
                    ["Livret A", 3600.0, "Livret", "", "2026-01-02"]]
    for bad in ({"name": "=IMPORTXML()", "amount": 1}, {"name": "-5", "amount": 1}, {"name": "X", "amount": -1},
                {"name": "X", "amount": 1, "type": "Crypto"}, {"name": "X", "amount": 1, "updated": "2027-01-01"}):
        with pytest.raises(OperationError):
            validate_savings([bad], today)
    with pytest.raises(OperationError):  # même nom deux fois
        validate_savings([{"name": "PEL", "amount": 1}, {"name": "pel", "amount": 2}], today)


class _Tab:
    def __init__(self, title):
        self.title = title

    def update_title(self, title):
        self.title = title


class _Sheet:
    def __init__(self, *titles):
        self.tabs = [_Tab(t) for t in titles]

    def worksheets(self):
        return self.tabs


def test_reconstruction_du_modele_renomme_l_ancien_livret():
    from app.workbook import rename_legacy_savings

    sheet = _Sheet("Positions", "Livret")
    rename_legacy_savings(sheet)
    assert [t.title for t in sheet.tabs] == ["Positions", "Épargne"]
    # Les deux existent déjà (Épargne créé par l'appli) : rien ne bouge
    sheet = _Sheet("Livret", "Épargne")
    rename_legacy_savings(sheet)
    assert [t.title for t in sheet.tabs] == ["Livret", "Épargne"]
