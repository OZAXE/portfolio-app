"""
Budget (octobre 2026, demande d'Enzo, réservé à l'administrateur) : les comptes du mois tirés du relevé du compte
courant. La catégorisation reste faite sur le PC d'Enzo par sa tâche mensuelle (update_suivi.py, règles apprises,
validation des opérations « À catégoriser » avec Claude) ; scripts/envoyer_budget.py lit ensuite outputs.xlsx et
envoie toutes les opérations ici. L'appli ne fait que les ranger et les afficher.

Onglet « Budget » du Sheet, créé au premier envoi : une ligne par opération. Chaque envoi **remplace** tout
l'onglet : le script envoie la liste complète, donc une opération reclassée le mois suivant (sortie de
« À catégoriser ») change de catégorie ici aussi, et un envoi refait après un échec ne crée pas de doublon. Pas de
dédoublonnage par date + libellé + montant : deux virements de 100 € vers Boursorama le même jour sont deux
opérations réelles (cas du 08/08/2026).

Les mois sont faits par le front d'après la date de chaque opération : outputs.xlsx n'a pas besoin d'être trié.
"""

import math
from collections import defaultdict
from datetime import date

from .notifications import _tab
from .operations import OperationError

BUDGET_TAB = "Budget"
BUDGET_HEADERS = ["Date", "Libellé", "Montant", "Catégorie", "Sous-catégorie", "Type", "Envoyé le"]
# depense / revenu comptent dans le solde ; interne (entre ses propres comptes) et investissement sont affichés à
# part, comme dans le Résumé d'outputs.xlsx ; a_categoriser compte dans les dépenses en attendant d'être classé.
KINDS = ("depense", "revenu", "interne", "investissement", "a_categoriser")
MAX_OPERATIONS = 20_000  # ~900 opérations par an : plus de 20 ans de relevés
MAX_TEXT = 300
MAX_AMOUNT = 1_000_000


def _text(value, label: str, limit: int, required: bool = True) -> str:
    text = " ".join(str(value or "").split())  # libellés du CA sur plusieurs lignes (prélèvements SEPA)
    if required and not text:
        raise OperationError(f"{label} manquant")
    return text[:limit]


def _day(value) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise OperationError(f"Date invalide : {value!r} (format AAAA-MM-JJ)")


def _amount(value) -> float:
    try:
        number = float(str(value).replace(",", ".").replace(" ", "").replace(" ", ""))
    except ValueError:
        raise OperationError(f"Montant invalide : {value!r}")
    if not math.isfinite(number) or abs(number) > MAX_AMOUNT:
        raise OperationError(f"Montant invalide : {value!r}")
    return round(number, 2)


def budget_row(op: dict, sent: str) -> list:
    """Opération validée, dans l'ordre des colonnes de l'onglet."""
    kind = str(op.get("kind") or "").strip()
    if kind not in KINDS:
        raise OperationError(f"Type invalide : {kind!r} ({', '.join(KINDS)})")
    return [_day(op.get("date")), _text(op.get("label"), "Libellé", MAX_TEXT), _amount(op.get("amount")),
            _text(op.get("category"), "Catégorie", 60), _text(op.get("subcategory"), "Sous-catégorie", 60, required=False),
            kind, sent]


def parse_budget(rows: list[list]) -> list[dict]:
    """Lignes de l'onglet (sans l'en-tête). Une ligne abîmée à la main dans le Sheet est ignorée."""
    operations = []
    for row in rows:
        row = (list(row) + [""] * 7)[:7]
        try:
            day, amount = _day(row[0]), _amount(row[2])
        except OperationError:
            continue
        kind = str(row[5]).strip()
        if kind not in KINDS:
            continue
        operations.append({"date": day, "label": str(row[1]), "amount": amount, "category": str(row[3]),
                           "subcategory": str(row[4]), "kind": kind})
    return operations


def deposits_by_month(cash) -> dict[str, float]:
    """Versements saisis dans l'onglet Opérations, par mois (AAAA-MM), tous comptes confondus : le front les compare
    aux virements « Investissement » du relevé pour repérer un versement oublié."""
    months = defaultdict(float)
    for move in cash:
        if move.kind == "Versement":
            months[move.day.isoformat()[:7]] += move.amount
    return {m: round(v, 2) for m, v in sorted(months.items())}


def read_budget(sheet_id: str, cash=()) -> dict:
    ws = _tab(sheet_id, BUDGET_TAB, BUDGET_HEADERS, create=False)
    rows = ws.get_values()[1:] if ws is not None else []
    sent = max((str(r[6])[:10] for r in rows if len(r) > 6 and r[6]), default=None)
    return {"operations": parse_budget(rows), "sent": sent, "deposits": deposits_by_month(cash)}


def replace_budget(sheet_id: str, payload: dict, today: date | None = None) -> dict:
    """Remplace tout l'onglet par les opérations envoyées.

    Garde-fou : un envoi qui contient moins de la moitié des opérations déjà rangées est refusé sans
    `force` (un outputs.xlsx tronqué ou le mauvais fichier ne doit pas effacer des mois de relevés)."""
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise OperationError("Aucune opération envoyée")
    if len(operations) > MAX_OPERATIONS:
        raise OperationError(f"Trop d'opérations ({len(operations)}, {MAX_OPERATIONS} au plus)")
    sent = (today or date.today()).isoformat()
    rows = []
    for i, op in enumerate(operations, 1):
        if not isinstance(op, dict):
            raise OperationError(f"Opération {i} illisible")
        try:
            rows.append(budget_row(op, sent))
        except OperationError as e:
            raise OperationError(f"Opération {i} : {e}")
    rows.sort(key=lambda r: r[0], reverse=True)
    ws = _tab(sheet_id, BUDGET_TAB, BUDGET_HEADERS, create=True)
    stored = max(0, len(ws.col_values(1)) - 1)
    if not payload.get("force") and len(rows) < stored / 2:
        raise OperationError(f"Envoi refusé : {len(rows)} opérations alors que l'onglet Budget en contient {stored}. "
                             "Vérifie que c'est le bon fichier, ou renvoie avec --force pour remplacer quand même.")
    ws.clear()
    ws.resize(rows=len(rows) + 1, cols=len(BUDGET_HEADERS))
    # Écrit brut (RAW) : un libellé qui commence par « = » reste du texte, jamais une formule
    ws.update(range_name="A1", values=[BUDGET_HEADERS] + rows, value_input_option="RAW")
    months = sorted({r[0][:7] for r in rows})
    return {"count": len(rows), "first": rows[-1][0], "last": rows[0][0], "months": len(months),
            "to_categorize": sum(r[5] == "a_categoriser" for r in rows), "sent": sent}
