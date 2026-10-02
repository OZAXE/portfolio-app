"""Budget (Plus > Budget, administrateur) : opérations envoyées par scripts/envoyer_budget.py depuis outputs.xlsx.
Libellés et montants inventés : le dépôt est public, aucune vraie opération bancaire ne doit y entrer."""

import sys
from datetime import date
from pathlib import Path

import pytest

from app import budget
from app.operations import OperationError
from app.realized import CashMovement

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import envoyer_budget  # noqa: E402

OP = {"date": "2026-08-17", "label": "CB SUPERMARCHE\nCENTRE", "amount": "8,56", "category": "Courses",
      "subcategory": "Supermarché", "kind": "depense"}


def test_ligne_validee():
    # Libellé sur deux lignes (prélèvement SEPA du CA) remis sur une ligne, montant à virgule lu
    assert budget.budget_row(OP, "2026-10-02") == ["2026-08-17", "CB SUPERMARCHE CENTRE", 8.56, "Courses", "Supermarché",
                                                   "depense", "2026-10-02"]


@pytest.mark.parametrize("change, message", [
    ({"kind": "cadeau"}, "Type invalide"),
    ({"date": "17/08/2026"}, "Date invalide"),
    ({"amount": "abc"}, "Montant invalide"),
    ({"amount": float("nan")}, "Montant invalide"),
    ({"label": "  "}, "Libellé manquant"),
    ({"category": ""}, "Catégorie manquant"),
])
def test_operation_refusee(change, message):
    with pytest.raises(OperationError, match=message):
        budget.budget_row({**OP, **change}, "2026-10-02")


def test_lecture_ignore_les_lignes_abimees_a_la_main():
    rows = [["2026-08-17", "CB SUPERMARCHE", "8.56", "Courses", "Supermarché", "depense", "2026-10-02"],
            ["pas une date", "x", 1, "Courses", "", "depense", ""],
            ["2026-08-18", "x", 1, "Courses", "", "inconnu", ""],
            ["2026-08-19", "VIR Famille", 300, "Virement reçu", "", "revenu"]]  # colonne Envoyé le absente
    assert budget.parse_budget(rows) == [
        {"date": "2026-08-17", "label": "CB SUPERMARCHE", "amount": 8.56, "category": "Courses", "subcategory": "Supermarché", "kind": "depense"},
        {"date": "2026-08-19", "label": "VIR Famille", "amount": 300.0, "category": "Virement reçu", "subcategory": "", "kind": "revenu"}]


def test_versements_par_mois():
    # 100 + 50 en août (deux comptes), 200 en septembre ; retraits et intérêts ne sont pas des versements
    cash = [CashMovement(date(2026, 8, 8), "CTO TR", "Versement", 100), CashMovement(date(2026, 8, 30), "PEA Bourso", "Versement", 50),
            CashMovement(date(2026, 9, 2), "CTO TR", "Versement", 200), CashMovement(date(2026, 9, 3), "CTO TR", "Retrait", 80),
            CashMovement(date(2026, 9, 30), "CTO TR", "Intérêts", 2)]
    assert budget.deposits_by_month(cash) == {"2026-08": 150.0, "2026-09": 200.0}


class FakeTab:
    def __init__(self, rows):
        self.rows = rows

    def get_values(self):
        return self.rows

    def col_values(self, n):
        return [r[n - 1] for r in self.rows]

    def clear(self):
        self.rows = []

    def resize(self, rows=None, cols=None):
        self.size = (rows, cols)

    def update(self, range_name, values, value_input_option=None):
        assert range_name == "A1" and value_input_option == "RAW"  # brut : « =... » reste du texte
        self.rows = [list(v) for v in values]


def ops(n, day="2026-08-08"):
    # Deux virements identiques le même jour : deux opérations réelles, gardées toutes les deux
    return [{"date": day, "label": "VIR INST vers Boursorama", "amount": 100, "category": "Investissement",
             "subcategory": "Bourse/Épargne", "kind": "investissement"} for _ in range(n)]


def test_un_envoi_remplace_tout_l_onglet(monkeypatch):
    tab = FakeTab([budget.BUDGET_HEADERS] + [["2026-07-01", "ancienne", 1, "Autre", "", "depense", "2026-08-01"]])
    monkeypatch.setattr(budget, "_tab", lambda *a, **k: tab)
    payload = {"operations": ops(2) + [{**OP, "kind": "a_categoriser", "category": "À catégoriser", "date": "2026-09-08"}]}
    result = budget.replace_budget("s", payload, date(2026, 10, 2))
    assert result == {"count": 3, "first": "2026-08-08", "last": "2026-09-08", "months": 2, "to_categorize": 1, "sent": "2026-10-02"}
    assert tab.rows[0] == budget.BUDGET_HEADERS and len(tab.rows) == 4 and tab.size == (4, 7)
    assert [r[0] for r in tab.rows[1:]] == ["2026-09-08", "2026-08-08", "2026-08-08"]  # plus récentes en tête
    # Relire l'onglet redonne les opérations et la date d'envoi
    read = budget.read_budget("s")
    assert len(read["operations"]) == 3 and read["sent"] == "2026-10-02" and read["deposits"] == {}


def test_envoi_beaucoup_plus_petit_refuse_sauf_force(monkeypatch):
    # 10 opérations rangées, 4 envoyées (moins de la moitié) : sans doute le mauvais fichier
    tab = FakeTab([budget.BUDGET_HEADERS] + [["2026-08-01", "x", 1, "Autre", "", "depense", ""]] * 10)
    monkeypatch.setattr(budget, "_tab", lambda *a, **k: tab)
    with pytest.raises(OperationError, match="4 opérations alors que l'onglet Budget en contient 10"):
        budget.replace_budget("s", {"operations": ops(4)})
    assert len(tab.rows) == 11  # rien d'effacé
    assert budget.replace_budget("s", {"operations": ops(4), "force": True})["count"] == 4


def test_envoi_vide_ou_illisible_refuse(monkeypatch):
    monkeypatch.setattr(budget, "_tab", lambda *a, **k: FakeTab([budget.BUDGET_HEADERS]))
    with pytest.raises(OperationError, match="Aucune opération"):
        budget.replace_budget("s", {"operations": []})
    with pytest.raises(OperationError, match="Opération 2 : Type invalide"):
        budget.replace_budget("s", {"operations": ops(1) + [{**OP, "kind": "?"}]})


def test_routes_reservees_a_l_administrateur(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.users import User

    monkeypatch.setattr(main, "resolve", lambda token: User("Ami", None, "s2", admin=False))
    client = TestClient(main.app)
    assert client.get("/budget").status_code == 403
    assert client.post("/budget/import", json={"operations": ops(1)}).status_code == 403


# --- Lecture d'outputs.xlsx par le script d'envoi ---

def workbook(path: Path):
    """Fichier au format d'outputs.xlsx : titre en ligne 1, en-têtes en ligne 2, récapitulatif en colonnes F à H."""
    import openpyxl

    book = openpyxl.Workbook()
    book.active.title = "Résumé"
    book.active.append([None, "Suivi financier", None])
    book.active.append([None, "TOTAL DÉPENSES", 999])
    sheets = {
        "Restaurant-Bar": [["17/08/2026", "CB TRATTORIA", 31, "Restaurant", "S34-2026", None, "Restaurant", 31]],
        "Sante": [["20/07/2026", "PRLV SALLE DE SPORT", 24.99, "Sport/Fitness", "S30-2026"]],
        "Revenus": [["01/09/2026", "VIR Famille", 380, "Virement reçu", "S36-2026"],
                    ["28/08/2026", "VIR Gratification", "1 200,50", "Salaire", "S35-2026"]],
        "Investissement": [["08/08/2026", "VIR INST vers Boursorama", 100, "Bourse/Épargne", "S32-2026"]],
        "Virements internes": [["31/08/2026", "VIR vers Livret A", 1024, "Livret A", "S36-2026"]],
        "À categoriser": [["05/09/2026", "CB NOUVEAU COMMERCE", 23.4, None, "S36-2026"]],
    }
    for title, rows in sheets.items():
        ws = book.create_sheet(title)
        ws.append([title.upper()])
        ws.append(["Date", "Libellé", "Montant (EUR)", "Sous-catégorie", "Semaine", None, "Sous-catégorie", "Total"])
        for row in rows:
            ws.append(row)
        ws.append([None, "TOTAL", 999])  # ligne de total sans date : ignorée
    book.save(path)


def test_le_script_lit_chaque_onglet_avec_son_type(tmp_path):
    path = tmp_path / "outputs.xlsx"
    workbook(path)
    result = envoyer_budget.read_outputs(path)
    assert result == [
        {"date": "2026-08-17", "label": "CB TRATTORIA", "amount": 31.0, "category": "Restaurant/Bar", "subcategory": "Restaurant", "kind": "depense"},
        {"date": "2026-07-20", "label": "PRLV SALLE DE SPORT", "amount": 24.99, "category": "Santé", "subcategory": "Sport/Fitness", "kind": "depense"},
        {"date": "2026-09-01", "label": "VIR Famille", "amount": 380.0, "category": "Virement reçu", "subcategory": "", "kind": "revenu"},
        {"date": "2026-08-28", "label": "VIR Gratification", "amount": 1200.5, "category": "Salaire", "subcategory": "", "kind": "revenu"},
        {"date": "2026-08-08", "label": "VIR INST vers Boursorama", "amount": 100.0, "category": "Investissement", "subcategory": "Bourse/Épargne", "kind": "investissement"},
        {"date": "2026-08-31", "label": "VIR vers Livret A", "amount": 1024.0, "category": "Virements internes", "subcategory": "Livret A", "kind": "interne"},
        {"date": "2026-09-05", "label": "CB NOUVEAU COMMERCE", "amount": 23.4, "category": "À catégoriser", "subcategory": "", "kind": "a_categoriser"},
    ]
    # Ce que lit le script passe les contrôles de l'API
    assert all(budget.budget_row(op, "2026-10-02") for op in result)


@pytest.mark.parametrize("title, kind", [("Résumé", None), ("RESUME", None), ("A catégoriser", ("a_categoriser", "À catégoriser")),
                                         ("Courses", ("depense", "Courses")), ("Virements internes", ("interne", "Virements internes"))])
def test_type_de_chaque_onglet(title, kind):
    assert envoyer_budget.sheet_kind(title) == kind
