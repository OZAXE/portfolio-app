"""
Alertes de prix personnelles et réglages de notification, rangés dans le Google Sheet de chaque
utilisateur (onglets créés au premier usage, comme la Watchlist) :
- « Alertes prix » : ID, TICKER, SENS (Sous / Au-dessus), PRIX (devise de cotation), NOTE,
  CRÉÉE LE, DÉCLENCHÉE LE. Une alerte déclenchée n'est plus vérifiée tant qu'on ne la réactive pas ;
- « Réglages » : clé / valeur, dont ntfy_topic, le sujet ntfy.sh où envoyer ses notifications.

Le job nocturne (screener/notify.py) vérifie les alertes sur les cours de clôture et envoie les
notifications de chaque utilisateur sur son propre sujet.
"""

import re
import secrets
from datetime import date

import gspread

from .operations import OperationError
from .sheets import _find_worksheet, _open_sheet

ALERTS_TAB = "Alertes prix"
ALERTS_HEADERS = ["ID", "TICKER", "SENS", "PRIX", "NOTE", "CRÉÉE LE", "DÉCLENCHÉE LE"]
SETTINGS_TAB = "Réglages"
DIRECTIONS = ("Sous", "Au-dessus")
# Un sujet ntfy.sh est public : quiconque le devine lit les notifications. 20 caractères au moins
# (« portfolio-enzo » se devine, le sujet généré par l'appli en fait 24, ex. portfolio-k3x9q2m1p8ab1c)
TOPIC_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def check_price_alerts(alerts: list[dict], prices: dict[str, float | None]) -> list[dict]:
    """Alertes actives dont la condition est remplie au cours donné. Fonction pure (job nocturne)."""
    triggered = []
    for alert in alerts:
        price = prices.get(alert["ticker"])
        if alert.get("triggered") or price is None:
            continue
        if (alert["direction"] == "Sous" and price <= alert["price"]) or (alert["direction"] == "Au-dessus" and price >= alert["price"]):
            triggered.append({**alert, "current": price})
    return triggered


def _tab(sheet_id: str, name: str, headers: list[str], create: bool, write: bool = False) -> gspread.Worksheet | None:
    sheet = _open_sheet(sheet_id, write=write or create)
    ws = _find_worksheet(sheet, name)
    if ws is None and create:
        ws = sheet.add_worksheet(name, rows=200, cols=len(headers))
        ws.update(range_name="A1", values=[headers])
    return ws


def list_price_alerts(sheet_id: str) -> list[dict]:
    ws = _tab(sheet_id, ALERTS_TAB, ALERTS_HEADERS, create=False)
    if ws is None:
        return []
    alerts = []
    for row in ws.get_values()[1:]:
        row = (row + [""] * 7)[:7]
        if not row[0] or not row[1]:
            continue
        try:
            price = float(str(row[3]).replace(",", ".").replace(" ", "").replace(" ", ""))
        except ValueError:
            continue
        alerts.append({"id": row[0], "ticker": row[1].strip().upper(), "direction": row[2] if row[2] in DIRECTIONS else "Sous",
                       "price": price, "note": row[4], "created": row[5], "triggered": row[6] or None})
    return alerts


def add_price_alert(sheet_id: str, ticker: str, direction: str, price, note: str = "") -> list[dict]:
    if direction not in DIRECTIONS:
        raise OperationError("Sens invalide (Sous ou Au-dessus)")
    try:
        price = float(price)
    except (TypeError, ValueError):
        raise OperationError("Prix invalide")
    if price <= 0:
        raise OperationError("Le prix doit être positif")
    ws = _tab(sheet_id, ALERTS_TAB, ALERTS_HEADERS, create=True)
    # Prix écrit en nombre brut : le Sheet l'affiche selon sa langue, la lecture le retrouve
    ws.append_row([secrets.token_hex(4), ticker, direction, price, str(note or "")[:200], date.today().isoformat(), ""],
                  value_input_option="RAW")
    return list_price_alerts(sheet_id)


def _find_row(ws: gspread.Worksheet, alert_id: str) -> int:
    ids = ws.col_values(1)
    for row, value in enumerate(ids, start=1):
        if row > 1 and value == alert_id:
            return row
    raise OperationError("Alerte introuvable")


def delete_price_alert(sheet_id: str, alert_id: str) -> list[dict]:
    ws = _tab(sheet_id, ALERTS_TAB, ALERTS_HEADERS, create=False, write=True)
    if ws is not None:
        ws.delete_rows(_find_row(ws, alert_id))
    return list_price_alerts(sheet_id)


def set_alert_triggered(sheet_id: str, alert_ids: list[str], day: str | None) -> list[dict]:
    """day : date de déclenchement (job nocturne), ou None pour réactiver l'alerte."""
    ws = _tab(sheet_id, ALERTS_TAB, ALERTS_HEADERS, create=False, write=True)
    if ws is None:
        return []
    for alert_id in alert_ids:
        ws.update_cell(_find_row(ws, alert_id), 7, day or "")
    return list_price_alerts(sheet_id)


def get_topic(sheet_id: str) -> str | None:
    ws = _tab(sheet_id, SETTINGS_TAB, ["CLÉ", "VALEUR"], create=False)
    if ws is None:
        return None
    return next((row[1].strip() for row in ws.get_values()[1:] if len(row) > 1 and row[0] == "ntfy_topic" and row[1].strip()), None)


def set_topic(sheet_id: str, topic: str | None) -> str | None:
    topic = (topic or "").strip() or None
    if topic and not TOPIC_PATTERN.match(topic):
        raise OperationError("Sujet ntfy invalide ou trop facile à deviner : 20 à 64 caractères, lettres, chiffres, - ou _ (bouton « Générer un sujet »)")
    ws = _tab(sheet_id, SETTINGS_TAB, ["CLÉ", "VALEUR"], create=True)
    keys = ws.col_values(1)
    if "ntfy_topic" in keys:
        ws.update_cell(keys.index("ntfy_topic") + 1, 2, topic or "")
    else:
        ws.append_row(["ntfy_topic", topic or ""], value_input_option="RAW")
    return topic


def send_ntfy(topic: str, title: str, message: str, tags: str = "bell", click: str | None = None) -> None:
    import requests

    payload = {"topic": topic, "title": title, "message": message, "tags": [tags]}
    if click:
        payload["click"] = click
    requests.post("https://ntfy.sh", json=payload, timeout=30).raise_for_status()
