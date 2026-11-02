"""
Relevé quotidien du patrimoine dans l'onglet Historique de chaque utilisateur.

Lancé par le workflow du soir (screener.yml, planifié à 21 h 47 UTC), avant le screener :
    python screener/snapshot.py

Le relevé est daté du dernier jour de bourse dont la clôture américaine est passée (market_day, dans
notify.py) : le soir même, ou la veille si GitHub lance le calcul après minuit à New York. Rien n'est
enregistré pour un samedi ni un dimanche. Le récap de la semaine n'est plus envoyé d'ici : la tâche du
matin (notify.py --morning) le calcule sur ce relevé, pour ne pas réveiller tout le monde à minuit.
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from night_report import add_detail
from notify import API_URL, api_get, market_day  # noqa: F401 (market_day : aussi lu par les tests)

log = logging.getLogger("snapshot")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", help="jour du relevé (AAAA-MM-JJ), par défaut le dernier jour de bourse")
    args = parser.parse_args()

    token = os.environ.get("APP_ACCESS_TOKEN")
    if not token:
        log.info("secret APP_ACCESS_TOKEN absent : pas de relevé")
        return
    day = date.fromisoformat(args.day) if args.day else market_day(datetime.now(ZoneInfo("Europe/Paris")))
    if day is None:
        log.info("pas de séance (week-end) : pas de relevé")
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
    # Étape en échec (le workflow continue) : le rapport de la nuit prévient que la courbe n'a pas avancé
    if failures:
        sys.exit(f"{failures} relevé(s) impossible(s)")


if __name__ == "__main__":
    main()
