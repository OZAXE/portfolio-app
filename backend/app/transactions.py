"""
Écran Transactions : les lignes de l'onglet Opérations, à voir, corriger ou supprimer depuis l'appli (avant,
une faute de frappe sur un prix obligeait à ouvrir le Google Sheet).

Une ligne est désignée par son numéro dans l'onglet, qui change si quelqu'un insère ou supprime une ligne dans
le Sheet entre l'affichage et l'action. L'appli renvoie donc aussi l'empreinte de la ligne affichée (date,
type, titre, quantité, prix) : si la ligne ne correspond plus, rien n'est écrit ni supprimé.
"""

from .operations import OperationError, add_operation
from .sheets import UNFORMATTED, _open_sheet, _serial_to_iso, _worksheet

WIDTH = 16  # colonnes A à P de workbook.OPERATIONS_HEADERS


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def fingerprint(row: list) -> str:
    """Empreinte d'une ligne : date, type, titre, quantité, prix (ex. « 45901|Achat|AI.PA|3|160 »)."""
    row = (list(row) + [""] * 6)[:6]
    number = lambda v: f"{v:g}" if isinstance(v, (int, float)) else str(v).strip()
    return "|".join([number(row[0]), str(row[2]).strip(), str(row[3]).strip().upper(), number(row[4]), number(row[5])])


def parse_transactions(rows: list[list], names: dict[str, str]) -> list[dict]:
    """Lignes de l'onglet Opérations (sans l'en-tête) -> transactions, les plus récentes d'abord. Les lignes
    sans date lisible (ligne vide, texte) sont écartées. Montant net : colonne L, calculée par le Sheet."""
    result = []
    for i, row in enumerate(rows, start=2):
        row = (list(row) + [""] * WIDTH)[:WIDTH]
        day = _serial_to_iso(row[0])
        if not day or not str(row[2]).strip():
            continue
        ticker = str(row[3]).strip().upper()
        result.append({
            "row": i, "key": fingerprint(row), "date": day, "account": str(row[1]).strip(), "type": str(row[2]).strip(),
            "ticker": ticker, "name": names.get(ticker, ticker), "quantity": _number(row[4]), "price": _number(row[5]),
            "currency": str(row[6] or "EUR").strip(), "fx": _number(row[7]), "gross": _number(row[8]),
            "fees": _number(row[9]) or 0.0, "taxes": _number(row[10]) or 0.0, "net": _number(row[11]),
            "order_type": str(row[12]).strip(), "why": str(row[13]).strip(), "term": str(row[14]).strip(),
            "note": str(row[15]).strip(),
        })
    return sorted(result, key=lambda t: (t["date"], t["row"]), reverse=True)


def list_transactions(sheet_id: str) -> dict:
    sheet = _open_sheet(sheet_id)
    rows = _worksheet(sheet, "Opérations").get_values(value_render_option=UNFORMATTED)[1:]
    titres = _worksheet(sheet, "Titres").get_values(value_render_option=UNFORMATTED)[1:]
    names = {str(r[0]).strip().upper(): str(r[2]).strip() for r in titres if len(r) > 2 and r[0] and r[2]}
    return {"transactions": parse_transactions(rows, names)}


def _check(sheet, row: int, key: str) -> None:
    """La ligne `row` est-elle toujours celle affichée dans l'appli ?"""
    if row < 2:
        raise OperationError("Ligne invalide")
    values = _worksheet(sheet, "Opérations").get_values(f"A{row}:F{row}", value_render_option=UNFORMATTED)
    if not values or fingerprint(values[0]) != key:
        raise OperationError("L'onglet Opérations a changé depuis l'affichage : recharge la liste des transactions")


def update_transaction(sheet_id: str, row: int, key: str, payload: dict, sector: str = "", zone: str = "") -> dict:
    """Remplace la ligne par l'opération corrigée, avec les mêmes contrôles qu'une saisie (quantité détenue
    pour une vente, sans compter la ligne elle-même)."""
    _check(_open_sheet(sheet_id, write=True), row, key)
    return add_operation(sheet_id, payload, sector, zone, row=row)


def delete_transaction(sheet_id: str, row: int, key: str) -> dict:
    sheet = _open_sheet(sheet_id, write=True)
    _check(sheet, row, key)
    _worksheet(sheet, "Opérations").delete_rows(row)
    return {"deleted": 1}
