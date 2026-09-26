"""
Notifications des alertes du jour sur le téléphone, via ntfy.sh (appli gratuite,
sans compte : il suffit de s'abonner au même "topic" que celui du secret NTFY_TOPIC).

Lancé par le workflow nocturne après le screener :
    python screener/notify.py --data-dir data

Les alertes sont calculées sur les fichiers de la nuit (data/), avec les positions
et la watchlist demandées à l'API (secret APP_ACCESS_TOKEN). Chaque événement
compare la nuit à la veille : il n'est donc envoyé qu'une fois.
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

API_URL = "https://portfolio-app-blvx.onrender.com"
NTFY_URL = "https://ntfy.sh"
APP_URL = "https://portfolio-front-8t6m.onrender.com/#portfolio"
MAX_SEPARATE_NOTIFICATIONS = 5  # au-delà, un seul message récapitulatif

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("notify")

EVENT_TAGS = {"sous-évaluée": "moneybag", "baisse": "chart_with_downwards_trend",
              "score": "warning", "super investisseur": "eyes"}


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

    token, topic = os.environ.get("APP_ACCESS_TOKEN"), os.environ.get("NTFY_TOPIC")
    if not token or (not topic and not args.dry_run):
        log.info("secrets APP_ACCESS_TOKEN / NTFY_TOPIC absents : pas de notification")
        return

    data_dir = Path(args.data_dir)
    screener = json.loads((data_dir / "screener.json").read_text(encoding="utf-8"))
    investors_path = data_dir / "superinvestors.json"
    investors = json.loads(investors_path.read_text(encoding="utf-8")) if investors_path.exists() else None

    positions = {p["ticker"].upper() for p in api_get("/portfolio", token)}
    watchlist = set(api_get("/watchlist", token))
    events = compute_alerts(positions, watchlist, screener, investors)["events"]
    log.info("%d alertes (positions : %d, watchlist : %d)", len(events), len(positions), len(watchlist))

    for e in events:
        log.info("  [%s] %s", e["type"], e["message"])
    if args.dry_run or not events:
        return

    if len(events) <= MAX_SEPARATE_NOTIFICATIONS:
        for e in events:
            label = "Position" if e["origin"] == "position" else "Watchlist"
            send(topic, f"{label} · {e['name']}", e["message"], EVENT_TAGS.get(e["type"], "bell"))
    else:
        summary = "\n".join(f"• {e['message']}" for e in events)
        send(topic, f"{len(events)} alertes sur ton portefeuille", summary, "bell")


if __name__ == "__main__":
    main()
