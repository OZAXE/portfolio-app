"""
Lecture de ton Google Sheet "Investissement".

Pour que ça marche, il faut un compte de service Google (fichier JSON de
credentials) partagé en lecture sur ta feuille. C'est la méthode standard
pour qu'un script accède à un Google Sheet sans passer par ton compte perso.
Doc rapide pour le créer : console.cloud.google.com > IAM & Admin >
Service Accounts > créer une clé JSON, puis partager le Sheet avec l'email
du compte de service (ça ressemble à un email, genre xxx@xxx.iam.gserviceaccount.com).

Onglets lus :
- Portefeuille : TICKER (format Yahoo) / QUANTITE / ENVELOPPE, pour les analyses
- Courbe : une ligne par position (valeur, investi, plus-value, secteur), enveloppe en colonne A
- Historique : un relevé par colonne (date, perf et valeur PEA / CTO / total)
- Livret : épargne réglementée (nom, montant), facultatif
"""

import os
from dataclasses import dataclass, field
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SHEET_ID = "11yHfADl5DfjJo0cnGAFIE452OZvkkKi3VI32LBQvpJM"  # fileId de ton Sheet "Investissement"

# Origine des dates en valeur brute dans Google Sheets (comme Excel)
SHEETS_EPOCH = date(1899, 12, 30)

# Ligne de chaque série dans l'onglet Historique (index 0), chaque bloc occupant 2 lignes fusionnées
HISTORY_ROWS = {
    "date": 0,
    "pea_pct": 2,
    "pea_value": 4,
    "cto_pct": 6,
    "cto_value": 8,
    "total_pct": 10,
    "total_value": 12,
}

# Préfixes de place GOOGLEFINANCE -> suffixes Yahoo
GOOGLE_TO_YAHOO_SUFFIX = {
    "EPA": ".PA",
    "AMS": ".AS",
    "EBR": ".BR",
    "ETR": ".DE",
    "XETRA": ".DE",
    "FRA": ".F",
    "BIT": ".MI",
    "BME": ".MC",
    "SWX": ".SW",
    "LON": ".L",
    "NASDAQ": "",
    "NYSE": "",
    "NYSEARCA": "",
}

UNFORMATTED = gspread.utils.ValueRenderOption.unformatted


class SheetNotConfiguredError(RuntimeError):
    """Identifiants du compte de service absents : l'API renvoie une 503 plutôt qu'une 500."""


@dataclass
class Position:
    ticker: str
    quantity: float
    envelope: str | None = None  # PEA / CTO


@dataclass
class HoldingLine:
    ticker: str  # format GOOGLEFINANCE, tel qu'écrit dans le Sheet
    yahoo_ticker: str | None
    envelope: str | None
    value: float | None
    invested: float | None
    gain: float | None
    gain_pct: float | None
    sector: str | None


@dataclass
class HistoryPoint:
    date: str  # ISO
    pea_value: float | None = None
    pea_pct: float | None = None
    cto_value: float | None = None
    cto_pct: float | None = None
    total_value: float | None = None
    total_pct: float | None = None


@dataclass
class Overview:
    holdings: list[HoldingLine] = field(default_factory=list)
    history: list[HistoryPoint] = field(default_factory=list)
    savings: list[dict] = field(default_factory=list)


def _open_sheet() -> gspread.Spreadsheet:
    creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path:
        raise SheetNotConfiguredError(
            "Variable d'environnement GOOGLE_SERVICE_ACCOUNT_JSON manquante "
            "(chemin vers le fichier de credentials du compte de service)."
        )
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(SHEET_ID)


def _worksheet(sheet: gspread.Spreadsheet, name: str) -> gspread.Worksheet:
    try:
        return sheet.worksheet(name)
    except gspread.WorksheetNotFound:
        raise SheetNotConfiguredError(f"onglet \"{name}\" introuvable dans le Google Sheet")


def get_portfolio_positions(worksheet_name: str = "Portefeuille") -> list[Position]:
    ws = _worksheet(_open_sheet(), worksheet_name)
    # Valeurs brutes : en formaté, un Sheet en français renvoie "0,97" que float() refuse
    rows = ws.get_all_records(value_render_option=UNFORMATTED)

    positions = []
    for row in rows:
        ticker = row.get("TICKER") or row.get("Ticker")
        quantity = row.get("QUANTITE") or row.get("Quantité")
        envelope = row.get("ENVELOPPE") or row.get("Enveloppe")
        if ticker and quantity:
            positions.append(
                Position(ticker=str(ticker).strip(), quantity=float(quantity), envelope=envelope)
            )
    return positions


def google_to_yahoo(ticker: str) -> str | None:
    """EPA:AI -> AI.PA, NASDAQ:NVDA -> NVDA. None si la place n'est pas connue."""
    if ":" not in ticker:
        return ticker
    exchange, symbol = ticker.split(":", 1)
    suffix = GOOGLE_TO_YAHOO_SUFFIX.get(exchange.upper())
    return None if suffix is None else symbol + suffix


def _cell(rows: list[list], r: int, c: int):
    if r >= len(rows) or c >= len(rows[r]):
        return None
    value = rows[r][c]
    return None if value == "" else value


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _serial_to_iso(value) -> str | None:
    if isinstance(value, (int, float)):
        return (SHEETS_EPOCH + timedelta(days=int(value))).isoformat()
    return None


def parse_holdings(rows: list[list]) -> list[HoldingLine]:
    """Onglet Courbe : en-tête ligne 1, puis une position par ligne jusqu'à la première
    ligne sans ticker en colonne B. L'enveloppe (colonne A) est fusionnée sur plusieurs
    lignes, donc seule la première porte la valeur : on la propage vers le bas. La
    fusion "PEA" démarre sur la ligne d'en-tête (A1), d'où l'initialisation."""
    holdings = []
    envelope = _cell(rows, 0, 0)
    for r in range(1, len(rows)):
        ticker = _cell(rows, r, 1)
        if not ticker:
            break
        envelope = _cell(rows, r, 0) or envelope
        ticker = str(ticker).strip()
        holdings.append(
            HoldingLine(
                ticker=ticker,
                yahoo_ticker=google_to_yahoo(ticker),
                envelope=envelope,
                value=_number(_cell(rows, r, 2)),
                invested=_number(_cell(rows, r, 3)),
                gain=_number(_cell(rows, r, 4)),
                gain_pct=_number(_cell(rows, r, 5)),
                sector=_cell(rows, r, 6),
            )
        )
    return holdings


def parse_history(rows: list[list]) -> list[HistoryPoint]:
    """Onglet Historique : un relevé par colonne à partir de B, séries aux lignes de HISTORY_ROWS."""
    if str(_cell(rows, 0, 0) or "").strip().lower() != "date":
        raise ValueError("onglet Historique : \"Date\" attendu en A1, structure inconnue")
    width = max((len(row) for row in rows), default=0)
    points = []
    for c in range(1, width):
        iso = _serial_to_iso(_cell(rows, HISTORY_ROWS["date"], c))
        if iso is None:
            continue
        point = HistoryPoint(date=iso)
        for name, r in HISTORY_ROWS.items():
            if name != "date":
                setattr(point, name, _number(_cell(rows, r, c)))
        points.append(point)
    return sorted(points, key=lambda p: p.date)


def parse_savings(rows: list[list]) -> list[dict]:
    """Onglet Livret : nom en colonne A, montant en colonne B (lignes fusionnées ignorées)."""
    savings = []
    for r in range(len(rows)):
        name, amount = _cell(rows, r, 0), _number(_cell(rows, r, 1))
        if name and amount is not None:
            savings.append({"name": str(name).strip(), "amount": amount})
    return savings


def get_overview() -> Overview:
    sheet = _open_sheet()
    courbe = _worksheet(sheet, "Courbe").get_values(value_render_option=UNFORMATTED)
    historique = _worksheet(sheet, "Historique").get_values(value_render_option=UNFORMATTED)
    overview = Overview(holdings=parse_holdings(courbe), history=parse_history(historique))
    try:
        overview.savings = parse_savings(sheet.worksheet("Livret").get_values(value_render_option=UNFORMATTED))
    except gspread.WorksheetNotFound:
        pass  # onglet facultatif
    return overview
