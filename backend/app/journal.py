"""
Journal de trading (octobre 2026, demande d'Enzo) : pour chaque titre, pourquoi on l'achète, à quel cours on
compte vendre (objectif), à quel cours on s'avoue qu'on s'est trompé (stop), et après la vente, le bilan.
Relire ses thèses face à ce qui s'est passé est ce qui fait progresser, bien plus qu'un indicateur de plus.

Onglet « Journal » du Sheet, créé au premier enregistrement (comme la Watchlist) : une ligne par titre.
Objectif et stop sont dans la devise de cotation, comme les alertes de prix, que l'appli propose de créer
sur ces deux cours. Les motifs de chaque achat restent dans les colonnes Pourquoi et Terme des Opérations.
"""

from datetime import date

from .notifications import _tab
from .operations import OperationError

JOURNAL_TAB = "Journal"
JOURNAL_HEADERS = ["Ticker", "Thèse", "Objectif", "Stop", "Horizon", "Revoir le", "Bilan", "Mis à jour"]
HORIZONS = ("", "Court", "Moyen", "Long")
MAX_TEXT = 2000


def _price(value, label: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", ".").replace(" ", "").replace(" ", ""))
    except ValueError:
        raise OperationError(f"{label} invalide")
    if number <= 0:
        raise OperationError(f"{label} doit être positif")
    return number


def _day(value) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise OperationError("Date de revue invalide (format AAAA-MM-JJ)")


def parse_journal(rows: list[list]) -> list[dict]:
    """Lignes de l'onglet (sans l'en-tête). Un prix illisible (saisi à la main dans le Sheet) est ignoré."""
    entries = []
    for row in rows:
        row = (list(row) + [""] * 8)[:8]
        ticker = str(row[0]).strip().upper()
        if not ticker:
            continue
        prices = []
        for value in (row[2], row[3]):
            try:
                prices.append(_price(value, "Prix"))
            except OperationError:
                prices.append(None)
        entries.append({"ticker": ticker, "thesis": str(row[1]), "target": prices[0], "stop": prices[1],
                        "horizon": str(row[4]).strip(), "review": str(row[5]).strip()[:10], "outcome": str(row[6]),
                        "updated": str(row[7]).strip()[:10]})
    return entries


def list_journal(sheet_id: str) -> list[dict]:
    ws = _tab(sheet_id, JOURNAL_TAB, JOURNAL_HEADERS, create=False)
    return parse_journal(ws.get_values()[1:]) if ws is not None else []


def journal_row(payload: dict, today: date) -> list:
    """Ligne validée : objectif au-dessus du stop, textes limités à 2 000 caractères."""
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not ticker:
        raise OperationError("Ticker manquant")
    target, stop = _price(payload.get("target"), "Objectif"), _price(payload.get("stop"), "Stop")
    if target is not None and stop is not None and stop >= target:
        raise OperationError("Le stop doit être sous l'objectif")
    horizon = str(payload.get("horizon") or "").strip()
    if horizon not in HORIZONS:
        raise OperationError("Horizon invalide (Court, Moyen ou Long)")
    thesis, outcome = str(payload.get("thesis") or "").strip(), str(payload.get("outcome") or "").strip()
    if not thesis and not outcome and target is None and stop is None:
        raise OperationError("Écris au moins ta thèse, un objectif ou un stop")
    return [ticker, thesis[:MAX_TEXT], target if target is not None else "", stop if stop is not None else "",
            horizon, _day(payload.get("review")), outcome[:MAX_TEXT], today.isoformat()]


def save_entry(sheet_id: str, payload: dict, today: date | None = None) -> list[dict]:
    """Crée ou remplace la ligne du titre (une thèse par titre)."""
    row = journal_row(payload, today or date.today())
    ws = _tab(sheet_id, JOURNAL_TAB, JOURNAL_HEADERS, create=True)
    tickers = [str(t).strip().upper() for t in ws.col_values(1)]
    # Nombres écrits bruts (RAW) : le Sheet les affiche selon sa langue, la lecture les retrouve
    if row[0] in tickers[1:]:
        ws.update(range_name=f"A{tickers.index(row[0], 1) + 1}", values=[row], value_input_option="RAW")
    else:
        ws.append_row(row, value_input_option="RAW")
    return list_journal(sheet_id)


def delete_entry(sheet_id: str, ticker: str) -> list[dict]:
    ws = _tab(sheet_id, JOURNAL_TAB, JOURNAL_HEADERS, create=False)
    if ws is None:
        return []
    ticker = ticker.strip().upper()
    column = ws.col_values(1)
    for row in range(len(column), 1, -1):  # de bas en haut : les numéros restent valables
        if str(column[row - 1]).strip().upper() == ticker:
            ws.delete_rows(row)
    return list_journal(sheet_id)
