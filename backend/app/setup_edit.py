"""
Modification depuis l'appli de ce qui se réglait dans le Sheet :
- comptes (onglet Comptes : nom, enveloppe PEA / CTO, courtier) et grilles de frais (onglet Frais),
  pour ajouter n'importe quelle banque ;
- allocation cible (onglet Allocation : poche, cible) et poche de chaque titre (colonne Poche de Titres) ;
- épargne saisie à la main (onglet Épargne : livrets, assurance-vie, PER).
"""

from datetime import date

from .operations import OperationError, _records
from .sheets import _find_worksheet, _open_sheet, _worksheet
from .workbook import ORDER_TYPES

ENVELOPES = ("PEA", "CTO")
POCKET_COLUMN = "H"  # colonne Poche de l'onglet Titres


def _text(value, label: str, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise OperationError(f"{label} manquant")
    if len(text) > max_length or text.startswith(("=", "+", "@")):
        raise OperationError(f"{label} invalide : {text[:40]}")
    return text


def _number(value, label: str, maximum: float) -> float:
    try:
        number = float(str(value if value not in (None, "") else 0).replace(",", "."))
    except ValueError:
        raise OperationError(f"{label} invalide")
    if not 0 <= number <= maximum:
        raise OperationError(f"{label} doit être entre 0 et {maximum:g}")
    return number


def _rewrite(ws, width_letter: str, rows: list[list]) -> None:
    """Remplace les lignes de données (à partir de la ligne 2) sans toucher à l'en-tête."""
    ws.batch_clear([f"A2:{width_letter}"])
    if rows:
        ws.update(range_name="A2", values=rows, value_input_option="RAW")


# --- Épargne saisie à la main : livrets, assurance-vie, PER (onglet Épargne, ancien onglet Livret) ---
def validate_savings(lines: list[dict], today: date) -> list[list]:
    """Nom, valeur, type, montant versé (facultatif, pour la plus-value d'une assurance-vie) et date de la
    valeur : celle envoyée par l'appli, qui la met à aujourd'hui quand la valeur change."""
    from .sheets import SAVINGS_TYPES

    rows, names = [], set()
    for line in lines:
        name = _text(line.get("name"), "Nom", 60)
        if name.startswith("-"):  # écrit en USER_ENTERED : serait lu comme une formule
            raise OperationError(f"Nom invalide : {name}")
        if name.lower() in names:
            raise OperationError(f"{name} : nom en double")
        names.add(name.lower())
        kind = line.get("type") or "Livret"
        if kind not in SAVINGS_TYPES:
            raise OperationError(f"{name} : type attendu {', '.join(SAVINGS_TYPES)}")
        amount = _amount(line.get("amount"), f"{name} : valeur")
        invested = None if line.get("invested") in (None, "") else _amount(line.get("invested"), f"{name} : montant versé")
        updated = str(line.get("updated") or today.isoformat())
        try:
            if date.fromisoformat(updated) > today:
                raise ValueError
        except ValueError:
            raise OperationError(f"{name} : date de mise à jour invalide")
        rows.append([name, amount, kind, "" if invested is None else invested, updated])
    return rows


def _amount(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OperationError(f"{label} invalide")
    if number < 0 or number > 1e9:
        raise OperationError(f"{label} invalide")
    return round(number, 2)


def save_savings(sheet_id: str, lines: list[dict], today: date | None = None) -> dict:
    """Réécrit l'onglet Épargne. Un ancien onglet Livret est renommé et complété (ses lignes, lues comme des
    livrets, arrivent déjà dans `lines` : l'appli les affiche avant la sauvegarde)."""
    from .sheets import savings_worksheet
    from .workbook import SAVINGS_HEADERS

    rows = validate_savings(lines, today or date.today())
    sheet = _open_sheet(sheet_id, write=True)
    ws, extended = savings_worksheet(sheet)
    if ws is None:
        ws = sheet.add_worksheet("Épargne", rows=30, cols=len(SAVINGS_HEADERS))
    elif not extended:
        ws.update_title("Épargne")
        if ws.col_count < len(SAVINGS_HEADERS):
            ws.add_cols(len(SAVINGS_HEADERS) - ws.col_count)
    ws.update(range_name="A1", values=[SAVINGS_HEADERS])
    ws.batch_clear(["A2:E"])
    if rows:
        # USER_ENTERED : la date AAAA-MM-JJ devient une vraie date (noms déjà protégés contre les formules)
        ws.update(range_name="A2", values=rows, value_input_option="USER_ENTERED")
    return {"lines": len(rows)}


# --- Comptes ---
def validate_accounts(accounts: list[dict], used: set[str]) -> list[list]:
    rows, names = [], set()
    for a in accounts:
        name = _text(a.get("name"), "Nom du compte", 50)
        envelope = str(a.get("envelope") or "").upper()
        if envelope not in ENVELOPES:
            raise OperationError(f"{name} : enveloppe attendue PEA ou CTO")
        if name.lower() in names:
            raise OperationError(f"Deux comptes s'appellent « {name} »")
        names.add(name.lower())
        rows.append([name, envelope, _text(a.get("broker"), f"{name} : courtier", 40)])
    missing = sorted(u for u in used if u.lower() not in names)
    if missing:
        raise OperationError(f"Le compte « {missing[0]} » a des opérations : il ne peut pas être supprimé ni renommé")
    if not rows:
        raise OperationError("Garde au moins un compte")
    return rows


def save_accounts(sheet_id: str, accounts: list[dict]) -> list[dict]:
    sheet = _open_sheet(sheet_id, write=True)
    used = {str(r[1]).strip() for r in _records(_worksheet(sheet, "Opérations"), 2) if r[1]}
    rows = validate_accounts(accounts, used)
    _rewrite(_worksheet(sheet, "Comptes"), "C", rows)
    return [{"name": n, "envelope": e, "broker": b} for n, e, b in rows]


# --- Grilles de frais (pourcentages en fraction : 0,005 pour 0,5 %) ---
def validate_fees(fees: list[dict]) -> list[list]:
    rows, keys = [], set()
    for f in fees:
        broker = _text(f.get("broker"), "Courtier", 40)
        order_type = f.get("order_type") or "Ordre"
        if order_type not in ORDER_TYPES:
            raise OperationError(f"{broker} : type d'ordre invalide")
        if (broker.lower(), order_type) in keys:
            raise OperationError(f"{broker} : deux grilles pour « {order_type} »")
        keys.add((broker.lower(), order_type))
        note = " ".join(str(f.get("note") or "").split())[:200]
        rows.append([broker, order_type, _number(f.get("fixed"), f"{broker} : frais fixes", 100),
                     _number(f.get("percent"), f"{broker} : pourcentage", 0.1),
                     _number(f.get("minimum"), f"{broker} : minimum", 100),
                     _number(f.get("fx_percent"), f"{broker} : frais de change", 0.05),
                     note.lstrip("=+@")])
    return rows


def save_fees(sheet_id: str, fees: list[dict]) -> list[dict]:
    rows = validate_fees(fees)
    _rewrite(_worksheet(_open_sheet(sheet_id, write=True), "Frais"), "G", rows)
    return [{"broker": b, "order_type": t, "fixed": x, "percent": p, "minimum": m, "fx_percent": fx, "note": n}
            for b, t, x, p, m, fx, n in rows]


# --- Allocation cible (cibles en fraction : 0,6 pour 60 %) ---
def validate_allocation(targets: list[dict], pockets: dict) -> tuple[list[list], dict[str, str]]:
    rows, names = [], set()
    for t in targets:
        pocket = _text(t.get("pocket"), "Nom de poche", 40)
        if pocket.lower() in names:
            raise OperationError(f"Deux poches s'appellent « {pocket} »")
        names.add(pocket.lower())
        rows.append([pocket, _number(t.get("target"), f"{pocket} : cible", 1)])
    total = sum(r[1] for r in rows)
    if rows and abs(total - 1) > 0.005:
        raise OperationError(f"Tes cibles font {total * 100:.1f} % au total : elles doivent faire 100 %")
    assigned = {}
    for ticker, pocket in (pockets or {}).items():
        pocket = " ".join(str(pocket or "").split())
        if pocket and pocket.lower() not in names:
            raise OperationError(f"{ticker} : poche « {pocket} » sans cible")
        assigned[str(ticker).strip().upper()] = pocket
    return rows, assigned


def save_allocation(sheet_id: str, targets: list[dict], pockets: dict) -> dict:
    rows, assigned = validate_allocation(targets, pockets)
    sheet = _open_sheet(sheet_id, write=True)
    allocation = _find_worksheet(sheet, "Allocation")
    if allocation is None:  # Sheet créé avant l'onglet Allocation
        allocation = sheet.add_worksheet("Allocation", rows=50, cols=2)
        allocation.update(range_name="A1", values=[["Poche", "Cible %"]])
    _rewrite(allocation, "B", rows)
    if assigned:
        titres = _worksheet(sheet, "Titres")
        tickers = [str(t).strip().upper() for t in titres.col_values(1)]
        updates = [{"range": f"{POCKET_COLUMN}{tickers.index(t) + 1}", "values": [[p]]}
                   for t, p in assigned.items() if t in tickers]
        if updates:
            titres.batch_update(updates, value_input_option="RAW")
    return {"targets": len(rows), "pockets": len(assigned)}
