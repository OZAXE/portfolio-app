"""
Titres suivis hors de l'univers : actions mises dans la watchlist d'un utilisateur alors qu'elles ne sont dans
aucun des grands indices de universe.csv (une petite valeur française, une action canadienne...).

Chaque nuit, run.py les ajoute à sa liste : la fiche a dès le lendemain son score, son prix juste, son historique
et les alertes, comme une action du screener. Elle en sort quand plus personne ne la suit. Avant (octobre 2026),
« Surveiller » une telle action l'écrivait dans le Sheet sans effet visible : elle n'apparaissait nulle part.

Les watchlists sont lues par l'API (/notifications/users, code administrateur), comme etf_fees.py. Si l'API ne
répond pas, on garde les titres suivis la veille plutôt que de les faire disparaître pour une nuit. Les journaux
GitHub étant publics, les tickers suivis n'y sont jamais écrits (seulement leur nombre).
"""

import logging
import os
import re

log = logging.getLogger("screener")

# Garde-fou du budget de la nuit : ~2 s d'analyse par titre, 200 titres ajoutent quelques minutes
MAX_FOLLOWED = 200
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")
# Cryptos (BTC-EUR), indices (^FCHI) et devises (EURUSD=X) n'ont pas de comptes d'entreprise
NOT_A_COMPANY = re.compile(r"-(EUR|USD|USDT|GBP|CHF)$")

# Pays et région d'après le suffixe Yahoo, pour les filtres du Marché (Europe, US, Asie)
SUFFIX_COUNTRY = {
    ".PA": "France", ".DE": "Allemagne", ".F": "Allemagne", ".AS": "Pays-Bas", ".MC": "Espagne", ".MI": "Italie",
    ".BR": "Belgique", ".HE": "Finlande", ".IR": "Irlande", ".LS": "Portugal", ".L": "Royaume-Uni",
    ".SW": "Suisse", ".ST": "Suède", ".CO": "Danemark", ".OL": "Norvège", ".VI": "Autriche", ".WA": "Pologne",
    ".AT": "Grèce", ".T": "Japon", ".HK": "Hong Kong", ".KS": "Corée du Sud", ".KQ": "Corée du Sud",
    ".TW": "Taïwan", ".TWO": "Taïwan", ".SS": "Chine", ".SZ": "Chine", ".SI": "Singapour", ".NS": "Inde",
    ".BO": "Inde", ".TO": "Canada", ".V": "Canada", ".AX": "Australie",
}
ASIA = {"Japon", "Hong Kong", "Corée du Sud", "Taïwan", "Chine", "Singapour", "Inde"}
OTHER = {"Canada", "Australie"}  # ni Europe, ni US, ni Asie : aucun filtre de région ne les retient


def place(ticker: str) -> tuple[str, str]:
    """(région, pays) : « ALO.PA » -> Europe, France ; « SHOP » (sans suffixe, coté à New York) -> US."""
    match = re.search(r"\.[A-Z]+$", ticker)
    if not match:
        return "US", "États-Unis"
    country = SUFFIX_COUNTRY.get(match.group(0), "")
    if not country or country in OTHER:
        return "", country
    return ("Asie" if country in ASIA else "Europe"), country


def entry(ticker: str, name: str = "") -> dict:
    """Ligne au format de universe.csv ; le vrai nom et le secteur viennent de l'analyse Yahoo."""
    region, country = place(ticker)
    return {"ticker": ticker, "name": name or ticker, "sector": "", "region": region, "country": country,
            "indices": "", "followed": True}


def followed_entries(users: list[dict], universe: set[str]) -> list[dict]:
    """Watchlists de tous les utilisateurs, moins ce que l'univers analyse déjà. Tickers saisis à la main dans le
    Sheet : on écarte ce qui n'a pas la forme d'un ticker d'action."""
    tickers = set()
    for u in users:
        for t in u.get("watchlist") or []:
            t = str(t).strip().upper()
            if TICKER_PATTERN.match(t) and not NOT_A_COMPANY.search(t) and t not in universe:
                tickers.add(t)
    if len(tickers) > MAX_FOLLOWED:
        log.warning("titres suivis : %d, seuls les %d premiers sont analysés", len(tickers), MAX_FOLLOWED)
    return [entry(t) for t in sorted(tickers)[:MAX_FOLLOWED]]


def previous_entries(previous: dict[str, dict], universe: set[str]) -> list[dict]:
    """Titres suivis de la veille (fiches marquées « followed » dans screener.json), quand l'API ne répond pas."""
    return [entry(t, s.get("name", "")) for t, s in sorted(previous.items()) if s.get("followed") and t not in universe]


def load_followed(previous: dict[str, dict], universe: set[str]) -> list[dict]:
    token = os.environ.get("APP_ACCESS_TOKEN")
    if token:
        try:
            from notify import api_get
            entries = followed_entries(api_get("/notifications/users", token), universe)
            log.info("titres suivis hors univers : %d", len(entries))
            return entries
        except Exception as e:  # Render endormi ou en panne : la liste de la veille, pas une liste vide
            log.warning("watchlists illisibles (%s), titres suivis de la veille gardés", type(e).__name__)
    entries = previous_entries(previous, universe)
    log.info("titres suivis hors univers (veille) : %d", len(entries))
    return entries
