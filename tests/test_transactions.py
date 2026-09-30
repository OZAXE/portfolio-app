"""Écran Transactions : liste de l'onglet Opérations, modification et suppression contrôlées par empreinte."""

from datetime import date

import pytest

from app import transactions
from app.operations import OperationError
from app.sheets import SHEETS_EPOCH


def serial(d):
    return (d - SHEETS_EPOCH).days


ROWS = [
    [serial(date(2025, 3, 1)), "PEA Bourso", "Achat", "ai.pa", 3, 160, "EUR", 1, 480, 2, 0, 482, "Ordre", "Renforcement", "Long", ""],
    [serial(date(2025, 9, 1)), "CTO TR", "Vente", "NVDA", 1, 150, "USD", 0.9, 135, 1, 0, 134, "Ordre", "", "", ""],
    ["", "", "", "", "", ""],  # ligne vide au milieu de l'onglet
    [serial(date(2025, 9, 1)), "CTO TR", "Versement", "", 1, 500, "EUR", 1, 500, 0, 0, 500, "", "", "", "Virement"],
]


def test_liste_des_transactions_recentes_d_abord():
    items = transactions.parse_transactions(ROWS, {"AI.PA": "Air Liquide"})
    # Même jour : la ligne la plus basse de l'onglet (saisie en dernier) d'abord
    assert [(t["row"], t["type"]) for t in items] == [(5, "Versement"), (3, "Vente"), (2, "Achat")]
    achat = items[-1]
    assert achat["date"] == "2025-03-01" and achat["ticker"] == "AI.PA" and achat["name"] == "Air Liquide"
    assert achat["net"] == 482 and achat["why"] == "Renforcement" and achat["term"] == "Long"
    assert achat["key"] == f"{serial(date(2025, 3, 1))}|Achat|AI.PA|3|160"


class FakeOps:
    def __init__(self, rows):
        self.rows, self.deleted = rows, []

    def get_values(self, range_name=None, value_render_option=None):
        row = int(range_name[1:range_name.index(":")])
        return [self.rows[row - 2]] if 2 <= row < len(self.rows) + 2 else []

    def delete_rows(self, row):
        self.deleted.append(row)


@pytest.fixture
def sheet(monkeypatch):
    tab = FakeOps(ROWS)
    monkeypatch.setattr(transactions, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(transactions, "_worksheet", lambda s, name: tab)
    return tab


def test_suppression_verifie_l_empreinte(sheet):
    key = transactions.fingerprint(ROWS[1])
    assert transactions.delete_transaction("sheet", 3, key) == {"deleted": 1}
    assert sheet.deleted == [3]
    # Le Sheet a changé (ligne insérée au-dessus) : la ligne 3 n'est plus la vente, rien n'est supprimé
    with pytest.raises(OperationError, match="a changé"):
        transactions.delete_transaction("sheet", 2, key)
    assert sheet.deleted == [3]


def test_modification_reecrit_la_meme_ligne(sheet, monkeypatch):
    calls = []
    monkeypatch.setattr(transactions, "add_operation", lambda *args, **kw: calls.append((args, kw)) or {"row": kw["row"]})
    payload = {"type": "Achat", "ticker": "AI.PA", "quantity": 3, "price": 158}
    assert transactions.update_transaction("sheet", 2, transactions.fingerprint(ROWS[0]), payload) == {"row": 2}
    assert calls[0][1] == {"row": 2} and calls[0][0][1] == payload
    with pytest.raises(OperationError):
        transactions.update_transaction("sheet", 2, "autre", payload)
    assert len(calls) == 1
