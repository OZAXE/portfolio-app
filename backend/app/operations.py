"""
Saisie d'opérations (achat, vente, dividende, division, versement...) depuis l'appli dans le Sheet modèle (v2).

- read_settings() : comptes, barèmes de frais et titres connus, pour pré-remplir le formulaire ;
- add_operation() : ajoute une ligne à l'onglet Opérations (montants en formules, comme à la main)
  et, pour un titre jamais acheté, sa ligne dans l'onglet Titres (ticker Google pour GOOGLEFINANCE,
  devise de cotation, type), retrouvée auprès de Yahoo.

Les frais et taxes sont proposés par l'appli (barème de l'onglet Frais, TTF) mais c'est la valeur
envoyée, éventuellement corrigée par l'utilisateur, qui est enregistrée.
"""

import re
from dataclasses import dataclass
from datetime import date

from .sheets import SHEETS_EPOCH, UNFORMATTED, _find_worksheet, _open_sheet, _worksheet
from .workbook import (CASH_TYPES, OPERATION_TYPES, ORDER_TYPES, SHARE_TYPES, cash_row, ensure_operation_types,
                       operation_row)

# Suffixe Yahoo -> préfixe de place GOOGLEFINANCE
YAHOO_TO_GOOGLE_EXCHANGE = {
    ".PA": "EPA", ".L": "LON", ".DE": "ETR", ".AS": "AMS", ".MI": "BIT", ".MC": "BME", ".SW": "SWX",
    ".BR": "EBR", ".ST": "STO", ".CO": "CPH", ".HE": "HEL", ".OL": "OSL", ".LS": "ELI", ".IR": "ISE",
    ".VI": "VIE", ".T": "TYO", ".HK": "HKG", ".KS": "KRX", ".TW": "TPE",
}
# Codes de place Yahoo des marchés américains -> GOOGLEFINANCE
US_EXCHANGES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NYQ": "NYSE", "ASE": "NYSEAMERICAN", "PCX": "NYSEARCA", "BTS": "BATS"}


class OperationError(ValueError):
    """Donnée invalide dans le formulaire (renvoyée en 400 par l'API)."""


@dataclass
class TickerInfo:
    google: str
    name: str
    currency: str
    kind: str  # "Action" ou "ETF"


def _records(ws, width: int) -> list[list]:
    rows = ws.get_values(value_render_option=UNFORMATTED)[1:]
    return [(row + [""] * width)[:width] for row in rows if row and row[0] != ""]


def read_settings(sheet_id: str) -> dict:
    sheet = _open_sheet(sheet_id)
    if _find_worksheet(sheet, "Opérations") is None:
        raise OperationError("La saisie d'opérations nécessite le Sheet modèle (onglet Opérations)")
    accounts = [{"name": a, "envelope": e, "broker": b} for a, e, b in _records(_worksheet(sheet, "Comptes"), 3)]
    fees = [
        {"broker": b, "order_type": t, "fixed": f or 0, "percent": p or 0, "minimum": m or 0, "fx_percent": x or 0}
        for b, t, f, p, m, x, _ in _records(_worksheet(sheet, "Frais"), 7)
    ]
    titres = [
        {"ticker": t, "google": g, "name": n, "sector": s, "zone": z, "currency": c, "kind": k}
        for t, g, n, s, z, c, k in _records(_worksheet(sheet, "Titres"), 7)
    ]
    # Quantités détenues par compte : le formulaire en déduit les actions reçues lors d'une division
    held = held_quantities(_operation_records(sheet))
    holdings = [{"account": a, "ticker": t, "quantity": round(q, 6)} for (a, t), q in sorted(held.items()) if q > 1e-9]
    return {"accounts": accounts, "fees": fees, "titres": titres, "holdings": holdings,
            "operation_types": OPERATION_TYPES, "order_types": ORDER_TYPES}


def describe_for_titres(ticker: str) -> TickerInfo:
    """Ticker Google, nom, devise de cotation et type d'un nouveau titre, via l'API chart de Yahoo."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    history = t.history(period="5d")
    meta = t.history_metadata or {}
    if history.empty or not meta.get("symbol"):
        raise OperationError(f"Ticker inconnu chez Yahoo : {ticker} (format attendu : MC.PA, SAP.DE, AAPL, BTC-EUR...)")
    crypto = re.fullmatch(r"([A-Z0-9]{2,10})-(EUR|USD)", ticker.upper())
    if crypto or meta.get("instrumentType") == "CRYPTOCURRENCY":
        base, quote = crypto.groups() if crypto else (ticker.upper().split("-")[0], meta.get("currency") or "EUR")
        name = (meta.get("longName") or meta.get("shortName") or base).replace(f" {quote}", "")
        return TickerInfo(google=f"CURRENCY:{base}{quote}", name=name, currency=quote, kind="Crypto")
    suffix = next((s for s in YAHOO_TO_GOOGLE_EXCHANGE if ticker.upper().endswith(s)), None)
    if suffix:
        google = f"{YAHOO_TO_GOOGLE_EXCHANGE[suffix]}:{ticker[: -len(suffix)]}"
    else:
        google = f"{US_EXCHANGES.get(meta.get('exchangeName'), 'NASDAQ')}:{ticker}".replace("-", ".")
    return TickerInfo(
        google=google,
        name=meta.get("longName") or meta.get("shortName") or ticker,
        currency=meta.get("currency") or "EUR",
        kind="ETF" if meta.get("instrumentType") == "ETF" else "Action",
    )


def _positive(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OperationError(f"{label} invalide")
    if number <= 0:
        raise OperationError(f"{label} doit être positif")
    return number


def _non_negative(value, label: str) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        raise OperationError(f"{label} invalide")
    if number < 0:
        raise OperationError(f"{label} ne peut pas être négatif")
    return number


def _operation_records(sheet, exclude_row: int | None = None) -> list[list]:
    """Lignes de l'onglet Opérations (5 premières colonnes), sans la ligne en cours de modification : une vente
    corrigée ne doit pas se compter elle-même dans la quantité disponible."""
    rows = _worksheet(sheet, "Opérations").get_values(value_render_option=UNFORMATTED)[1:]
    return [(row + [""] * 5)[:5] for i, row in enumerate(rows, start=2) if row and row[0] != "" and i != exclude_row]


def _target_row(sheet, row: int | None) -> int:
    """Ligne à écrire : celle modifiée, sinon la première ligne libre."""
    return row or len(_worksheet(sheet, "Opérations").col_values(1)) + 1


def add_operation(sheet_id: str, payload: dict, sector: str = "", zone: str = "", row: int | None = None) -> dict:
    """Valide et enregistre une opération. Renvoie la ligne écrite (numéro et montant brut).
    row : ligne existante à remplacer (modification depuis l'écran Transactions)."""
    sheet = _open_sheet(sheet_id, write=True)
    settings = read_settings(sheet_id)
    accounts = {a["name"] for a in settings["accounts"]}

    kind = payload.get("type")
    if kind not in OPERATION_TYPES:
        raise OperationError(f"Type d'opération invalide (attendu : {', '.join(OPERATION_TYPES)})")
    account = payload.get("account")
    if account not in accounts:
        raise OperationError("Compte inconnu : ajoute-le d'abord dans l'onglet Comptes du Sheet")
    if kind in CASH_TYPES:
        return _add_cash(sheet, payload, kind, account, row)
    if kind in SHARE_TYPES:
        return _add_shares(sheet, payload, kind, account, row)
    order_type = payload.get("order_type") or "Ordre"
    if order_type not in ORDER_TYPES:
        raise OperationError("Type d'ordre invalide")
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not ticker:
        raise OperationError("Ticker manquant")
    when = _operation_date(payload)

    quantity = _positive(payload.get("quantity"), "Quantité")
    price = _positive(payload.get("price"), "Prix unitaire")
    fx = _positive(payload.get("fx") or 1, "Taux de change")
    fees = _non_negative(payload.get("fees"), "Frais")
    taxes = _non_negative(payload.get("taxes"), "Taxes")
    currency = str(payload.get("currency") or "EUR").strip()

    if kind == "Vente":
        held = sum(q for (_, t), q in held_quantities(_operation_records(sheet, row)).items() if t == ticker)
        if quantity > held + 1e-9:
            raise OperationError(f"Vente impossible : seulement {held:g} {ticker} en portefeuille")

    # Nouveau titre : ligne dans Titres pour que Positions trouve son cours (GOOGLEFINANCE)
    known = {t["ticker"].upper() for t in settings["titres"]}
    if ticker not in known:
        info = describe_for_titres(ticker)
        if info.kind == "Crypto":
            sector, zone = sector or "Crypto", zone or "Monde"
        titres = _worksheet(sheet, "Titres")
        next_row = len(titres.col_values(1)) + 1
        titres.update(range_name=f"A{next_row}", values=[[ticker, info.google, info.name, sector, zone, info.currency, info.kind]])

    ops = _worksheet(sheet, "Opérations")
    row = _target_row(sheet, row)
    op = {
        "date": when, "account": account, "type": kind, "ticker": ticker, "quantity": quantity,
        "price": price, "currency": currency, "fx": fx, "fees": fees, "taxes": taxes,
        "order_type": order_type, "why": payload.get("why") or "", "term": payload.get("term") or "",
        "note": payload.get("note") or "",
    }
    ops.update(range_name=f"A{row}", values=[operation_row(op, row)], value_input_option="USER_ENTERED")
    return {"row": row, "gross_eur": round(quantity * price * fx, 2), "new_ticker": ticker not in known}


def _operation_date(payload: dict) -> date:
    try:
        when = date.fromisoformat(payload.get("date") or date.today().isoformat())
    except ValueError:
        raise OperationError("Date invalide (format AAAA-MM-JJ)")
    if when > date.today():
        raise OperationError("La date ne peut pas être dans le futur")
    return when


def _add_cash(sheet, payload: dict, kind: str, account: str, row: int | None = None) -> dict:
    """Versement, retrait ou intérêts : seulement une date, un compte et un montant en euros."""
    when = _operation_date(payload)
    amount = _positive(payload.get("amount") or payload.get("price"), "Montant")
    taxes = _non_negative(payload.get("taxes"), "Impôts prélevés") if kind == "Intérêts" else 0.0
    if taxes > amount:
        raise OperationError("Les impôts prélevés dépassent le montant brut des intérêts")
    ensure_operation_types(sheet)
    ops = _worksheet(sheet, "Opérations")
    row = _target_row(sheet, row)
    ops.update(range_name=f"A{row}", values=[cash_row(when, account, kind, amount, payload.get("note") or "", row, taxes)],
               value_input_option="USER_ENTERED")
    return {"row": row, "gross_eur": round(amount, 2), "new_ticker": False}


def _add_shares(sheet, payload: dict, kind: str, account: str, row: int | None = None) -> dict:
    """Division ou actions gratuites : actions reçues sans rien payer (négatif pour un regroupement), sur un
    titre détenu dans ce compte à cette date. Prix, frais et taxes à 0 : le coût total ne change pas."""
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not ticker:
        raise OperationError("Ticker manquant")
    when = _operation_date(payload)
    try:
        quantity = float(payload.get("quantity"))
    except (TypeError, ValueError):
        raise OperationError("Nombre d'actions reçues invalide")
    held = held_quantities(_operation_records(sheet, row), until=when).get((account, ticker), 0.0)
    if held <= 1e-9:
        raise OperationError(f"Aucune action {ticker} sur le compte {account} le {when.strftime('%d/%m/%Y')}")
    if not quantity or (kind == "Actions gratuites" and quantity < 0):
        raise OperationError("Le nombre d'actions reçues doit être positif")
    if held + quantity <= 1e-9:
        raise OperationError(f"Regroupement impossible : il ne resterait aucune action (tu en as {held:g})")
    ensure_operation_types(sheet)
    ops = _worksheet(sheet, "Opérations")
    row = _target_row(sheet, row)
    op = {"date": when, "account": account, "type": kind, "ticker": ticker, "quantity": quantity, "price": 0,
          "currency": "EUR", "fx": 1, "order_type": "", "why": "", "term": "",
          "note": payload.get("note") or f"{held:g} -> {held + quantity:g} actions"}
    ops.update(range_name=f"A{row}", values=[operation_row(op, row)], value_input_option="USER_ENTERED")
    return {"row": row, "gross_eur": 0.0, "new_ticker": False}


def held_quantities(rows: list[list], until: date | None = None) -> dict[tuple[str, str], float]:
    """(compte, titre) -> quantité détenue d'après les lignes de l'onglet Opérations (date en numéro de série),
    toutes ou jusqu'au jour `until` compris : achats et actions reçues moins ventes."""
    held: dict[tuple[str, str], float] = {}
    last = (until - SHEETS_EPOCH).days if until else None
    for row in rows:
        if not isinstance(row[4], (int, float)) or row[2] not in ("Achat", "Vente", *SHARE_TYPES):
            continue
        if last is not None and not (isinstance(row[0], (int, float)) and row[0] <= last):
            continue
        key = (str(row[1]).strip(), str(row[3]).strip().upper())
        held[key] = held.get(key, 0.0) + (-row[4] if row[2] == "Vente" else row[4])
    return held
