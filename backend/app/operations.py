"""
Saisie d'opérations (achat, vente, dividende) depuis l'appli dans le Sheet modèle (format v2).

- read_settings() : comptes, barèmes de frais et titres connus, pour pré-remplir le formulaire ;
- add_operation() : ajoute une ligne à l'onglet Opérations (montants en formules, comme à la main)
  et, pour un titre jamais acheté, sa ligne dans l'onglet Titres (ticker Google pour GOOGLEFINANCE,
  devise de cotation, type), retrouvée auprès de Yahoo.

Les frais et taxes sont proposés par l'appli (barème de l'onglet Frais, TTF) mais c'est la valeur
envoyée, éventuellement corrigée par l'utilisateur, qui est enregistrée.
"""

from dataclasses import dataclass
from datetime import date

from .sheets import UNFORMATTED, _find_worksheet, _open_sheet, _worksheet
from .workbook import OPERATION_TYPES, ORDER_TYPES, operation_row

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
    return {"accounts": accounts, "fees": fees, "titres": titres,
            "operation_types": OPERATION_TYPES, "order_types": ORDER_TYPES}


def describe_for_titres(ticker: str) -> TickerInfo:
    """Ticker Google, nom, devise de cotation et type d'un nouveau titre, via l'API chart de Yahoo."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    history = t.history(period="5d")
    meta = t.history_metadata or {}
    if history.empty or not meta.get("symbol"):
        raise OperationError(f"Ticker inconnu chez Yahoo : {ticker} (format attendu : MC.PA, SAP.DE, AAPL...)")
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


def add_operation(sheet_id: str, payload: dict, sector: str = "", zone: str = "") -> dict:
    """Valide et enregistre une opération. Renvoie la ligne écrite (numéro et montant brut)."""
    sheet = _open_sheet(sheet_id, write=True)
    settings = read_settings(sheet_id)
    accounts = {a["name"] for a in settings["accounts"]}

    kind = payload.get("type")
    if kind not in OPERATION_TYPES:
        raise OperationError(f"Type d'opération invalide (attendu : {', '.join(OPERATION_TYPES)})")
    account = payload.get("account")
    if account not in accounts:
        raise OperationError("Compte inconnu : ajoute-le d'abord dans l'onglet Comptes du Sheet")
    order_type = payload.get("order_type") or "Ordre"
    if order_type not in ORDER_TYPES:
        raise OperationError("Type d'ordre invalide")
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not ticker:
        raise OperationError("Ticker manquant")
    try:
        when = date.fromisoformat(payload.get("date") or date.today().isoformat())
    except ValueError:
        raise OperationError("Date invalide (format AAAA-MM-JJ)")
    if when > date.today():
        raise OperationError("La date ne peut pas être dans le futur")

    quantity = _positive(payload.get("quantity"), "Quantité")
    price = _positive(payload.get("price"), "Prix unitaire")
    fx = _positive(payload.get("fx") or 1, "Taux de change")
    fees = _non_negative(payload.get("fees"), "Frais")
    taxes = _non_negative(payload.get("taxes"), "Taxes")
    currency = str(payload.get("currency") or "EUR").strip()

    if kind == "Vente":
        held = _held_quantity(sheet, ticker)
        if quantity > held + 1e-9:
            raise OperationError(f"Vente impossible : seulement {held:g} {ticker} en portefeuille")

    # Nouveau titre : ligne dans Titres pour que Positions trouve son cours (GOOGLEFINANCE)
    known = {t["ticker"].upper() for t in settings["titres"]}
    if ticker not in known:
        info = describe_for_titres(ticker)
        titres = _worksheet(sheet, "Titres")
        next_row = len(titres.col_values(1)) + 1
        titres.update(range_name=f"A{next_row}", values=[[ticker, info.google, info.name, sector, zone, info.currency, info.kind]])

    ops = _worksheet(sheet, "Opérations")
    row = len(ops.col_values(1)) + 1
    op = {
        "date": when, "account": account, "type": kind, "ticker": ticker, "quantity": quantity,
        "price": price, "currency": currency, "fx": fx, "fees": fees, "taxes": taxes,
        "order_type": order_type, "why": payload.get("why") or "", "term": payload.get("term") or "",
        "note": payload.get("note") or "",
    }
    ops.update(range_name=f"A{row}", values=[operation_row(op, row)], value_input_option="USER_ENTERED")
    return {"row": row, "gross_eur": round(quantity * price * fx, 2), "new_ticker": ticker not in known}


def _held_quantity(sheet, ticker: str) -> float:
    held = 0.0
    for row in _records(_worksheet(sheet, "Opérations"), 5):
        if str(row[3]).upper() != ticker or not isinstance(row[4], (int, float)):
            continue
        if row[2] == "Achat":
            held += row[4]
        elif row[2] == "Vente":
            held -= row[4]
    return held
