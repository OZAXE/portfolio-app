"""
Relevé quotidien du patrimoine et notification de la plus-value de la semaine.

Lancé par le workflow nocturne, avant le screener (planifié à 1 h UTC, mais lancé par GitHub avec 4 à 6 h de
retard : vers 7 h - 8 h à Paris en octobre 2026, donc le récap du samedi arrive le matin) :
    python screener/snapshot.py

Les cours lus par GOOGLEFINANCE sont alors ceux de la clôture de la veille : le relevé est daté
de la veille, et rien n'est enregistré le dimanche ni le lundi (pas de bourse samedi et dimanche).
Le relevé du vendredi (fait dans la nuit de vendredi à samedi) déclenche la notification
« ta semaine » (gain de la semaine et depuis le 1er janvier) sur les téléphones de chaque utilisateur
(notifications de l'appli) et sur son sujet ntfy s'il en a un.
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from night_report import add_detail
from notify import API_URL, MONTHS, api_get, deliver

log = logging.getLogger("snapshot")


def market_day(now: datetime) -> date | None:
    """Jour de bourse dont les cours de clôture sont disponibles au moment `now` (heure de Paris)."""
    day = now.date() - timedelta(days=1)
    return day if day.weekday() < 5 else None


def euros(x: float, signed: bool = False) -> str:
    text = f"{abs(x):,.0f}".replace(",", " ") + " €" if abs(x) >= 100 else f"{abs(x):.2f}".replace(".", ",") + " €"
    return ("+" if x >= 0 else "-") + text if signed else ("-" if x < 0 else "") + text


def percent(x: float | None) -> str:
    return f" ({x * 100:+.1f} %)".replace(".", ",") if x is not None else ""


def since_label(start: str) -> str:
    """« 12 mars » pour un historique commencé en cours d'année (1er pour le premier du mois)."""
    d = date.fromisoformat(start)
    return f"{'1er' if d.day == 1 else d.day} {MONTHS[d.month - 1]}"


def summary_message(summary: dict | None) -> tuple[str, str, str] | None:
    """Notification du vendredi d'après le récap de l'API (mêmes chiffres que la courbe du Portefeuille :
    achats et ventes ne comptent pas comme un gain, dividendes oui). None : pas de semaine complète."""
    week = (summary or {}).get("week")
    if not week:
        return None
    year = summary.get("year")
    title = f"Ta semaine : {euros(week['gain'], signed=True)}{percent(week.get('pct'))}"
    lines = []
    if year:
        start = "le 1er janvier" if not year.get("since") else f"le {since_label(year['since'])}"
        lines.append(f"Depuis {start} : {euros(year['gain'], signed=True)}{percent(year.get('pct'))}.")
    lines.append(f"Ton portefeuille vaut {euros(summary['value'])}.")
    return title, "\n".join(lines), "chart_with_upwards_trend" if week["gain"] >= 0 else "chart_with_downwards_trend"


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

    # Les journaux de GitHub Actions sont publics : ni noms ni titres (le message d'erreur en contient)
    results = response.json()
    failures = 0
    for i, u in enumerate(results, 1):
        who = f"utilisateur {i}/{len(results)}"
        if u.get("error"):
            log.warning("%s : relevé impossible (cours en erreur ou Sheet illisible)", who)
            add_detail(f"Relevé impossible pour {u.get('name') or who} : {u['error']}")  # privé : envoyé par ntfy
            failures += 1
            continue
        log.info("%s : %s", who, "relevé ajouté" if u["recorded"] else f"pas de relevé ({u['reason']})")
        if day.weekday() != 4 or args.dry_run or not (u.get("push") or u.get("topic") or (u.get("admin") and default_topic)):
            continue
        message = summary_message(u.get("summary")) or (weekly_message(u["weekly"]) if u.get("weekly") else None)
        if message and deliver(u, token, default_topic, *message, push_tag="semaine"):
            log.info("%s : notification de la semaine envoyée", who)
    # Étape en échec (le workflow continue) : le rapport de la nuit prévient que la courbe n'a pas avancé
    if failures:
        sys.exit(f"{failures} relevé(s) impossible(s)")


if __name__ == "__main__":
    main()
