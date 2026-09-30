import re
from datetime import date

from app import workbook as wb
from app.workbook import UNDATED_DEFAULT, operation_row, parse_v1_movements

# Reproduction réduite de l'onglet Mouvement : bloc PEA avec une colonne "Avant" et un achat daté,
# bloc CTO avec montant en euros (prix déjà en euros chez Trade Republic)
ROWS = [
    ["PEA", "Action/RIB", "", "Avant"],
    ["", "", "", "", "", 46154],  # date (12/05/2026) au-dessus de la 2e colonne d'opérations
    ["", "EPA:ESE", 34.3, "Achat/vente", "Achat", "Achat/vente", "Achat"],
    ["", "", "", "Quantité", 10, "Quantité", 7],
    ["", "", "", "Prix", 27.93, "Prix", 31.96],
    ["", "", "", "Pourquoi", "", "Pourquoi", "Diversification"],
    ["", "", "", "Terme", "Long", "Terme", "Long"],
    ["CTO", "Action/RIB", "", "Avant"],
    [],
    ["", "NASDAQ:NVDA", 225.0, "Achat/vente", "Achat", "Achat/vente", ""],
    ["", "", "", "Combien €", 153.4289, "Combien €", ""],
    ["", "", "", "Prix d'achat", 158.15, "Prix d'achat", ""],
    ["", "", "", "Quantité", 0.970148, "Quantité", ""],
    ["", "", "", "Pourquoi", "", "Pourquoi", ""],
    ["", "", "", "Terme", "", "Terme", ""],
]


def test_v1_movements_parsed():
    ops = parse_v1_movements(ROWS)
    assert [(o["ticker"], o["account"], o["quantity"], o["date"]) for o in ops] == [
        ("ESE.PA", "PEA Boursorama", 10.0, UNDATED_DEFAULT),
        ("ESE.PA", "PEA Boursorama", 7.0, date(2026, 5, 12)),
        ("NVDA", "CTO Trade Republic", 0.970148, UNDATED_DEFAULT),
    ]
    assert ops[0]["note"].startswith("Date à préciser") and ops[1]["note"] == ""
    assert ops[2]["currency"] == "EUR" and ops[2]["fx"] == 1.0  # montant = quantité x prix


def test_operation_row_formulas_reference_their_row():
    op = parse_v1_movements(ROWS)[1]
    row = operation_row({**op, "currency": "EUR"}, 7)
    assert row[8] == "=E7*F7*H7"
    assert row[11] == '=IF(C7="Achat"; I7+J7+K7; I7-J7-K7)'


def test_positions_une_ligne_par_titre_et_par_compte():
    # Ticker (A) et compte (C) sortent du même tri de couples « ticker|compte » ; quantité et PRU par compte
    for cell in ("A2", "C2", "E2", "F2"):
        assert "Opérations!B2:B" in wb.POSITION_FORMULAS[cell]
    assert wb.POSITION_FORMULAS["A2"].replace("; 0; 1))", "; 0; 2))") == wb.POSITION_FORMULAS["C2"]
    assert not wb.is_old_positions_formula(wb.POSITION_FORMULAS["A2"])
    old = '=IFERROR(SORT(UNIQUE(FILTER(Opérations!D2:D; Opérations!D2:D<>""; (Opérations!C2:C="Achat")+(Opérations!C2:C="Vente")))); "")'
    assert wb.is_old_positions_formula(old)


class FakePositions:
    def __init__(self, formula, pru=None):
        self.title, self.formulas, self.updates = "Positions", {"A2": formula, "F2": pru or wb.POSITION_FORMULAS["F2"]}, []

    def acell(self, label, value_render_option=None):
        return type("Cell", (), {"value": self.formulas[label]})()

    def batch_update(self, data, value_input_option=None):
        self.updates.append(data)


def test_pru_rejoue_les_ventes():
    # Le PRU rejoue les opérations dans l'ordre (REDUCE) au lieu de moyenner tous les achats : Alphabet C
    # acheté 1 à 170,74 € frais compris, vendu, puis racheté 0,265 pour 78 € -> PRU 294 €, pas 197 €
    pru = wb.POSITION_FORMULAS["F2"]
    assert "REDUCE" in pru and '"Vente"' in pru and "Opérations!B2:B" in pru
    assert not wb.is_old_pru_formula(pru)
    old = ('=MAP(A2:A; C2:C; LAMBDA(t; c; IF(t=""; ""; IFERROR(SUMIFS(Opérations!L2:L; Opérations!D2:D; t; Opérations!B2:B; c;'
           ' Opérations!C2:C; "Achat") / SUMIFS(Opérations!E2:E; Opérations!D2:D; t; Opérations!B2:B; c; Opérations!C2:C; "Achat"); 0))))')
    assert wb.is_old_pru_formula(old)
    # Pas de nombre décimal écrit dans la formule : « 0.5 » ou « 0,5 » dépend du réglage régional du Sheet
    assert not re.search(r"\d[.,]\d", pru)


def test_ancien_pru_mis_a_niveau(monkeypatch):
    old_pru = '=MAP(A2:A; C2:C; LAMBDA(t; c; IF(t=""; ""; IFERROR(SUMIFS(Opérations!L2:L; Opérations!D2:D; t); 0))))'
    ws = FakePositions(wb.POSITION_FORMULAS["A2"], old_pru)
    client = type("Client", (), {"open_by_key": lambda self, key: key})()
    monkeypatch.setattr(wb, "sheets_client", lambda write=False: client)
    monkeypatch.setattr(wb, "_find_worksheet", lambda sheet, name: ws)
    monkeypatch.setattr(wb, "_positions_checked", set())
    wb.ensure_position_formulas("sheet")
    assert len(ws.updates) == 1 and {u["range"] for u in ws.updates[0]} == set(wb.POSITION_FORMULAS)


def test_ancien_sheet_mis_a_niveau_une_seule_fois(monkeypatch):
    old, current = FakePositions('=IFERROR(SORT(UNIQUE(FILTER(Opérations!D2:D; 1))); "")'), FakePositions(wb.POSITION_FORMULAS["A2"])
    sheets = {"ancien": old, "recent": current}
    client = type("Client", (), {"open_by_key": lambda self, key: key})()
    monkeypatch.setattr(wb, "sheets_client", lambda write=False: client)
    monkeypatch.setattr(wb, "_find_worksheet", lambda sheet, name: sheets[sheet])
    monkeypatch.setattr(wb, "_positions_checked", set())
    for _ in range(2):
        wb.ensure_position_formulas("ancien")
        wb.ensure_position_formulas("recent")
    assert len(old.updates) == 1 and {u["range"] for u in old.updates[0]} == set(wb.POSITION_FORMULAS)
    assert current.updates == []
