from datetime import date

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
