"""
Construit screener/universe.csv : la liste des actions analysées chaque nuit
par le screener, tirée des pages Wikipedia des grands indices.

À relancer de temps en temps (les indices changent à chaque révision
trimestrielle) :
    python screener/build_universe.py

Chaque indice a son propre format de ticker sur Wikipedia : on le convertit
au format Yahoo (suffixe de place : .PA, .L, .T...).
"""

import csv
import io
import re
from pathlib import Path

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio-app screener universe builder)"}
OUTPUT = Path(__file__).with_name("universe.csv")


def _tables(url: str) -> list[pd.DataFrame]:
    html = requests.get(url, headers=HEADERS, timeout=30).text
    return pd.read_html(io.StringIO(html))


def _table_with(url: str, column: str) -> pd.DataFrame:
    for table in _tables(url):
        if column in table.columns and len(table) >= 15:
            return table
    raise ValueError(f"aucune table avec la colonne {column!r} sur {url}")


def _after_colon(value: str) -> str:
    """'OSE: AKRBP' -> 'AKRBP' (les espaces insécables de Wikipedia inclus)."""
    return str(value).replace("\xa0", " ").split(":")[-1].strip()


def _first(row: pd.Series, *columns: str) -> str | None:
    for column in columns:
        if column in row and pd.notna(row[column]):
            return str(row[column]).strip()
    return None


# (clé, url, colonne du ticker, conversion vers Yahoo, région, pays, colonnes nom, colonnes secteur)
SOURCES = [
    ("S&P 500", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol",
     lambda t: t.replace(".", "-"), "US", "États-Unis", ("Security",), ("GICS Sector",)),
    ("CAC 40", "https://en.wikipedia.org/wiki/CAC_40", "Ticker",
     lambda t: t, "Europe", None, ("Company",), ("Sector",)),
    ("CAC Next 20", "https://en.wikipedia.org/wiki/CAC_Next_20", "Ticker symbol",
     lambda t: _after_colon(t) + ".PA", "Europe", "France", ("Company",), ("ICB Sector",)),
    ("OMX Helsinki 25", "https://en.wikipedia.org/wiki/OMX_Helsinki_25", "Ticker",
     lambda t: t, "Europe", "Finlande", ("Company",), ("GICS sector",)),
    ("PSI", "https://en.wikipedia.org/wiki/PSI-20", "Ticker",
     lambda t: t + ".LS", "Europe", "Portugal", ("Company",), ("Industry",)),
    ("ISEQ 20", "https://en.wikipedia.org/wiki/ISEQ_20", "MNEM code",
     lambda t: _after_colon(t) + ".IR", "Europe", "Irlande", ("Company",), ()),
    ("DAX", "https://en.wikipedia.org/wiki/DAX", "Ticker",
     lambda t: t, "Europe", None, ("Company",), ("Prime Standard Sector",)),
    ("EURO STOXX 50", "https://en.wikipedia.org/wiki/EURO_STOXX_50", "Ticker",
     lambda t: t, "Europe", None, ("Name",), ("Sector",)),
    ("FTSE 100", "https://en.wikipedia.org/wiki/FTSE_100_Index", "Ticker",
     lambda t: t.rstrip(".").replace(".", "-") + ".L", "Europe", "Royaume-Uni", ("Company",),
     ("FTSE industry classification benchmark sector[39]",)),
    ("FTSE 250", "https://en.wikipedia.org/wiki/FTSE_250_Index", "Ticker",
     lambda t: t.rstrip(".").replace(".", "-") + ".L", "Europe", "Royaume-Uni", ("Company",),
     ("FTSE Industry Classification Benchmark sector[13]",)),
    ("SMI", "https://en.wikipedia.org/wiki/Swiss_Market_Index", "Ticker",
     lambda t: t + ".SW", "Europe", "Suisse", ("Name",), ("Sector",)),
    ("AEX", "https://en.wikipedia.org/wiki/AEX_index", "Ticker",
     lambda t: t, "Europe", None, ("Company",), ("ICB Sector",)),
    ("IBEX 35", "https://en.wikipedia.org/wiki/IBEX_35", "Ticker",
     lambda t: t, "Europe", None, ("Company",), ("Sector",)),
    ("FTSE MIB", "https://en.wikipedia.org/wiki/FTSE_MIB", "Ticker",
     lambda t: t, "Europe", None, ("Company",), ("ICB Sector",)),
    ("OMX Stockholm 30", "https://en.wikipedia.org/wiki/OMX_Stockholm_30", "Ticker",
     lambda t: t, "Europe", "Suède", ("Company",), ("GICS sector",)),
    ("OMX Copenhagen 25", "https://en.wikipedia.org/wiki/OMX_Copenhagen_25", "Ticker symbol",
     lambda t: t.replace(" ", "-") + ".CO", "Europe", "Danemark", ("Company",), ("ICB Sector",)),
    ("OBX", "https://en.wikipedia.org/wiki/OBX_Index", "Ticker symbol",
     lambda t: _after_colon(t) + ".OL", "Europe", "Norvège", ("Company",), ("ICB subsector",)),
    ("BEL 20", "https://en.wikipedia.org/wiki/BEL_20", "Ticker symbol",
     lambda t: _after_colon(t) + ".BR", "Europe", "Belgique", ("Company",), ("ICB Sector",)),
    ("Hang Seng", "https://en.wikipedia.org/wiki/Hang_Seng_Index", "Ticker",
     lambda t: _after_colon(t).zfill(4) + ".HK", "Asie", "Hong Kong", ("Name",), ("Sub-index",)),
    ("KOSPI 200", "https://en.wikipedia.org/wiki/KOSPI_200", "Symbol",
     lambda t: str(t).zfill(6) + ".KS", "Asie", "Corée du Sud", ("Company",), ("GICS Sector",)),
]

# Pays déduit du suffixe Yahoo pour les indices multi-pays
SUFFIX_COUNTRY = {
    ".PA": "France", ".DE": "Allemagne", ".AS": "Pays-Bas", ".MC": "Espagne", ".MI": "Italie",
    ".BR": "Belgique", ".HE": "Finlande", ".IR": "Irlande", ".LS": "Portugal", ".L": "Royaume-Uni",
    ".SW": "Suisse", ".ST": "Suède", ".CO": "Danemark", ".OL": "Norvège", ".T": "Japon",
    ".HK": "Hong Kong", ".KS": "Corée du Sud", ".TW": "Taïwan",
}


def _country(ticker: str, default: str | None) -> str | None:
    match = re.search(r"\.[A-Z]+$", ticker)
    return SUFFIX_COUNTRY.get(match.group(0), default) if match else default or "États-Unis"


def _nikkei_225() -> list[dict]:
    """Page japonaise : composants répartis en plusieurs tables par secteur, code à 4 chiffres."""
    rows = []
    for table in _tables("https://ja.wikipedia.org/wiki/%E6%97%A5%E7%B5%8C%E5%B9%B3%E5%9D%87%E6%A0%AA%E4%BE%A1"):
        if "証券コード" not in table.columns:
            continue
        for _, row in table.iterrows():
            code = re.sub(r"\D", "", str(row["証券コード"]))
            if len(code) == 4:
                rows.append({"ticker": f"{code}.T", "name": _first(row, "銘柄"), "sector": None})
    return rows


def _taiwan_50() -> list[dict]:
    """Table sur deux colonnes de paires (code, nom)."""
    table = _tables("https://zh.wikipedia.org/wiki/%E8%87%BA%E7%81%A350%E6%8C%87%E6%95%B8")[0]
    rows = []
    for code_col, name_col in (("股票代號", "名稱"), ("股票代號.1", "名稱.1")):
        for _, row in table.iterrows():
            code = re.sub(r"\D", "", str(row.get(code_col, "")))
            if len(code) == 4:
                rows.append({"ticker": f"{code}.TW", "name": _first(row, name_col), "sector": None})
    return rows


def build() -> list[dict]:
    universe: dict[str, dict] = {}

    def add(ticker, name, sector, region, country, index):
        if not ticker or ticker.lower() == "nan":
            return
        entry = universe.setdefault(ticker, {
            "ticker": ticker, "name": name, "sector": sector, "region": region,
            "country": _country(ticker, country), "indices": [],
        })
        entry["sector"] = entry["sector"] or sector
        entry["indices"].append(index)

    for index, url, col, to_yahoo, region, country, name_cols, sector_cols in SOURCES:
        try:
            table = _table_with(url, col)
        except Exception as e:
            print(f"!! {index} ignoré : {e}")
            continue
        for _, row in table.iterrows():
            raw = str(row[col]).replace("\xa0", " ").strip()
            add(to_yahoo(raw), _first(row, *name_cols), _first(row, *sector_cols), region, country, index)
        print(f"{index} : {len(table)} lignes")

    for index, loader in (("Nikkei 225", _nikkei_225), ("Taiwan 50", _taiwan_50)):
        try:
            rows = loader()
        except Exception as e:
            print(f"!! {index} ignoré : {e}")
            continue
        for row in rows:
            add(row["ticker"], row["name"], row["sector"], "Asie", None, index)
        print(f"{index} : {len(rows)} lignes")

    return sorted(universe.values(), key=lambda e: e["ticker"])


def main():
    universe = build()
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "name", "sector", "region", "country", "indices"])
        writer.writeheader()
        for entry in universe:
            writer.writerow({**entry, "indices": "|".join(entry["indices"])})
    print(f"{len(universe)} actions écrites dans {OUTPUT}")


if __name__ == "__main__":
    main()
