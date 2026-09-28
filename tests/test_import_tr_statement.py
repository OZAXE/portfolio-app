"""Relevé de compte PDF de Trade Republic (texte tel que le rend pypdf). Données fictives."""

import base64

import pytest

from app import imports
from app.imports import ParsedOperation, parse_trade_republic_statement, preview_import, route_accounts
from app.operations import OperationError

HEADER = """TRADE REPUBLIC BANK GMBH, BRANCH FRANCE   75 BOULEVARD HAUSSMANN 75008 PARIS
DATE 01 déc. 2025 - 27 sept. 2026
IBAN FR0000000000000000000000000
JEAN EXEMPLE
1 rue de l'Exemple
Directeurs Généraux
Généré le 2026-09-28 23:55:01 Europe/Paris (UTC+02:00) Page   {page} de 2
"""

STATEMENT = HEADER.format(page=1) + """SYNTHÈSE DU RELEVÉ DE COMPTE
PRODUIT SOLDE DÉBUT DE PÉRIODE ENTRÉE D'ARGENT SORTIE D'ARGENT SOLDE FIN DE PÉRIODE
Compte courant 0,00 € 1500,00 € 1400,00 € 100,00 €
TRANSACTIONS
DATE TYPE DESCRIPTION ENTRÉE
D'ARGENT
SORTIE
D'ARGENT SOLDE
08 déc.
2025 Virement Incoming transfer from JEAN EXEMPLE 1500,00 € 1500,00 €
10 déc.
2025
Exécution
d'ordre Buy trade US0000000001 EXEMPLE CORP. DL -,01, quantity: 2 201,00 € 1299,00 €
02
mars
2026
Exécution
d'ordre
Savings plan execution US0000000002 AUTRE SOCIETE INC.
DL-,01, quantity: 0.25 50,00 € 1249,00 €
02
mars
2026
Exécution
d'ordre Savings plan execution XF000BTC0017 Bitcoin, quantity: 0.0004 25,00 € 1224,00 €
""" + HEADER.format(page=2) + """DATE TYPE DESCRIPTION ENTRÉE
D'ARGENT
SORTIE
D'ARGENT SOLDE
09 avr.
2026 Rendement Cash Dividend for ISIN US0000000001 1,20 € 1225,20 €
30 avr.
2026
Exécution
d'ordre Sell trade US0000000001 EXEMPLE CORP. DL -,01, quantity: 1 1.099,00 € 2324,20 €
REMARQUES SUR LE RELEVÉ DE COMPTE
Les fonds sont protégés jusqu'à 100 000 € chacun.
""" + HEADER.format(page=1) + """SYNTHÈSE DU RELEVÉ DE COMPTE
PRODUIT SOLDE DÉBUT DE PÉRIODE ENTRÉE D'ARGENT SORTIE D'ARGENT SOLDE FIN DE PÉRIODE
Compte PEA 0,00 € 300,00 € 300,00 € 0,00 €
TRANSACTIONS
DATE TYPE DESCRIPTION ENTRÉE
D'ARGENT
SORTIE
D'ARGENT SOLDE
10
déc.
2025
Exécution d'ordre Buy trade FR0000000003 SOCIETE FRANCAISE SA, quantity: 3 151,00 € 0,00 €
20 mai
2026 Rendement Cash Dividend for ISIN FR0000000003 9,00 € 9,00 €
21 mai
2026 Opération sur titres Corporate actions - fractions for ISIN FR0000000003 12,00 € 21,00 €
REMARQUES SUR LE RELEVÉ DE COMPTE
"""


def test_statement_trades_dividends_and_accounts():
    skipped = {}
    ops = parse_trade_republic_statement(STATEMENT, "releve.pdf", skipped)
    summary = [(o.envelope, o.date, o.type, o.isin, o.quantity, o.price, o.fees, o.order_type) for o in ops]
    assert summary == [
        ("CTO", "2025-12-10", "Achat", "US0000000001", 2.0, 100.0, 1.0, "Ordre"),  # 201 € = 2 x 100 + 1 € de frais
        ("CTO", "2026-03-02", "Achat", "US0000000002", 0.25, 200.0, 0.0, "Plan d'investissement"),
        ("CTO", "2026-04-09", "Dividende", "US0000000001", 2.0, 0.6, 0.0, ""),  # 1,20 € pour 2 actions détenues
        ("CTO", "2026-04-30", "Vente", "US0000000001", 1.0, 1100.0, 1.0, "Ordre"),  # 1.099,00 € encaissés
        ("PEA", "2025-12-10", "Achat", "FR0000000003", 3.0, 50.0, 1.0, "Ordre"),
        ("PEA", "2026-05-20", "Dividende", "FR0000000003", 3.0, 3.0, 0.0, ""),
    ]
    assert ops[1].name == "AUTRE SOCIETE INC. DL-,01"  # nom sur deux lignes
    assert ops[2].name == "EXEMPLE CORP. DL -,01"  # nom repris de l'achat
    assert skipped == {"crypto": 1, "corporate": 1}


def test_statement_without_operations():
    with pytest.raises(OperationError, match="aucune opération"):
        parse_trade_republic_statement(HEADER.format(page=1) + "SYNTHÈSE DU RELEVÉ DE COMPTE TRANSACTIONS", "vide.pdf")


ACCOUNTS = [{"name": "CTO Trade Republic", "envelope": "CTO", "broker": "Trade Republic"},
            {"name": "PEA Boursorama", "envelope": "PEA", "broker": "Boursorama"},
            {"name": "PEA Trade Republic", "envelope": "PEA", "broker": "Trade Republic"}]


def op(envelope):
    return ParsedOperation("2026-01-01", "Achat", "X", "X", 1, 1, 0, 0, "Ordre", "f", envelope=envelope)


def test_route_accounts_prefers_same_broker():
    ops = [op("CTO"), op("PEA"), op(None)]
    route_accounts(ops, "CTO Trade Republic", ACCOUNTS)
    assert [o.account for o in ops] == ["CTO Trade Republic", "PEA Trade Republic", "CTO Trade Republic"]
    ops = [op("CTO")]
    route_accounts(ops, "PEA Boursorama", ACCOUNTS[1:])  # aucun CTO
    assert ops[0].account is None


def test_preview_statement_routes_pea_to_pea_account(monkeypatch):
    monkeypatch.setattr(imports, "read_operations", lambda sheet_id: ([], {}, {}))
    monkeypatch.setattr(imports, "find_ticker", lambda isin, known: isin[-4:])
    monkeypatch.setattr("app.operations.read_settings", lambda sheet_id: {"accounts": ACCOUNTS})
    monkeypatch.setattr(imports, "parse_file", lambda name, content, skipped: parse_trade_republic_statement(STATEMENT, name, skipped))
    result = preview_import("sheet", "CTO Trade Republic", [{"name": "releve.pdf", "content": base64.b64encode(b"%PDF").decode()}], {})
    accounts = {(o["type"], o["isin"], o["account"]) for o in result["operations"]}
    assert ("Achat", "FR0000000003", "PEA Trade Republic") in accounts
    assert ("Achat", "US0000000001", "CTO Trade Republic") in accounts
    assert result["counts"]["new"] == 6
    assert any("crypto" in e for e in result["errors"]) and any("opérations sur titres" in e for e in result["errors"])


def test_known_isin_symbols_are_valid_yahoo_tickers():
    from app.main import yahoo_symbol

    assert yahoo_symbol("RR/", ".L") == "RR.L"  # Rolls-Royce
    assert yahoo_symbol("BT/A", ".L") == "BT-A.L"
    assert yahoo_symbol("AI", ".PA") == "AI.PA"
