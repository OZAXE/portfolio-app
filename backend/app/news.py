"""
Actualités d'une action, pour la fiche : titres récents avec leur source et un lien vers l'article.

Source principale : le flux RSS de Google Actualités en français (recherche du nom de l'entreprise sur
30 jours), gratuit, sans clé, au format RSS 2.0 stable. Secours : la recherche de Yahoo Finance (articles
en anglais). Un titre n'est gardé que s'il contient le nom de l'entreprise : « Orange » ne doit pas
remonter d'articles sur le fruit, ni « Total » des totaux de n'importe quoi.
"""

import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

MAX_ARTICLES = 8
GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={query}&hl=fr&gl=FR&ceid=FR:fr"
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={ticker}&newsCount=12&quotesCount=0"
HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio-app)"}

# « L'Air Liquide S.A. » -> « Air Liquide », « Hermès International Société en commandite par actions » -> « Hermès
# International » : les articles citent le nom d'usage, pas la forme juridique (même règle que shortName de l'appli)
LEGAL_FORMS = re.compile(
    r"[\s,]*\(?\b(Société en commandite par actions|Société Européenne|S\.?C\.?A\.?|S\.?A\.?|SE|N\.?V\.?|AG|plc|Inc\.?|"
    r"Corporation|Corp\.?|Ltd\.?|Limited|Holdings?|Group|S\.p\.A\.?|Class [A-C])\)?\.?$", re.IGNORECASE)


def company_name(name: str) -> str:
    name = str(name or "").strip()
    for _ in range(3):
        name = LEGAL_FORMS.sub("", name).strip(" ,-")
    return re.sub(r"^L'(?=[A-ZÉ])", "", name)  # « L'Oréal » reste cherché « Oréal » : les titres écrivent « L'Oréal »


def _fold(text: str) -> str:
    """Minuscules sans accents, pour comparer « Hermès » et « HERMES »."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


# Premiers mots trop courants pour identifier seuls une entreprise : « Air » Liquide, « Société » Générale
GENERIC_WORDS = {"societe", "credit", "banque", "banco", "bank", "deutsche", "general", "royal", "national", "united",
                 "american", "first", "international", "compagnie", "groupe", "air", "the", "data", "global", "energy"}


def mentions(title: str, name: str) -> bool:
    """Le titre cite-t-il l'entreprise ? Le premier mot du nom suffit s'il est distinctif (« Hermès » pour
    Hermès International, « LVMH »), sinon les deux premiers (« Air Liquide », « Société Générale »)."""
    words = _fold(name).split()
    if not words:
        return False
    distinctive = len(words) == 1 or (len(words[0]) >= 4 and words[0] not in GENERIC_WORDS)
    key = words[0] if distinctive else " ".join(words[:2])
    return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", _fold(title)) is not None


def google_news_url(name: str) -> str:
    return GOOGLE_NEWS_URL.format(query=quote_plus(f'"{name}" when:30d'))


def parse_google_rss(xml_text: str, name: str) -> list[dict]:
    """Éléments <item> du flux : titre « Titre - Source », lien, date RFC 822, <source>."""
    articles = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        link = (item.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
        except (TypeError, ValueError):
            published = None
        if title and link.startswith("https://") and mentions(title, name):
            articles.append({"title": title, "source": source or None, "url": link,
                             "published": published.isoformat() if published else None})
    return articles


def parse_yahoo_search(data: dict, name: str) -> list[dict]:
    articles = []
    for n in data.get("news") or []:
        title, link = str(n.get("title") or "").strip(), str(n.get("link") or "")
        stamp = n.get("providerPublishTime")
        published = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if isinstance(stamp, (int, float)) else None
        if title and link.startswith("https://") and mentions(title, name):
            articles.append({"title": title, "source": n.get("publisher") or None, "url": link, "published": published})
    return articles


def latest(articles: list[dict]) -> list[dict]:
    """Plus récents d'abord, sans les doublons (même titre repris par plusieurs sites)."""
    seen, out = set(), []
    for a in sorted(articles, key=lambda a: a["published"] or "", reverse=True):
        key = _fold(a["title"])[:80]
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out[:MAX_ARTICLES]


def fetch_news(ticker: str, name: str) -> dict:
    """Google Actualités, sinon Yahoo. {"articles": [...], "source": "Google Actualités" | "Yahoo Finance" | None}."""
    import requests

    clean = company_name(name) or ticker
    try:
        response = requests.get(google_news_url(clean), headers=HEADERS, timeout=15)
        response.raise_for_status()
        articles = latest(parse_google_rss(response.text, clean))
        if articles:
            return {"articles": articles, "source": "Google Actualités", "query": clean}
    except Exception:
        pass
    try:
        response = requests.get(YAHOO_SEARCH_URL.format(ticker=quote_plus(ticker)), headers=HEADERS, timeout=15)
        response.raise_for_status()
        articles = latest(parse_yahoo_search(response.json(), clean))
        if articles:
            return {"articles": articles, "source": "Yahoo Finance", "query": clean}
    except Exception:
        pass
    return {"articles": [], "source": None, "query": clean}
