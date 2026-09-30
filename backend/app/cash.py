"""
Espèces de chaque compte, déduites de l'onglet Opérations (septembre 2026) :
solde = versements - retraits + intérêts - achats + ventes + dividendes (montants nets, frais compris).

Le solde n'est juste que si tous les versements depuis l'ouverture du compte sont saisis. Signe qui ne
trompe pas : un solde qui passe sous zéro à un moment (on ne peut pas acheter avec de l'argent qu'on n'a
pas versé). Le plus bas atteint donne le minimum qui manque ; le compte est alors marqué incomplet.
Un compte sans aucun versement n'est pas suivi (l'utilisateur n'a pas activé le suivi des espèces).

Chez Trade Republic, le compte titres est aussi un compte courant : paiements par carte et virements
sortants sont des retraits, et son solde est celui de l'appli Trade Republic.
"""

from collections import defaultdict

TOLERANCE = 1.0  # euros : arrondis des frais et des conversions, pas un versement manquant

# Le même jour, l'argent entre avant d'être dépensé (versement puis achat)
ORDER = {"Versement": 0, "Intérêts": 1, "Dividende": 2, "Vente": 3, "Achat": 4, "Retrait": 5}


def cash_summary(operations, cash, envelopes: dict[str, str]) -> dict:
    """operations : achats, ventes, dividendes (realized.Operation) ; cash : versements, retraits, intérêts
    (realized.CashMovement). Solde de chaque compte suivi et totaux par enveloppe."""
    events = defaultdict(list)  # compte -> [(jour, ordre, montant signé, type)]
    for op in operations:
        events[op.account].append((op.day, ORDER[op.kind], -op.net if op.kind == "Achat" else op.net, op.kind))
    for m in cash:
        events[m.account].append((m.day, ORDER[m.kind], -m.amount if m.kind == "Retrait" else m.amount, m.kind))

    tracked = {m.account for m in cash if m.kind == "Versement"}
    accounts = []
    for account in sorted(tracked):
        balance = lowest = 0.0
        lowest_day = None
        totals = defaultdict(float)
        for day, _, amount, kind in sorted(events[account], key=lambda e: (e[0], e[1])):
            balance += amount
            totals[kind] += abs(amount)
            if balance < lowest:
                lowest, lowest_day = balance, day
        missing = -lowest if lowest < -TOLERANCE else 0.0
        accounts.append({
            "account": account, "envelope": envelopes.get(account, "CTO"), "balance": round(balance, 2),
            "deposits": round(totals["Versement"], 2), "withdrawals": round(totals["Retrait"], 2),
            "interest": round(totals["Intérêts"], 2),
            # Versements manquants : au moins ce montant avant cette date (solde négatif impossible)
            "missing": round(missing, 2), "missing_before": lowest_day.isoformat() if missing else None,
        })
    by_envelope = defaultdict(float)
    for a in accounts:
        by_envelope[a["envelope"]] += max(a["balance"], 0.0)
    return {"accounts": accounts, "envelopes": {e: round(v, 2) for e, v in sorted(by_envelope.items())},
            "total": round(sum(by_envelope.values()), 2),
            "untracked": sorted({op.account for op in operations} - tracked)}


def pea_deposits(cash, envelopes: dict[str, str]) -> float | None:
    """Versements réels sur le PEA, quand ils sont saisis (sinon le plafond est estimé à partir des achats).
    Un retrait avant 5 ans ferme le plan ; après, il ne libère pas de plafond : seuls les versements comptent."""
    deposits = [m.amount for m in cash if m.kind == "Versement" and envelopes.get(m.account) == "PEA"]
    return round(sum(deposits), 2) if deposits else None
