"""Relevés du compte courant lus sur Drive et catégorisés par l'appli (budget_rules.py, budget_import.py).
Libellés, commerces et montants inventés : le dépôt est public, aucune vraie opération bancaire ni règle d'Enzo ici."""

import io
import json
from collections import Counter
from datetime import date

import openpyxl
import pytest

from app import budget_import as bi
from app import budget_rules as br
from app.budget import BUDGET_HEADERS
from app.operations import OperationError

RULES = [br.Rule("exacte", "boulangerie du port", "Courses", "Boulangerie"),
         br.Rule("exacte", "virement vers paul martin", "Autre", "Virement perso"),
         br.Rule("motif", r"AIRE DU LAC", "Restaurant/Bar", "Snack"),  # avant la règle des péages : le premier gagne
         br.Rule("motif", r"AIRE|PEAGE", "Voiture", "Péage"),
         br.Rule("motif", r"GRATIFICATION", "Revenus", "Salaire"),
         br.Rule("motif", r"VERS MON LIVRET", "Virements internes", "Livret A")]


def line(label, amount=10.0, credit=False, day=date(2026, 10, 12)):
    return br.Line(day, label, amount, credit)


@pytest.mark.parametrize("label, key", [
    # La date de fin de libellé ne fait plus partie de la clé : une règle reconnaît tous les mois
    ("Paiement par carte - X9900 BOULANGERIE DU PORT   12/10", "boulangerie du port"),
    ("Paiement par carte - X9900 BOULANGERIE DU PORT   03/11", "boulangerie du port"),
    # Dernier morceau qui ressemble à un nom (le nom commercial après « - »)
    ("Paiement par carte - X9900 SUMUP *CAFE 44 NAN 05/10 - Le Café", "le café"),
    ("Virement émis - VIR INST vers Paul Martin", "virement vers paul martin"),
    ("Virement en votre faveur - DE M. JEAN DUPONT", "virement de m. jean dupont"),
    # Prélèvement SEPA sur plusieurs lignes : seule la première compte
    ("Prélèvement - SALLE DE SPORT - Abonnement\nC0001\nFR00ZZZ000000", "abonnement"),
])
def test_cle_du_libelle(label, key):
    assert br.extract_key(label) == key


def test_categorie_regle_exacte_puis_motifs_dans_l_ordre():
    exact, patterns = br.compile_rules(RULES)
    assert br.categorize(line("Paiement par carte - X9900 BOULANGERIE DU PORT 01/09"), exact, patterns) == ("Courses", "Boulangerie")
    assert br.categorize(line("Paiement par carte - X9900 AIRE DU LAC 12/10"), exact, patterns) == ("Restaurant/Bar", "Snack")
    assert br.categorize(line("Paiement par carte - X9900 AIRE DES SAPINS 12/10"), exact, patterns) == ("Voiture", "Péage")
    assert br.categorize(line("Paiement par carte - X9900 NOUVEAU COMMERCE 12/10"), exact, patterns) is None


def test_virement_perso_recu_devient_un_remboursement():
    # Paul rembourse sa part : un crédit sur une règle « Virement perso » n'est pas une dépense
    exact, patterns = br.compile_rules(RULES)
    assert br.categorize(line("Virement émis - VIR INST vers Paul Martin"), exact, patterns) == ("Autre", "Virement perso")
    assert br.categorize(line("Virement en votre faveur - VIR INST vers Paul Martin", credit=True), exact, patterns) == ("Revenus", "Remboursement")


def test_motif_abime_ignore():
    exact, patterns = br.compile_rules([br.Rule("motif", "(non fermé", "Autre", ""), *RULES])
    assert len(patterns) == 4


def test_operation_au_format_de_l_onglet_budget():
    # Un revenu a sa sous-catégorie comme catégorie (comme l'onglet Revenus d'outputs.xlsx), les autres types suivent la catégorie
    assert br.budget_operation(line("VIR GRATIFICATION", 600, True), ("Revenus", "Salaire"))["category"] == "Salaire"
    assert br.budget_operation(line("x"), ("Virements internes", "Livret A"))["kind"] == "interne"
    assert br.budget_operation(line("x"), ("Investissement", "Bourse/Épargne"))["kind"] == "investissement"
    assert br.budget_operation(line("x"), None) == {"date": "2026-10-12", "label": "x", "amount": 10.0, "category": "À catégoriser",
                                                    "subcategory": "", "kind": "a_categoriser"}


def export(rows) -> bytes:
    """Fichier au format de l'export du CA : quelques lignes d'en-tête du compte, puis Date / Libellé / Débit / Crédit."""
    book = openpyxl.Workbook()
    ws = book.active
    ws.append(["Compte de dépôt", None, None, None])
    ws.append([None, None, None, None])
    ws.append(["Date", "Libellé", "Débit euros", "Crédit euros"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_lecture_de_l_export_du_credit_agricole():
    content = export([["12/10/2026", "Paiement par carte - X9900 AIRE DU LAC 11/10", "8,40 €", None],  # date et montant en texte
                      [date(2026, 10, 13), "Virement en votre faveur - VIR GRATIFICATION", None, 600],  # vraie date Excel
                      [None, "Solde", None, None]])  # ligne sans date : ignorée
    assert br.read_export_file(content) == [line("Paiement par carte - X9900 AIRE DU LAC 11/10", 8.4),
                                            line("Virement en votre faveur - VIR GRATIFICATION", 600.0, True, date(2026, 10, 13))]
    with pytest.raises(ValueError, match="en-tête"):
        br.read_export([["autre chose"]])


def test_export_au_format_de_novembre_2026():
    # En-tête « Date d'opération », montants en texte « 1,638.26 », livret à la suite du compte de dépôt
    book = openpyxl.Workbook()
    ws = book.active
    for row in [["Téléchargement du 06/11/2026"], ["Liste des opérations du compte entre le 06/10/2026 et le 06/11/2026"],
                ["Date d'opération", "Libellé", "Débit euros", "Crédit euros"],
                ["29/10/2026", "Virement en votre faveur - VIR GRATIFICATION", None, "1,638.26"],
                ["06/10/2026", "Virement émis - VIR VERS MON LIVRET", "1,000.00", None],
                ["Livret A carte n° 000", None, None, None],
                ["Date d'opération", "Libellé", "Débit euros", "Crédit euros"],
                ["06/10/2026", "Virement en votre faveur - DE MON COMPTE", None, "1,000.00"]]:
        ws.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    lines = br.read_export_file(buffer.getvalue())
    assert [(l.amount, l.credit) for l in lines] == [(1638.26, True), (1000.0, False), (1000.0, True)]


@pytest.mark.parametrize("text, amount", [("1 024,50 €", 1024.5), ("1,638.26", 1638.26), ("1.024,50", 1024.5), ("16.56", 16.56), ("abc", None)])
def test_montant_en_texte(text, amount):
    assert br.parse_amount(text) == amount


def test_dedoublonnage_compte_les_occurrences():
    # Deux virements identiques le même jour sont deux opérations ; deux exports qui se chevauchent ne les doublent pas
    vir = line("Virement émis - VIR INST vers Courtier", 100)
    known = Counter({br.op_key("2026-10-12", "Virement émis - VIR INST vers Courtier", 100): 1})
    assert br.new_lines([vir, vir], known) == [vir]  # un déjà rangé, le second est nouveau
    assert br.new_lines([vir, vir], known) == []  # export suivant qui couvre la même période
    # Libellé sur deux lignes dans l'export, sur une ligne dans l'onglet Budget : même opération
    assert br.new_lines([line("PRLV\nSALLE")], Counter({br.op_key("2026-10-12", "PRLV SALLE", 10): 1})) == []


@pytest.mark.parametrize("text, folder", [
    ("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp?usp=sharing", "1AbCdEfGhIjKlMnOp"),
    ("1AbCdEfGhIjKlMnOp", "1AbCdEfGhIjKlMnOp"),
])
def test_lien_du_dossier(text, folder):
    assert bi.folder_id_of(text) == folder


def test_lien_invalide_refuse():
    with pytest.raises(OperationError, match="Lien de dossier"):
        bi.folder_id_of("pas un lien !")


# --- Synchronisation avec un faux Drive et un faux Sheet ---

class FakeTab:
    def __init__(self, rows, cols=8):
        self.rows, self.col_count = [list(r) for r in rows], cols

    def get_values(self):
        return [list(r) for r in self.rows]

    def resize(self, rows=None, cols=None):
        self.col_count = cols or self.col_count

    def update(self, range_name, values, value_input_option=None):
        assert value_input_option == "RAW"
        if range_name == "A1":
            self.rows[:len(values)] = [list(v) for v in values]
            return
        # « D5:F5 » : colonnes D à F de la ligne 5
        row = int(range_name.split(":")[0][1:])
        self.rows[row - 1][3:6] = values[0]

    def append_rows(self, rows, value_input_option=None):
        assert value_input_option == "RAW"
        self.rows += [list(r) for r in rows]

    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))


class FakeDrive:
    def __init__(self, files):
        self.files = files  # id -> (nom, date de modification, contenu)

    def listing(self):
        return [{"id": i, "name": n, "mimeType": bi.XLSX if n.endswith(".xlsx") else "application/json", "modifiedTime": m}
                for i, (n, m, _) in self.files.items()]

    def download(self, f):
        return self.files[f["id"]][2]


@pytest.fixture
def sheet(monkeypatch):
    tabs = {"Budget": FakeTab([BUDGET_HEADERS[:7], ["2026-10-01", "VIR INST vers Agence", 540, "Logement", "Loyer", "depense", "2026-10-02"]], cols=7)}
    settings = {"budget_folder": "dossier"}

    def tab(sheet_id, name, headers, create, write=False):
        if name not in tabs and create:
            tabs[name] = FakeTab([headers])
        return tabs.get(name)
    monkeypatch.setattr(bi, "_tab", tab)
    monkeypatch.setattr(bi, "get_setting", lambda s, k: settings.get(k))
    monkeypatch.setattr(bi, "set_setting", lambda s, k, v: settings.__setitem__(k, v))
    seed = [{"type": "exacte", "motif": "boulangerie du port 12/10", "categorie": "Courses", "sous_categorie": "Boulangerie"},
            {"type": "motif", "motif": "AIRE", "categorie": "Voiture", "sous_categorie": "Péage"},
            {"type": "inconnu", "motif": "x", "categorie": "y"},  # type inconnu : ignoré
            ["motif", "GRATIFICATION", "Revenus", "Salaire"]]  # forme courte
    drive = FakeDrive({
        "f1": ("CA20261013_0900.xlsx", "2026-10-13T09:00:00Z", export([
            ["12/10/2026", "Paiement par carte - X9900 BOULANGERIE DU PORT 11/10", 4.2, None],
            ["12/10/2026", "Paiement par carte - X9900 AIRE DES SAPINS 11/10", 9.9, None],
            ["13/10/2026", "Paiement par carte - X9900 NOUVEAU COMMERCE 12/10", 23.4, None],
            ["13/10/2026", "Paiement par carte - X9900 NOUVEAU COMMERCE 13/10", 5, None],
            ["01/10/2026", "VIR INST vers Agence", 540, None]])),  # déjà dans l'onglet
        "f2": ("regles_budget.json", "2026-10-13T09:00:00Z", json.dumps(seed).encode()),
        "f3": ("photo.xlsx", "2026-10-13T09:00:00Z", b"pas un classeur"),
    })
    monkeypatch.setattr(bi, "drive_files", lambda folder: drive.listing())
    monkeypatch.setattr(bi, "download", drive.download)
    return tabs, settings, drive


def test_synchronisation_depuis_drive(sheet):
    tabs, settings, drive = sheet
    result = bi.sync("s", today=date(2026, 10, 14))
    # Onglet des règles créé une fois depuis regles_budget.json, date retirée de la règle exacte à la lecture
    assert [r[:4] for r in tabs["Règles budget"].rows] == [br.RULES_HEADERS[:4], ["exacte", "boulangerie du port 12/10", "Courses", "Boulangerie"],
                                                           ["motif", "AIRE", "Voiture", "Péage"], ["motif", "GRATIFICATION", "Revenus", "Salaire"]]
    assert result["added"] == 4 and result["to_categorize"] == 2
    assert result["files"] == [{"name": "CA20261013_0900.xlsx", "read": 5, "added": 4}]
    assert result["errors"] and result["errors"][0].startswith("photo.xlsx")
    rows = tabs["Budget"].rows
    assert rows[0] == BUDGET_HEADERS and tabs["Budget"].col_count == 8  # en-tête complété de la colonne Clé
    assert rows[2][3:6] == ["Courses", "Boulangerie", "depense"] and rows[3][3:6] == ["Voiture", "Péage", "depense"]
    assert rows[4][3:6] == ["À catégoriser", "", "a_categoriser"] and rows[4][7] == "nouveau commerce"
    assert rows[2][7] == ""  # clé écrite seulement pour une opération à catégoriser
    # Rien de nouveau au passage suivant : bon fichier retenu ; le mauvais n'est pas retenu, il est signalé à nouveau
    assert set(json.loads(settings["budget_files"])) == {"f1"}
    again = bi.sync("s", today=date(2026, 10, 15))
    assert again["added"] == 0 and len(again["errors"]) == 1
    # Un export plus récent qui recouvre le premier n'ajoute que la nouvelle opération
    drive.files["f4"] = ("CA20261020_0900.xlsx", "2026-10-20T09:00:00Z", export([
        ["13/10/2026", "Paiement par carte - X9900 NOUVEAU COMMERCE 12/10", 23.4, None],
        ["19/10/2026", "Paiement par carte - X9900 BOULANGERIE DU PORT 18/10", 3.1, None]]))
    assert bi.sync("s")["added"] == 1 and len(tabs["Budget"].rows) == 7


def test_sans_dossier_configure(sheet):
    _, settings, _ = sheet
    settings["budget_folder"] = None
    with pytest.raises(OperationError, match="Aucun dossier"):
        bi.sync("s")


def test_classer_une_operation_et_retenir_la_regle(sheet):
    tabs, _, _ = sheet
    bi.sync("s", today=date(2026, 10, 14))
    rows = tabs["Budget"].rows
    payload = {"row": 5, "date": "2026-10-13", "label": rows[4][1], "amount": 23.4, "category": "Shopping",
               "subcategory": "Divers", "remember": True}
    # Les deux paiements « NOUVEAU COMMERCE » (même clé) sont rangés d'un coup, et la règle est ajoutée
    assert bi.categorize_operation("s", payload) == {"updated": 2, "rule": "nouveau commerce"}
    assert rows[4][3:6] == ["Shopping", "Divers", "depense"] and rows[5][3:6] == ["Shopping", "Divers", "depense"]
    assert tabs["Règles budget"].rows[-1][:4] == ["exacte", "nouveau commerce", "Shopping", "Divers"]
    # Un revenu prend sa sous-catégorie comme catégorie ; la ligne a changé depuis : refus
    assert bi.categorize_operation("s", {**payload, "category": "Revenus", "subcategory": "Remboursement", "remember": False})["updated"] == 1
    assert rows[4][3:6] == ["Remboursement", "", "revenu"]
    with pytest.raises(OperationError, match="a changé"):
        bi.categorize_operation("s", {**payload, "amount": 99})
    with pytest.raises(OperationError, match="Choisis une catégorie"):
        bi.categorize_operation("s", {**payload, "category": "À catégoriser"})


def test_ancien_envoi_depuis_le_pc_refuse_une_fois_drive_configure(monkeypatch):
    # La tâche Windows de 21 h remplacerait tout l'onglet Budget par outputs.xlsx, qui n'est plus mis à jour
    from fastapi.testclient import TestClient

    from app import main, notifications
    from app.users import User

    monkeypatch.setattr(main, "resolve", lambda token: User("Enzo", None, "s", admin=True))
    monkeypatch.setattr(notifications, "get_setting", lambda s, k: "dossier" if k == "budget_folder" else None)
    response = TestClient(main.app).post("/budget/import", json={"operations": [{"date": "2026-10-01"}]})
    assert response.status_code == 400 and "Drive" in response.json()["detail"]
