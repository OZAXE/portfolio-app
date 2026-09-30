"""
Repérage des opérations en double : à l'import (une opération déjà dans le Sheet n'est pas réécrite)
et dans l'onglet Opérations (outil « Rechercher les doublons », pour nettoyer un import en trop).

Deux lignes décrivent la même opération quand elles ont le même type et la même enveloppe, des dates
à quelques jours près (saisie à la main à la date de l'ordre, relevé à la date d'exécution...) et :
- achat ou vente : une quantité à 1 % près, et le même titre ou un montant à 3 % près (un titre
  saisi sous un autre ticker, TNO.PA / TNOW.MI, reste reconnu) ;
- dividende : le même titre (montant brut ou net selon la source, quantité parfois inconnue).

Cas à part, les achats sans date précise : la migration de l'ancien Sheet a daté du 5 mai 2026 les
achats antérieurs au suivi (note « Date à préciser »), parfois regroupés en une ligne. Quand des
relevés importés contiennent les vrais achats datés du même titre, la ligne provisoire fait double
emploi : elle est proposée à la suppression si les imports couvrent au moins sa quantité.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from .operations import OperationError
from .sheets import SHEETS_EPOCH, UNFORMATTED, _open_sheet, _worksheet

DATE_TOLERANCE_DAYS = 4
LOOSE_DATE_TOLERANCE_DAYS = 45  # dates approximatives saisies à la main : proposé, jamais coché d'office
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
    net: float | None = None  # intérêts : montant net (brut - prélèvements), comparé aussi


def _base(ticker: str) -> str:
    return ticker.upper().split(".")[0].split("-")[0]


CASH_KINDS = ("Versement", "Retrait", "Intérêts")


def same_operation(a: Entry, b: Entry, days: int = DATE_TOLERANCE_DAYS, same_ticker_only: bool = False) -> bool:
    if a.kind != b.kind or a.envelope != b.envelope:
        return False
    # Espèces : même jour et même montant au centime (deux cafés à 4 € deux jours de suite sont deux dépenses)
    if a.kind in CASH_KINDS:
        # Intérêts importés avant septembre 2026 : enregistrés nets, réimportés bruts -> brut ou net suffit
        amounts_a = {a.amount} | ({a.net} if a.net is not None else set())
        amounts_b = {b.amount} | ({b.net} if b.net is not None else set())
        return a.day == b.day and any(abs(x - y) < 0.005 for x in amounts_a for y in amounts_b)
    if abs((a.day - b.day).days) > days:
        return False
    same_ticker = bool(a.ticker and b.ticker and (a.ticker.upper() == b.ticker.upper() or _base(a.ticker) == _base(b.ticker)))
    if same_ticker_only and not same_ticker:
        return False
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


def find_duplicate_pairs(entries: list[Entry], days: int = DATE_TOLERANCE_DAYS, same_ticker_only: bool = False,
                         used: set | None = None) -> list[tuple[Entry, Entry]]:
    """(ligne gardée, ligne en trop) : la copie à supprimer est de préférence une ligne importée
    (note « Import … »), sinon la plus récente dans l'onglet."""
    pairs, used = [], used if used is not None else set()
    for i, a in enumerate(entries):
        if a.row in used:
            continue
        for b in entries[i + 1:]:
            if b.row in used or not same_operation(a, b, days, same_ticker_only):
                continue
            keep, extra = (b, a) if a.note.startswith("Import") and not b.note.startswith("Import") else (a, b)
            pairs.append((keep, extra))
            used.update({a.row, b.row})
            break
    return pairs


UNDATED_NOTE = "Date à préciser"


def find_undated_replacements(entries: list[Entry], extra_rows: set[int]) -> list[dict]:
    """Achats « Date à préciser » et achats importés datés du même titre et de la même enveloppe
    (hors lignes déjà proposées comme doublons) : complete si les imports couvrent la quantité."""
    results = []
    for p in entries:
        if p.kind != "Achat" or UNDATED_NOTE not in p.note:
            continue
        imported = [e for e in entries if e.kind == "Achat" and e.note.startswith("Import") and e.envelope == p.envelope
                    and e.row not in extra_rows and (e.ticker == p.ticker or _base(e.ticker) == _base(p.ticker))]
        covered = sum(e.quantity for e in imported)
        results.append({"placeholder": _describe(p), "covered": round(covered, 6), "imports": len(imported),
                        "complete": covered >= p.quantity * (1 - QUANTITY_TOLERANCE)})
    return results


def _describe(e: Entry) -> dict:
    return {"row": e.row, "date": e.day.isoformat(), "account": e.account, "type": e.kind, "ticker": e.ticker,
            "quantity": e.quantity, "amount": round(e.amount, 2), "note": e.note}


def list_duplicates(sheet_id: str) -> dict:
    entries = read_entries(_open_sheet(sheet_id))
    # Les lignes « Date à préciser » ne se comparent pas par date : traitées à part
    dated = [e for e in entries if UNDATED_NOTE not in e.note]
    used: set = set()
    pairs = find_duplicate_pairs(dated, used=used)
    # Puis, parmi les autres, le même titre et la même quantité à quelques semaines d'écart
    loose = find_duplicate_pairs(dated, LOOSE_DATE_TOLERANCE_DAYS, same_ticker_only=True, used=used)
    describe = lambda keep, extra: {"keep": _describe(keep), "extra": _describe(extra), "days": abs((keep.day - extra.day).days)}
    return {"pairs": [describe(k, x) for k, x in pairs], "loose": [describe(k, x) for k, x in loose],
            "undated": [u for u in find_undated_replacements(entries, {x.row for _, x in pairs + loose}) if u["imports"]]}


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
