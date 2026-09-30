from datetime import date

import pytest

from app.cash import cash_summary, pea_deposits
from app.costs import pea_ceiling
from app.duplicates import Entry, same_operation
from app.imports import parse_trade_republic_csv
from app.realized import CashMovement, Operation

ENVELOPES = {"PEA Boursorama": "PEA", "CTO Trade Republic": "CTO"}


def op(day, account, kind, net):
    return Operation(date.fromisoformat(day), account, kind, "AAA", 1, net, 0.0, 0.0, net)


def cash(day, account, kind, amount):
    return CashMovement(date.fromisoformat(day), account, kind, amount)


def test_solde_des_especes():
    # Versé 1 000 €, acheté pour 600 €, vendu 250 €, dividende 10 €, intérêts 2 €, retrait 100 € :
    # 1 000 - 600 + 250 + 10 + 2 - 100 = 562 €
    ops = [op("2026-01-05", "CTO Trade Republic", "Achat", 600), op("2026-03-01", "CTO Trade Republic", "Vente", 250),
           op("2026-04-01", "CTO Trade Republic", "Dividende", 10)]
    moves = [cash("2026-01-05", "CTO Trade Republic", "Versement", 1000), cash("2026-05-01", "CTO Trade Republic", "Intérêts", 2),
             cash("2026-06-01", "CTO Trade Republic", "Retrait", 100)]
    result = cash_summary(ops, moves, ENVELOPES)
    account = result["accounts"][0]
    assert account["balance"] == pytest.approx(562) and account["missing"] == 0
    assert (account["deposits"], account["withdrawals"], account["interest"]) == (1000, 100, 2)
    assert result["envelopes"] == {"CTO": 562} and result["total"] == 562


def test_versement_le_jour_meme_passe_avant_l_achat():
    # Achat de 500 € le jour du versement de 500 € : jamais de solde négatif
    ops = [op("2026-01-05", "CTO Trade Republic", "Achat", 500)]
    result = cash_summary(ops, [cash("2026-01-05", "CTO Trade Republic", "Versement", 500)], ENVELOPES)
    assert result["accounts"][0]["missing"] == 0


def test_versements_incomplets_signales():
    # Versement de 300 € mais achats de 1 000 € le 10/01 : il manque au moins 700 € versés avant le 10/01
    ops = [op("2026-01-10", "PEA Boursorama", "Achat", 1000)]
    result = cash_summary(ops, [cash("2026-01-02", "PEA Boursorama", "Versement", 300)], ENVELOPES)
    account = result["accounts"][0]
    assert account["missing"] == pytest.approx(700) and account["missing_before"] == "2026-01-10"
    assert result["total"] == 0  # solde négatif : pas compté dans les espèces


def test_compte_sans_versement_non_suivi():
    ops = [op("2026-01-10", "PEA Boursorama", "Achat", 1000)]
    result = cash_summary(ops, [], ENVELOPES)
    assert result["accounts"] == [] and result["untracked"] == ["PEA Boursorama"]


def test_plafond_pea_sur_les_versements_reels():
    # Achats nets de 800 € (estimation) mais 5 000 € réellement versés : le plafond suit les versements
    ops = [op("2026-01-10", "PEA Boursorama", "Achat", 800)]
    moves = [cash("2026-01-02", "PEA Boursorama", "Versement", 5000), cash("2026-02-01", "PEA Boursorama", "Retrait", 1000),
             cash("2026-01-02", "CTO Trade Republic", "Versement", 999)]
    deposits = pea_deposits(moves, ENVELOPES)
    assert deposits == 5000  # un retrait ne libère pas de plafond ; le CTO ne compte pas
    ceiling = pea_ceiling(ops, ENVELOPES, date(2026, 6, 1), deposits)
    assert ceiling["deposits"] == 5000 and ceiling["remaining"] == 145000 and ceiling["estimated"] is False
    assert pea_ceiling(ops, ENVELOPES, date(2026, 6, 1))["estimated"] is True


def test_doublon_d_especes_meme_jour_meme_montant():
    a = Entry(date(2026, 8, 18), "CTO", "Retrait", "", 1, 4.0)
    assert same_operation(a, Entry(date(2026, 8, 18), "CTO", "Retrait", "", 1, 4.0))
    # Même café le lendemain : une autre dépense, pas un doublon (tolérance de dates des achats non appliquée)
    assert not same_operation(a, Entry(date(2026, 8, 19), "CTO", "Retrait", "", 1, 4.0))
    assert not same_operation(a, Entry(date(2026, 8, 18), "CTO", "Retrait", "", 1, 4.5))


HEADER = '"datetime","date","account_type","category","type","asset_class","name","symbol","shares","price","amount","fee","tax","currency"\n'


def test_trade_republic_csv_regroupe_les_especes():
    # 18/08 : virement reçu de 500 €, deux paiements par carte (4 € et 12,50 €) ; 01/09 : intérêts 1,20 €
    # dont 0,38 € de prélèvements ; PEA : versement de 200 € le 18/08
    rows = [
        '"","2026-08-18","DEFAULT","CASH","CUSTOMER_INBOUND","","","","","","500.00","","","EUR"',
        '"","2026-08-18","DEFAULT","CASH","CARD_TRANSACTION","","CAFE","","","","-4.00","","","EUR"',
        '"","2026-08-18","DEFAULT","CASH","CARD_TRANSACTION","","LIBRAIRIE","","","","-12.50","","","EUR"',
        '"","2026-08-18","PEA","CASH","CUSTOMER_INBOUND","","","","","","200.00","","","EUR"',
        '"","2026-09-01","DEFAULT","CASH","INTEREST_PAYMENT","","","","","","1.20","","-0.38","EUR"',
    ]
    ops = parse_trade_republic_csv(HEADER + "\n".join(rows) + "\n", "tr.csv")
    summary = [(o.date, o.envelope, o.type, o.price, o.name) for o in ops]
    assert summary == [
        ("2026-08-18", "CTO", "Versement", 500.0, "Espèces (1 mouvement)"),
        ("2026-08-18", "CTO", "Retrait", 16.5, "Espèces (2 mouvements)"),
        ("2026-08-18", "PEA", "Versement", 200.0, "Espèces (1 mouvement)"),
        ("2026-09-01", "CTO", "Intérêts", 0.82, "Espèces (1 mouvement)"),
    ]
