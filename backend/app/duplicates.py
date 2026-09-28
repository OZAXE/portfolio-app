"""
Repérage des opérations en double : à l'import (une opération déjà dans le Sheet n'est pas réécrite)
et dans l'onglet Opérations (outil « Rechercher les doublons », pour nettoyer un import en trop).

Deux lignes décrivent la même opération quand elles ont le même type et la même enveloppe, des dates
à quelques jours près (saisie à la main à la date de l'ordre, relevé à la date d'exécution...) et :
- achat ou vente : une quantité à 1 % près, et le même titre ou un montant à 3 % près (un titre
  saisi sous un autre ticker, TNO.PA / TNOW.MI, reste reconnu) ;
- dividende : le même titre (montant brut ou net selon la source, quantité parfois inconnue).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from .operations import OperationError
from .sheets import SHEETS_EPOCH, UNFORMATTED, _open_sheet, _worksheet

DATE_TOLERANCE_DAYS = 4
QUANTITY_TOLERANCE = 0.01
AMOUNT_TOLERANCE = 0.03


@dataclass
class Entry:
    day: date
    envelope: str
    kind: str  # Achat / Vente / Dividende
    ticker: str  # vide si inconnu
    quantity: float
    amount: float  # montant brut en euros
    row: int | None = None  # ligne de l'onglet Opérations
    account: str = ""
    note: str = ""
    source: str | None = None  # fichier d'origine d'une opération importée


def _base(ticker: str) -> str:
    return ticker.upper().split(".")[0].split("-")[0]


def same_operation(a: Entry, b: Entry) -> bool:
    if a.kind != b.kind or a.envelope != b.envelope or abs((a.day - b.day).days) > DATE_TOLERANCE_DAYS:
        return False
    same_ticker = bool(a.ticker and b.ticker and (a.ticker.upper() == b.ticker.upper() or _base(a.ticker) == _base(b.ticker)))
    if a.kind == "Dividende":
        return same_ticker
    if abs(a.quantity - b.quantity) > max(0.0005, QUANTITY_TOLERANCE * max(abs(a.quantity), abs(b.quantity))):
        return False
    close_amount = bool(a.amount and b.amount and abs(a.amount - b.amount) <= AMOUNT_TOLERANCE * max(a.amount, b.amount))
    return same_ticker or close_amount


def mark_duplicates(new: list[Entry], existing: list[Entry]) -> list[bool]:
    """Pour chaque nouvelle opération : déjà présente ? Une ligne existante ne sert qu'une fois (deux
    achats identiques le même jour restent deux achats) ; les nouvelles se comparent aussi à celles
    des autres fichiers du même import (le même ordre dans deux relevés), pas à celles du même fichier."""
    pool = list(existing)
    flags = []
    for entry in new:
        match = next((i for i, e in enumerate(pool)
                      if (e.source is None or e.source != entry.source) and same_operation(entry, e)), None)
        if match is None:
            flags.append(False)
        else:
            pool.pop(match)
            flags.append(True)
        pool.append(entry)
    return flags


# --- Doublons déjà présents dans l'onglet Opérations ---
def read_entries(sheet) -> list[Entry]:
    comptes = _worksheet(sheet, "Comptes").get_values(value_render_option=UNFORMATTED)[1:]
    envelopes = {str(r[0]).strip(): str(r[1]).strip().upper() for r in comptes if len(r) > 1 and r[0]}
    entries = []
    for i, row in enumerate(_worksheet(sheet, "Opérations").get_values(value_render_option=UNFORMATTED)[1:], start=2):
        row = (list(row) + [""] * 16)[:16]
        if not isinstance(row[0], (int, float)) or row[2] not in ("Achat", "Vente", "Dividende") or not isinstance(row[4], (int, float)):
            continue
        amount = row[8] if isinstance(row[8], (int, float)) else row[4] * (row[5] or 0) * (row[7] or 1)
        account = str(row[1]).strip()
        entries.append(Entry(day=SHEETS_EPOCH + timedelta(days=int(row[0])), envelope=envelopes.get(account, "CTO"),
                             kind=row[2], ticker=str(row[3]).strip().upper(), quantity=float(row[4]),
                             amount=float(amount or 0), row=i, account=account, note=str(row[15] or "")))
    return entries


def find_duplicate_pairs(entries: list[Entry]) -> list[tuple[Entry, Entry]]:
    """(ligne gardée, ligne en trop) : la copie à supprimer est de préférence une ligne importée
    (note « Import … »), sinon la plus récente dans l'onglet."""
    pairs, used = [], set()
    for i, a in enumerate(entries):
        if a.row in used:
            continue
        for b in entries[i + 1:]:
            if b.row in used or not same_operation(a, b):
                continue
            keep, extra = (b, a) if a.note.startswith("Import") and not b.note.startswith("Import") else (a, b)
            pairs.append((keep, extra))
            used.update({a.row, b.row})
            break
    return pairs


def _describe(e: Entry) -> dict:
    return {"row": e.row, "date": e.day.isoformat(), "account": e.account, "type": e.kind, "ticker": e.ticker,
            "quantity": e.quantity, "amount": round(e.amount, 2), "note": e.note}


def list_duplicates(sheet_id: str) -> list[dict]:
    pairs = find_duplicate_pairs(read_entries(_open_sheet(sheet_id)))
    return [{"keep": _describe(keep), "extra": _describe(extra)} for keep, extra in pairs]


def delete_operations(sheet_id: str, rows: list[dict]) -> dict:
    """Supprime des lignes de l'onglet Opérations. Chaque ligne est revérifiée (date, titre, quantité)
    avant suppression : si le Sheet a changé entre-temps, rien n'est supprimé."""
    sheet = _open_sheet(sheet_id, write=True)
    by_row = {e.row: e for e in read_entries(sheet)}
    targets = []
    for r in rows:
        entry = by_row.get(int(r.get("row") or 0))
        if (entry is None or entry.day.isoformat() != r.get("date") or entry.ticker != str(r.get("ticker") or "").upper()
                or abs(entry.quantity - float(r.get("quantity") or 0)) > 1e-9):
            raise OperationError("L'onglet Opérations a changé depuis la recherche : relance « Rechercher les doublons »")
        targets.append(entry)
    ws = _worksheet(sheet, "Opérations")
    for entry in sorted(targets, key=lambda e: -e.row):  # du bas vers le haut : les numéros restent valables
        ws.delete_rows(entry.row)
    earliest = min((e.day for e in targets), default=None)
    return {"deleted": len(targets), "earliest": earliest.isoformat() if earliest else None}
