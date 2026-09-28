"""
Notifications des alertes du jour sur le téléphone, via ntfy.sh (appli gratuite,
sans compte : il suffit de s'abonner au même "topic").

Lancé par le workflow nocturne après le screener :
    python screener/notify.py --data-dir data

Pour chaque utilisateur de l'appli, avec les positions, la watchlist et les alertes de prix
demandées à l'API (secret APP_ACCESS_TOKEN, le code administrateur du propriétaire) :
- les événements du screener, qui comparent la nuit à la veille : envoyés une seule fois ;
- les alertes de prix, vérifiées sur le dernier cours de clôture, puis marquées déclenchées.
Chacun reçoit ses notifications sur le sujet ntfy choisi dans Réglages ; le propriétaire,
à défaut, sur celui du secret NTFY_TOPIC.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.alerts import compute_alerts  # noqa: E402
from app.notifications import check_price_alerts  # noqa: E402

API_URL = "https://portfolio-app-blvx.onrender.com"
NTFY_URL = "https://ntfy.sh"
APP_URL = "https://portfolio-front-8t6m.onrender.com/#portfolio"
MAX_SEPARATE_NOTIFICATIONS = 5  # au-delà, un seul message récapitulatif

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("notify")

EVENT_TAGS = {"sous-évaluée": "moneybag", "baisse": "chart_with_downwards_trend",
              "score": "warning", "super investisseur": "eyes", "dividende": "scissors", "prix": "bell"}


def api_get(path: str, token: str):
    """Le backend gratuit de Render dort : le premier appel peut prendre une minute."""
    for attempt in range(4):
        try:
            response = requests.get(f"{API_URL}{path}", headers={"X-Access-Token": token}, timeout=120)
            if response.status_code < 500:
                response.raise_for_status()
                return response.json()
        except requests.RequestException as e:
            if getattr(e, "response", None) is not None and e.response.status_code < 500:
                raise
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"API injoignable : {path}")


def api_post(path: str, token: str, payload: dict):
    response = requests.post(f"{API_URL}{path}", headers={"X-Access-Token": token}, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def closing_prices(tickers: list[str]) -> dict[str, float | None]:
    """Dernier cours de clôture de chaque titre (Yahoo), dans sa devise de cotation."""
    import yfinance as yf

    prices = {}
    for ticker in tickers:
        try:
            history = yf.Ticker(ticker).history(period="5d")
            prices[ticker] = float(history["Close"].dropna().iloc[-1]) if not history.empty else None
        except Exception:
            prices[ticker] = None
    return prices


def price_alert_events(alerts: list[dict], prices: dict) -> list[dict]:
    events = []
    for a in check_price_alerts(alerts, prices):
        word = "passe sous" if a["direction"] == "Sous" else "dépasse"
        note = f" ({a['note']})" if a.get("note") else ""
        events.append({"type": "prix", "origin": "alerte", "name": a["ticker"], "id": a["id"],
                       "message": f"{a['ticker']} {word} {a['price']:g} : dernier cours {a['current']:.2f}{note}"})
    return events


def notify(topic: str, events: list[dict]) -> None:
    if len(events) <= MAX_SEPARATE_NOTIFICATIONS:
        for e in events:
            label = {"position": "Position", "watchlist": "Watchlist", "alerte": "Alerte de prix"}.get(e["origin"], "Alerte")
            send(topic, f"{label} · {e['name']}", e["message"], EVENT_TAGS.get(e["type"], "bell"))
    else:
        summary = "\n".join(f"• {e['message']}" for e in events)
        send(topic, f"{len(events)} alertes sur ton portefeuille", summary, "bell")


def send(topic: str, title: str, message: str, tags: str) -> None:
    # Publication en JSON : les titres accentués passent mal dans les en-têtes HTTP
    requests.post(
        NTFY_URL,
        json={"topic": topic, "title": title, "message": message, "tags": [tags], "click": APP_URL},
        timeout=30,
    ).raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--dry-run", action="store_true", help="affiche les alertes sans les envoyer")
    args = parser.parse_args()

    token, default_topic = os.environ.get("APP_ACCESS_TOKEN"), os.environ.get("NTFY_TOPIC")
    if not token:
        log.info("secret APP_ACCESS_TOKEN absent : pas de notification")
        return

    data_dir = Path(args.data_dir)
    screener = json.loads((data_dir / "screener.json").read_text(encoding="utf-8"))
    investors_path = data_dir / "superinvestors.json"
    investors = json.loads(investors_path.read_text(encoding="utf-8")) if investors_path.exists() else None

    users = api_get("/notifications/users", token)
    alert_tickers = sorted({a["ticker"] for u in users for a in u.get("price_alerts", [])})
    prices = closing_prices(alert_tickers)

    # Les journaux de GitHub Actions sont publics : ni noms, ni titres, ni textes d'alerte
    for i, u in enumerate(users, 1):
        who = f"utilisateur {i}/{len(users)}"
        if u.get("error"):
            log.warning("%s : Sheet illisible", who)
            continue
        topic = u.get("topic") or (default_topic if u.get("admin") else None)
        events = compute_alerts(set(u["positions"]), set(u["watchlist"]), screener, investors)["events"]
        price_events = price_alert_events(u["price_alerts"], prices)
        log.info("%s : %d alertes, %d alertes de prix déclenchées%s", who, len(events), len(price_events),
                 "" if topic else " (pas de sujet ntfy)")
        if args.dry_run:  # à la main seulement, jamais dans le workflow
            for e in events + price_events:
                log.info("  [%s] %s", e["type"], e["message"])
        if args.dry_run or not topic or not (events or price_events):
            continue
        notify(topic, events + price_events)
        if price_events:  # une alerte de prix n'est envoyée qu'une fois : marquée déclenchée
            api_post("/notifications/triggered", token, {"user": u["name"], "ids": [e["id"] for e in price_events]})


if __name__ == "__main__":
    main()
