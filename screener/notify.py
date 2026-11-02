"""
Notifications des alertes du jour sur le téléphone : notifications de l'appli installée (Web Push,
activées dans Plus > Notifications, envoyées par l'API qui garde la clé VAPID) et, pour qui l'a
choisi, ntfy.sh (appli gratuite, sans compte : il suffit de s'abonner au même "topic").

Lancé par le workflow nocturne après le screener :
    python screener/notify.py --data-dir data

Pour chaque utilisateur de l'appli, avec les positions, la watchlist et les alertes de prix
demandées à l'API (secret APP_ACCESS_TOKEN, le code administrateur du propriétaire) :
- les événements du screener, qui comparent la nuit à la veille : envoyés une seule fois ;
- les alertes de prix, vérifiées sur le dernier cours de clôture, puis marquées déclenchées.
- le nouveau brief de la semaine, annoncé une fois (s'il n'est pas déjà coché « Lu »).
Chacun reçoit ses notifications sur ses téléphones abonnés et sur son sujet ntfy s'il en a un ; le
propriétaire, sans aucun des deux, sur le sujet du secret NTFY_TOPIC.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.alerts import compute_alerts  # noqa: E402
from app.notifications import check_price_alerts  # noqa: E402

API_URL = "https://portfolio-app-blvx.onrender.com"
NTFY_URL = "https://ntfy.sh"
APP_ORIGIN = "https://portfolio-front-8t6m.onrender.com"
APP_URL = f"{APP_ORIGIN}/#portfolio"
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre")
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


def notify(deliver_one, events: list[dict]) -> None:
    """deliver_one(titre, texte, étiquette ntfy) : envoi sur les canaux de l'utilisateur (voir deliver)."""
    if len(events) <= MAX_SEPARATE_NOTIFICATIONS:
        for e in events:
            label = {"position": "Position", "watchlist": "Watchlist", "alerte": "Alerte de prix"}.get(e["origin"], "Alerte")
            deliver_one(f"{label} · {e['name']}", e["message"], EVENT_TAGS.get(e["type"], "bell"))
    else:
        summary = "\n".join(f"• {e['message']}" for e in events)
        deliver_one(f"{len(events)} alertes sur ton portefeuille", summary, "bell")


def send(topic: str, title: str, message: str, tags: str, click: str = APP_URL) -> None:
    # Publication en JSON : les titres accentués passent mal dans les en-têtes HTTP
    requests.post(
        NTFY_URL,
        json={"topic": topic, "title": title, "message": message, "tags": [tags], "click": click},
        timeout=30,
    ).raise_for_status()


def user_topic(user: dict, default_topic: str | None) -> str | None:
    """Sujet ntfy de l'utilisateur. Le secret NTFY_TOPIC ne sert au propriétaire que s'il n'a ni sujet ni téléphone
    abonné : une fois les notifications de l'appli activées, il ne reçoit pas tout en double."""
    return user.get("topic") or (default_topic if user.get("admin") and not user.get("push") else None)


def deliver(user: dict, token: str, default_topic: str | None, title: str, message: str, tags: str,
            url: str = APP_URL, push_tag: str | None = None) -> list[str]:
    """Envoie sur les téléphones abonnés (par l'API) puis sur ntfy ; un canal en panne n'empêche pas l'autre.
    Renvoie les canaux qui ont marché. Rien de privé dans les journaux (publics) : seulement le type d'erreur."""
    channels = []
    if user.get("push"):
        try:
            if api_post("/notifications/send", token, {"user": user["name"], "title": title, "message": message,
                                                       "url": url, "tag": push_tag}).get("sent"):
                channels.append("appli")
        except Exception as e:
            log.warning("notification de l'appli impossible (%s)", type(e).__name__)
    topic = user_topic(user, default_topic)
    if topic:
        try:
            send(topic, title, message, tags, url)
            channels.append("ntfy")
        except Exception as e:
            log.warning("notification ntfy impossible (%s)", type(e).__name__)
    return channels


def brief_message(brief: dict) -> tuple[str, str]:
    """Brief publié le samedi 31/10/2026 -> « Nouveau brief : semaine du 26 octobre » (lundi de la semaine,
    comme la liste des briefs de l'appli)."""
    day = date.fromisoformat(brief["date"])
    monday = day - timedelta(days=day.weekday())
    first = "1er" if monday.day == 1 else str(monday.day)
    return f"Nouveau brief : semaine du {first} {MONTHS[monday.month - 1]}", "Le point marchés de la semaine est prêt à lire."


def announce_brief(user: dict, token: str, default_topic: str | None, who: str) -> None:
    """Annonce le nouveau brief (s'il y en a un pour cet utilisateur) puis le marque annoncé : plus jamais renvoyé.
    Pas marqué si rien n'est parti (aucun canal) : annoncé au prochain passage, tant qu'il a moins de 8 jours."""
    if not user.get("brief"):
        return
    title, text = brief_message(user["brief"])
    if deliver(user, token, default_topic, title, text, "newspaper", f"{APP_ORIGIN}/#briefs", "brief"):
        api_post("/notifications/brief-sent", token, {"user": user["name"], "id": user["brief"]["id"]})
        log.info("%s : nouveau brief annoncé", who)


def announce_briefs(users: list[dict], token: str, default_topic: str | None, dry_run: bool) -> None:
    """Passage de 18 h : le brief déposé le samedi (dans la journée) est annoncé le soir même, pas le lendemain
    matin à la fin du calcul de nuit. Le passage de nuit annonce ceux qui seraient arrivés après."""
    for i, u in enumerate(users, 1):
        who = f"utilisateur {i}/{len(users)}"
        if u.get("error") or not u.get("brief"):
            continue
        if dry_run or not (u.get("push") or user_topic(u, default_topic)):
            log.info("%s : brief à annoncer%s", who, " (notifications non activées)" if not dry_run else "")
            continue
        announce_brief(u, token, default_topic, who)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--dry-run", action="store_true", help="affiche les alertes sans les envoyer")
    parser.add_argument("--briefs-only", action="store_true",
                        help="annonce seulement le nouveau brief (passage de 18 h, workflow notifications.yml)")
    args = parser.parse_args()

    token, default_topic = os.environ.get("APP_ACCESS_TOKEN"), os.environ.get("NTFY_TOPIC")
    if not token:
        log.info("secret APP_ACCESS_TOKEN absent : pas de notification")
        return

    users = api_get("/notifications/users", token)
    if args.briefs_only:
        announce_briefs(users, token, default_topic, args.dry_run)
        return

    data_dir = Path(args.data_dir)
    screener = json.loads((data_dir / "screener.json").read_text(encoding="utf-8"))
    investors_path = data_dir / "superinvestors.json"
    investors = json.loads(investors_path.read_text(encoding="utf-8")) if investors_path.exists() else None
    alert_tickers = sorted({a["ticker"] for u in users for a in u.get("price_alerts", [])})
    prices = closing_prices(alert_tickers)

    # Les journaux de GitHub Actions sont publics : ni noms, ni titres, ni textes d'alerte
    for i, u in enumerate(users, 1):
        who = f"utilisateur {i}/{len(users)}"
        if u.get("error"):
            log.warning("%s : Sheet illisible", who)
            continue
        has_channel = bool(u.get("push") or user_topic(u, default_topic))
        events = compute_alerts(set(u["positions"]), set(u["watchlist"]), screener, investors)["events"]
        price_events = price_alert_events(u["price_alerts"], prices)
        log.info("%s : %d alertes, %d alertes de prix déclenchées%s", who, len(events), len(price_events),
                 "" if has_channel else " (notifications non activées)")
        if args.dry_run:  # à la main seulement, jamais dans le workflow
            for e in events + price_events:
                log.info("  [%s] %s", e["type"], e["message"])
            if u.get("brief"):
                log.info("  [brief] %s", brief_message(u["brief"])[0])
        if args.dry_run or not has_channel:
            continue
        if events or price_events:
            notify(lambda title, text, tag: deliver(u, token, default_topic, title, text, tag), events + price_events)
        if price_events:  # une alerte de prix n'est envoyée qu'une fois : marquée déclenchée
            api_post("/notifications/triggered", token, {"user": u["name"], "ids": [e["id"] for e in price_events]})
        announce_brief(u, token, default_topic, who)


if __name__ == "__main__":
    main()
