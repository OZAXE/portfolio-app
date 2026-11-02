"""
Notifications des alertes du jour sur le téléphone : notifications de l'appli installée (Web Push,
activées dans Plus > Notifications, envoyées par l'API qui garde la clé VAPID) et, pour qui l'a
choisi, ntfy.sh (appli gratuite, sans compte : il suffit de s'abonner au même "topic").

Lancé par le workflow notifications.yml, en deux passages :
    python screener/notify.py --morning      # vers 8 h : brief, récap du samedi, alertes de la nuit
    python screener/notify.py --briefs-only  # vers 18 h : nouveau brief déposé dans la journée
À la main, sur des données locales : python screener/notify.py --data-dir data --dry-run

Le calcul (screener.yml) tourne le soir, après la clôture américaine ; ses données sont publiées sur la
branche screener-data, que le passage du matin relit (en attendant qu'elles soient de la nuit si GitHub a
lancé le calcul en retard). Envoyer le matin et pas à la fin du calcul : personne n'est réveillé à minuit.

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
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
DATA_URL = "https://raw.githubusercontent.com/OZAXE/portfolio-app/screener-data"
PARIS, NEW_YORK = ZoneInfo("Europe/Paris"), ZoneInfo("America/New_York")
US_CLOSE_DONE = clock(16, 30)  # clôture de New York (16 h) plus le délai des cours de GOOGLEFINANCE
FRESH_HOURS = 16  # données du matin = calcul lancé la veille au soir (21 h 47 UTC), même avec du retard

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


def market_day(now: datetime) -> date | None:
    """Dernière séance dont la clôture américaine est passée à `now` (sans fuseau : heure de Paris) ; None le
    week-end. Calculé à New York : le calcul du vendredi soir lancé avec retard après minuit à Paris (1 h 30 le
    samedi = 19 h 30 le vendredi à New York) reste daté du vendredi, et le matin à Paris donne la veille."""
    ny = (now if now.tzinfo else now.replace(tzinfo=PARIS)).astimezone(NEW_YORK)
    day = ny.date() if ny.time() >= US_CLOSE_DONE else ny.date() - timedelta(days=1)
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


def fresh_data(now: datetime | None = None, wait_minutes: int = 0) -> tuple[dict, dict | None] | None:
    """screener.json et superinvestors.json publiés par le calcul de la veille au soir. Plus vieux que FRESH_HOURS
    (calcul pas encore fini, ou en échec) : on réessaie toutes les 10 min pendant `wait_minutes`, sinon None.
    Sans ce contrôle, les alertes de la veille repartiraient (elles comparent deux nuits d'affilée)."""
    deadline = time.monotonic() + wait_minutes * 60
    while True:
        try:
            screener = requests.get(f"{DATA_URL}/screener.json", timeout=120).json()
            generated = datetime.fromisoformat(screener["generated_at"])
            age = (now or datetime.now(timezone.utc)) - generated
            if age <= timedelta(hours=FRESH_HOURS):
                investors = requests.get(f"{DATA_URL}/superinvestors.json", timeout=120)
                return screener, investors.json() if investors.ok else None
            log.info("données du %s, pas encore celles de la nuit", generated.isoformat(timespec="minutes"))
        except (requests.RequestException, ValueError, KeyError) as e:
            log.warning("données du screener illisibles (%s)", type(e).__name__)
        if time.monotonic() >= deadline:
            return None
        time.sleep(600)


def send_weekly(token: str, default_topic: str | None, day: date, dry_run: bool) -> None:
    """Récap du samedi matin sur le relevé du vendredi soir (route /notifications/weekly)."""
    users = api_get(f"/notifications/weekly?day={day.isoformat()}", token)
    for i, u in enumerate(users, 1):
        who = f"utilisateur {i}/{len(users)}"
        message = None if u.get("error") else summary_message(u.get("summary"))
        if not message:
            log.info("%s : pas de récap (semaine incomplète ou Sheet illisible)", who)
            continue
        if dry_run:
            log.info("  [semaine] %s", message[0])
        elif deliver(u, token, default_topic, *message, push_tag="semaine"):
            log.info("%s : récap de la semaine envoyé", who)


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
        user["brief"] = None  # déjà parti : pas une deuxième fois dans la suite du même passage
        log.info("%s : nouveau brief annoncé", who)


def announce_briefs(users: list[dict], token: str, default_topic: str | None, dry_run: bool) -> None:
    """Le brief déposé le samedi dans la journée est annoncé le soir même (passage de 18 h) ; le passage du
    matin rattrape ceux qui seraient arrivés après."""
    for i, u in enumerate(users, 1):
        who = f"utilisateur {i}/{len(users)}"
        if u.get("error") or not u.get("brief"):
            continue
        if dry_run or not (u.get("push") or user_topic(u, default_topic)):
            log.info("%s : brief à annoncer%s", who, " (notifications non activées)" if not dry_run else "")
            continue
        announce_brief(u, token, default_topic, who)


def send_alerts(users: list[dict], token: str, default_topic: str | None, screener: dict, investors: dict | None,
                dry_run: bool) -> None:
    alert_tickers = sorted({a["ticker"] for u in users if not u.get("error") for a in u.get("price_alerts", [])})
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
        if dry_run:  # à la main seulement, jamais dans le workflow
            for e in events + price_events:
                log.info("  [%s] %s", e["type"], e["message"])
            continue
        if not has_channel:
            continue
        if events or price_events:
            notify(lambda title, text, tag: deliver(u, token, default_topic, title, text, tag), events + price_events)
        if price_events:  # une alerte de prix n'est envoyée qu'une fois : marquée déclenchée
            api_post("/notifications/triggered", token, {"user": u["name"], "ids": [e["id"] for e in price_events]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data", help="données locales (sans --morning)")
    parser.add_argument("--dry-run", action="store_true", help="affiche les notifications sans les envoyer")
    parser.add_argument("--briefs-only", action="store_true", help="passage de 18 h : seulement le nouveau brief")
    parser.add_argument("--morning", action="store_true",
                        help="passage du matin : brief, récap du samedi, alertes sur les données publiées cette nuit")
    parser.add_argument("--wait-min", type=int, default=180, help="attente maximale des données de la nuit (--morning)")
    args = parser.parse_args()

    token, default_topic = os.environ.get("APP_ACCESS_TOKEN"), os.environ.get("NTFY_TOPIC")
    if not token:
        log.info("secret APP_ACCESS_TOKEN absent : pas de notification")
        return

    users = api_get("/notifications/users", token)
    if args.briefs_only:
        announce_briefs(users, token, default_topic, args.dry_run)
        return
    if not args.morning:
        data_dir = Path(args.data_dir)
        investors_path = data_dir / "superinvestors.json"
        send_alerts(users, token, default_topic, json.loads((data_dir / "screener.json").read_text(encoding="utf-8")),
                    json.loads(investors_path.read_text(encoding="utf-8")) if investors_path.exists() else None, args.dry_run)
        return

    # Matin : ce qui ne dépend pas du calcul de la nuit part tout de suite, les alertes l'attendent
    announce_briefs(users, token, default_topic, args.dry_run)
    now = datetime.now(PARIS)
    if now.weekday() == 5:  # samedi
        send_weekly(token, default_topic, market_day(now) or now.date() - timedelta(days=1), args.dry_run)
    data = fresh_data(wait_minutes=args.wait_min)
    if data is None:  # échec visible dans GitHub (mail) : les alertes de la nuit ne sont pas parties
        sys.exit(f"Pas de données de la nuit après {args.wait_min} min d'attente : alertes non envoyées")
    users = api_get("/notifications/users", token)  # relu : alertes de prix modifiées pendant l'attente
    send_alerts(users, token, default_topic, *data, args.dry_run)


if __name__ == "__main__":
    main()
