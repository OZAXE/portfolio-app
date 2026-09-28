"""
Relevé quotidien du patrimoine et notification de la plus-value de la semaine.

Lancé par le workflow nocturne (vers 3 h à Paris), avant le screener :
    python screener/snapshot.py

Les cours lus par GOOGLEFINANCE sont alors ceux de la clôture de la veille : le relevé est daté
de la veille, et rien n'est enregistré le dimanche ni le lundi (pas de bourse samedi et dimanche).
Le relevé du vendredi (fait dans la nuit de vendredi à samedi) déclenche la notification
« ta semaine » sur le sujet ntfy de chaque utilisateur.
"""

import argparse
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from notify import API_URL, api_get, send

log = logging.getLogger("snapshot")


def market_day(now: datetime) -> date | None:
    """Jour de bourse dont les cours de clôture sont disponibles au moment `now` (heure de Paris)."""
    day = now.date() - timedelta(days=1)
    return day if day.weekday() < 5 else None


def euros(x: float, signed: bool = False) -> str:
    text = f"{abs(x):,.0f}".replace(",", " ") + " €" if abs(x) >= 100 else f"{abs(x):.2f}".replace(".", ",") + " €"
    return ("+" if x >= 0 else "-") + text if signed else ("-" if x < 0 else "") + text


def weekly_message(weekly: dict) -> tuple[str, str, str]:
    """Titre, texte et étiquette ntfy de la notification de fin de semaine."""
    gain = weekly["gain"]
    pct = f" ({weekly['gain_pct'] * 100:+.1f} %)".replace(".", ",") if weekly.get("gain_pct") is not None else ""
    lines = [f"{euros(gain, signed=True)}{pct} de plus-value cette semaine.",
             f"Valeur du portefeuille : {euros(weekly['value'])}."]
    if abs(weekly.get("contributions") or 0) >= 1:
        word = "Versements" if weekly["contributions"] > 0 else "Retraits"
        lines.append(f"{word} de la semaine ({euros(abs(weekly['contributions']))}) non comptés.")
    title = "Ta semaine en bourse : " + ("en hausse" if gain >= 0 else "en baisse")
    return title, "\n".join(lines), "chart_with_upwards_trend" if gain >= 0 else "chart_with_downwards_trend"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", help="jour du relevé (AAAA-MM-JJ), par défaut le dernier jour de bourse")
    parser.add_argument("--dry-run", action="store_true", help="n'envoie pas la notification")
    args = parser.parse_args()

    token, default_topic = os.environ.get("APP_ACCESS_TOKEN"), os.environ.get("NTFY_TOPIC")
    if not token:
        log.info("secret APP_ACCESS_TOKEN absent : pas de relevé")
        return
    day = date.fromisoformat(args.day) if args.day else market_day(datetime.now(ZoneInfo("Europe/Paris")))
    if day is None:
        log.info("pas de bourse hier : pas de relevé")
        return

    api_get("/health", token)  # réveille le backend gratuit de Render
    response = requests.post(f"{API_URL}/history/snapshot", params={"day": day.isoformat()},
                             headers={"X-Access-Token": token}, timeout=300)
    response.raise_for_status()

    for u in response.json():
        if u.get("error"):
            log.warning("%s : relevé impossible (%s)", u["name"], u["error"])
            continue
        log.info("%s : %s", u["name"], "relevé ajouté" if u["recorded"] else f"pas de relevé ({u['reason']})")
        weekly, topic = u.get("weekly"), u.get("topic") or (default_topic if u.get("admin") else None)
        if day.weekday() != 4 or not weekly or not topic or args.dry_run:
            continue
        title, message, tag = weekly_message(weekly)
        send(topic, title, message, tag)
        log.info("%s : notification de la semaine envoyée", u["name"])


if __name__ == "__main__":
    main()
