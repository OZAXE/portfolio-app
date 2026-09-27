"""
Contenu réel des ETF : composition des grands indices, pour décomposer un ETF du portefeuille
en pays, secteurs et entreprises (un ETF MSCI World, c'est environ 70 % d'actions américaines).

Lancé avec le screener nocturne :
    python screener/etf_lookthrough.py --data-dir data

Sources, publiques et sans clé :
- fichiers de composition quotidiens des ETF SPDR UCITS (State Street) : poids, pays et secteur
  de chaque ligne. Un ETF Amundi ou iShares sur le même indice a la même composition, à quelques
  détails de réplication près ;
- Nasdaq 100 : membres et capitalisations publiés par Nasdaq ; CAC 40, Euro Stoxx 50 et
  STOXX Europe 600 : membres et capitalisations du screener. Poids reconstitués au prorata des
  capitalisations (approximation : les indices plafonnent certains poids et retiennent le flottant).

L'appli reconnaît l'indice d'un ETF à son nom (onglet Titres) et fait la décomposition elle-même.
"""

import argparse
import io
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

SPDR_URL = "https://www.ssga.com/library-content/products/fund-data/etfs/emea/holdings-daily-emea-en-{}.xlsx"
NASDAQ_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio-app)", "Accept": "application/json, */*"}
MAX_HOLDINGS = 300  # au-delà, les poids sont minuscules

# clé, libellé, source (code SPDR ou indice du screener)
SPDR_INDICES = [
    ("world", "MSCI World", "sppw-gy"),
    ("acwi", "MSCI ACWI", "spyy-gy"),
    ("acwi_imi", "MSCI ACWI IMI", "spyi-gy"),
    ("sp500", "S&P 500", "spy5-gy"),
    ("em", "MSCI Emerging Markets", "spym-gy"),
    ("europe", "MSCI Europe", "ero-fp"),
]
SCREENER_INDICES = [
    ("cac40", "CAC 40", "CAC 40"),
    ("eurostoxx50", "Euro Stoxx 50", "EURO STOXX 50"),
    ("stoxx600", "STOXX Europe 600", "STOXX Europe 600"),
]

# Secteurs GICS -> libellés de l'appli (ceux du screener)
SECTORS = {
    "Information Technology": "Technologie", "Financials": "Finance", "Health Care": "Santé",
    "Industrials": "Industrie", "Consumer Discretionary": "Consommation", "Consumer Staples": "Consommation",
    "Communication Services": "Communication", "Materials": "Matériaux", "Energy": "Énergie",
    "Utilities": "Services publics", "Real Estate": "Immobilier",
}
COUNTRIES = {
    "United States": "États-Unis", "Japan": "Japon", "United Kingdom": "Royaume-Uni", "Canada": "Canada",
    "France": "France", "Switzerland": "Suisse", "Germany": "Allemagne", "Australia": "Australie",
    "Netherlands": "Pays-Bas", "Sweden": "Suède", "Denmark": "Danemark", "Italy": "Italie", "Spain": "Espagne",
    "Hong Kong": "Hong Kong", "Singapore": "Singapour", "Finland": "Finlande", "Belgium": "Belgique",
    "Norway": "Norvège", "Israel": "Israël", "Ireland": "Irlande", "New Zealand": "Nouvelle-Zélande",
    "Austria": "Autriche", "Portugal": "Portugal", "China": "Chine", "Taiwan": "Taïwan", "India": "Inde",
    "Korea": "Corée du Sud", "South Korea": "Corée du Sud", "Korea (South)": "Corée du Sud", "Brazil": "Brésil",
    "Saudi Arabia": "Arabie saoudite", "South Africa": "Afrique du Sud", "Mexico": "Mexique",
    "Indonesia": "Indonésie", "Thailand": "Thaïlande", "Malaysia": "Malaisie", "United Arab Emirates": "Émirats arabes unis",
    "Poland": "Pologne", "Qatar": "Qatar", "Kuwait": "Koweït", "Turkey": "Turquie", "Philippines": "Philippines",
    "Chile": "Chili", "Greece": "Grèce", "Peru": "Pérou", "Hungary": "Hongrie", "Colombia": "Colombie",
    "Czech Republic": "République tchèque", "Egypt": "Égypte", "Luxembourg": "Luxembourg",
}

# Mots sans valeur pour reconnaître une entreprise d'une source à l'autre (même règle dans l'appli)
NAME_STOPWORDS = {
    "inc", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "sa", "se", "ag", "nv", "ab", "asa",
    "spa", "as", "oyj", "the", "class", "group", "holding", "holdings", "and", "de", "reg", "common", "stock",
    "shares", "adr", "sponsored", "ordinary", "npv", "aktiengesellschaft", "kgaa", "societe", "europeenne",
    "anonyme", "incorporated", "sab", "cv", "bhd", "tbk", "pcl",
}


def name_key(name: str) -> str:
    """« NVIDIA Corporation » et « Nvidia Corp » -> « nvidia » ; deux premiers mots significatifs."""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.split(r"[^a-z0-9]+", text) if len(w) > 1 and w not in NAME_STOPWORDS]
    return " ".join(words[:2])


def find_by_name(index: dict[str, dict], key: str) -> dict | None:
    """Entrée de même clé, sinon la seule dont la clé commence par le même premier mot
    (« asml » et « asml new » ; pas « american express » et « american tower »)."""
    if key in index:
        return index[key]
    first = key.split(" ")[0]
    candidates = [v for k, v in index.items() if k.split(" ")[0] == first]
    return candidates[0] if len(candidates) == 1 else None


def _shares(pairs) -> dict[str, float]:
    """Poids agrégés et normalisés (somme 1), du plus gros au plus petit."""
    totals: dict[str, float] = {}
    for label, weight in pairs:
        totals[label] = totals.get(label, 0.0) + weight
    total = sum(totals.values())
    return {k: round(v / total, 5) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])} if total else {}


def summarize(rows: list[dict]) -> dict:
    """rows : {name, weight, country, sector} (poids dans n'importe quelle unité)."""
    rows = [r for r in rows if r["weight"] and r["weight"] > 0]
    total = sum(r["weight"] for r in rows)
    holdings: dict[str, list] = {}
    for r in rows:  # actions de plusieurs classes (Alphabet A et C) regroupées sous le même nom
        key = name_key(r["name"])
        if key in holdings:
            holdings[key][2] += r["weight"] / total
        else:
            display = re.sub(r"\s+Class [A-Z]\b.*$", "", r["name"])  # « Alphabet Inc. Class A » -> « Alphabet Inc. »
            holdings[key] = [display, key, r["weight"] / total]
    top = sorted(holdings.values(), key=lambda h: -h[2])[:MAX_HOLDINGS]
    return {
        "count": len(rows),
        "countries": _shares((COUNTRIES.get(r["country"], r["country"]) or "Autre", r["weight"]) for r in rows),
        "sectors": _shares((SECTORS.get(r["sector"], r["sector"]) or "Non classé", r["weight"]) for r in rows),
        "holdings": [[name, key, round(w, 6)] for name, key, w in top],
    }


def parse_spdr(content: bytes) -> tuple[list[dict], str | None]:
    """Fichier xlsx SPDR : 5 lignes d'en-tête (nom du fonds, ISIN, date), puis une ligne par titre.
    Les liquidités et lignes de fin (sans pays) sont écartées."""
    raw = pd.read_excel(io.BytesIO(content), header=None)
    as_of = str(raw.iloc[3, 1]) if raw.shape[0] > 3 else None
    header_row = next(i for i in range(min(15, len(raw))) if str(raw.iloc[i, 0]).strip() == "ISIN")
    table = raw.iloc[header_row + 1:].copy()
    table.columns = [str(c).strip() for c in raw.iloc[header_row]]
    rows = []
    for _, r in table.iterrows():
        weight = pd.to_numeric(r.get("Percent of Fund"), errors="coerce")
        country = r.get("Trade Country Name")
        if pd.isna(weight) or pd.isna(country) or not str(r.get("Security Name", "")).strip():
            continue
        sector = r.get("Sector Classification")
        rows.append({"name": str(r["Security Name"]).strip(), "weight": float(weight), "country": str(country).strip(),
                     "sector": None if pd.isna(sector) or sector == "Unassigned" else str(sector).strip()})
    return rows, as_of


def screener_index_rows(stocks: list[dict], index_name: str) -> list[dict]:
    """Membres d'un indice d'après le screener, pondérés par leur capitalisation en euros."""
    return [{"name": s["name"], "weight": s.get("market_cap_eur") or 0, "country": s.get("country"),
             "sector": None if s.get("sector") in (None, "Non classé") else s.get("sector")}
            for s in stocks if index_name in (s.get("indices") or [])]


def nasdaq_rows(payload: dict, reference: dict[str, dict]) -> list[dict]:
    """Membres du Nasdaq 100 (capitalisation Nasdaq) ; pays et secteur repris d'un fichier SPDR
    (MSCI ACWI) quand l'entreprise y figure, sinon États-Unis et non classé."""
    rows = {}
    for item in payload["data"]["data"]["rows"]:
        cap = pd.to_numeric(str(item.get("marketCap", "")).replace(",", ""), errors="coerce")
        name = re.sub(r"\s+(Common Stock|Capital Stock|Class [A-C].*|Ordinary Shares.*|American Depositary.*|ADS.*|New York Registry.*)$", "", item["companyName"]).strip()
        key = name_key(name)
        if key in rows:  # Alphabet A et C : chaque classe affiche la capitalisation de toute l'entreprise
            continue
        known = find_by_name(reference, key) or {}
        rows[key] = {"name": name, "weight": 0 if pd.isna(cap) else float(cap),
                     "country": known.get("country", "United States"), "sector": known.get("sector")}
    return list(rows.values())


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    out_path = data_dir / "etf_lookthrough.json"
    previous = json.loads(out_path.read_text(encoding="utf-8")).get("indices", {}) if out_path.exists() else {}

    indices, reference = {}, {}
    for key, label, code in SPDR_INDICES:
        try:
            response = requests.get(SPDR_URL.format(code), headers=HEADERS, timeout=60)
            response.raise_for_status()
            rows, as_of = parse_spdr(response.content)
            indices[key] = {"label": label, "source": f"Composition de l'ETF SPDR {code.split('-')[0].upper()} au {as_of}", **summarize(rows)}
            if key == "acwi":
                reference = {name_key(r["name"]): r for r in rows}
            logging.info("%s : %d lignes", label, len(rows))
        except Exception as e:  # une source en panne : on garde la composition de la veille
            logging.warning("%s indisponible (%s), composition précédente conservée", label, e)
            if key in previous:
                indices[key] = previous[key]

    try:
        response = requests.get(NASDAQ_URL, headers=HEADERS, timeout=60)
        response.raise_for_status()
        indices["nasdaq100"] = {"label": "Nasdaq 100", "source": "Membres Nasdaq, poids au prorata des capitalisations",
                                **summarize(nasdaq_rows(response.json(), reference))}
    except Exception as e:
        logging.warning("Nasdaq 100 indisponible (%s)", e)
        if "nasdaq100" in previous:
            indices["nasdaq100"] = previous["nasdaq100"]

    screener_path = data_dir / "screener.json"
    if screener_path.exists():
        stocks = json.loads(screener_path.read_text(encoding="utf-8")).get("stocks", [])
        for key, label, index_name in SCREENER_INDICES:
            rows = screener_index_rows(stocks, index_name)
            if rows:
                indices[key] = {"label": label, "source": "Membres du screener, poids au prorata des capitalisations", **summarize(rows)}

    out_path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "indices": indices},
                                   ensure_ascii=False), encoding="utf-8")
    logging.info("%d indices écrits dans %s", len(indices), out_path)


if __name__ == "__main__":
    main()
