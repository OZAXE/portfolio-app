"""
Rapport du calcul de nuit : prévient le propriétaire (sujet ntfy du secret NTFY_TOPIC) quand une étape a échoué.

Dernière étape du workflow nocturne, lancée quoi qu'il arrive :
    OUTCOMES="Relevé du patrimoine=success;Screener=failure;..." python screener/night_report.py

Pourquoi : la plupart des étapes sont en « continue-on-error » pour ne pas perdre le travail déjà fait, donc
le workflow reste vert même quand une étape plante, et GitHub n'envoie aucun mail. Un relevé du patrimoine
refusé (cours GOOGLEFINANCE en erreur) laissait la courbe s'arrêter sans que personne ne le sache.

Les détails privés (noms, titres en cause) ne vont pas dans les journaux de GitHub Actions, qui sont publics :
les scripts les ajoutent au fichier NIGHT_REPORT (add_detail), lu ici et envoyé seulement par ntfy.
Bibliothèque standard seulement : le rapport doit partir même si l'installation des paquets a échoué.
"""

import json
import logging
import os
import urllib.request

log = logging.getLogger("night_report")

NTFY_URL = "https://ntfy.sh"
FAILED = ("failure", "cancelled")  # « cancelled » : étape arrêtée par la limite de temps du workflow


def add_detail(text: str) -> None:
    """Ajoute une ligne privée au rapport de la nuit (rien si le script tourne hors du workflow)."""
    path = os.environ.get("NIGHT_REPORT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text.replace("\n", " ") + "\n")


def parse_outcomes(text: str) -> list[tuple[str, str]]:
    """« Screener=failure; Traduction=success » -> [("Screener", "failure"), ("Traduction", "success")]."""
    pairs = []
    for part in text.split(";"):
        name, sep, outcome = part.strip().rpartition("=")
        if sep and name.strip():
            pairs.append((name.strip(), outcome.strip()))
    return pairs


def report_message(outcomes: list[tuple[str, str]], details: list[str]) -> tuple[str, str] | None:
    """Titre et texte de la notification, ou None si tout s'est bien passé."""
    failed = [name for name, outcome in outcomes if outcome in FAILED]
    skipped = [name for name, outcome in outcomes if outcome == "skipped"]
    if not failed and not details:
        return None
    n = len(failed)
    title = f"Calcul de nuit : {n} étape{'s' if n > 1 else ''} en échec" if n else "Calcul de nuit : à vérifier"
    lines = [f"• {name}" for name in failed]
    lines += [f"  {d}" for d in details]
    if skipped:
        lines.append(f"Pas lancées ensuite : {', '.join(skipped)}.")
    lines.append("L'appli garde les données de la veille. Touche pour voir le journal du workflow.")
    return title, "\n".join(lines)


def read_details(path: str | None) -> list[str]:
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def send(topic: str, title: str, message: str, click: str | None) -> None:
    payload = {"topic": topic, "title": title, "message": message, "tags": ["warning"], "priority": 4}
    if click:
        payload["click"] = click
    request = urllib.request.Request(NTFY_URL, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30):
        pass


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    outcomes = parse_outcomes(os.environ.get("OUTCOMES", ""))
    details = read_details(os.environ.get("NIGHT_REPORT"))
    report = report_message(outcomes, details)
    if report is None:
        log.info("toutes les étapes ont réussi")
        return
    failed = [name for name, outcome in outcomes if outcome in FAILED]
    log.warning("étapes en échec : %s", ", ".join(failed) or "aucune (détails signalés)")
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        log.info("secret NTFY_TOPIC absent : pas de notification")
        return
    send(topic, *report, os.environ.get("RUN_URL"))
    log.info("notification envoyée")


if __name__ == "__main__":
    main()
