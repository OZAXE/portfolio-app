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
import json
import re
import time
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


# Stoxx Europe 600 : composition publiée par Xtrackers (ETF LU0328475792), identifiée par ISIN.
# Conversion ISIN -> ticker via OpenFIGI, en visant la Bourse principale du pays (codes Bloomberg).
STOXX_600_URL = "https://etf.dws.com/etfdata/export/DEU/DEU/excel/product/constituent/LU0328475792/"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
# Pays (libellés allemands du fichier) -> (code de Bourse Bloomberg, suffixe Yahoo, pays affiché)
COUNTRY_EXCHANGES = {
    "Frankreich": ("FP", ".PA", "France"), "Deutschland": ("GY", ".DE", "Allemagne"),
    "Großbritannien (UK)": ("LN", ".L", "Royaume-Uni"), "Schweiz": ("SE", ".SW", "Suisse"),
    "Niederlande": ("NA", ".AS", "Pays-Bas"), "Italien": ("IM", ".MI", "Italie"),
    "Spanien": ("SM", ".MC", "Espagne"), "Schweden": ("SS", ".ST", "Suède"),
    "Dänemark": ("DC", ".CO", "Danemark"), "Norwegen": ("NO", ".OL", "Norvège"),
    "Belgien": ("BB", ".BR", "Belgique"), "Finnland": ("FH", ".HE", "Finlande"),
    "Österreich": ("AV", ".VI", "Autriche"), "Portugal": ("PL", ".LS", "Portugal"),
    "Irland": ("ID", ".IR", "Irlande"), "Griechenland": ("GA", ".AT", "Grèce"),
    "Polen": ("PW", ".WA", "Pologne"),
}
# Sociétés domiciliées ailleurs (Jersey, Luxembourg...) : on essaie les grandes places dans l'ordre
FALLBACK_EXCHANGES = [("LN", ".L", "Royaume-Uni"), ("NA", ".AS", "Pays-Bas"), ("FP", ".PA", "France"),
                      ("GY", ".DE", "Allemagne"), ("BB", ".BR", "Belgique"), ("SM", ".MC", "Espagne"),
                      ("IM", ".MI", "Italie"), ("SE", ".SW", "Suisse"), ("SS", ".ST", "Suède"),
                      ("DC", ".CO", "Danemark"), ("NO", ".OL", "Norvège"), ("FH", ".HE", "Finlande")]
# Conversions ISIN -> ticker déjà faites : évite de tout redemander à OpenFIGI à chaque reconstruction
FIGI_CACHE = Path(__file__).with_name("isin_tickers.json")
# Bourses nordiques : Bloomberg écrit "VOLVB", Yahoo "VOLV-B"
NORDIC_SUFFIXES = (".ST", ".CO", ".HE", ".OL")


def _figi_batch(jobs: list[tuple[str, str]]) -> list[str | None]:
    """Jusqu'à 10 couples (ISIN, code de Bourse) par requête. Réessaie sur coupure réseau ou limite de débit."""
    payload = [{"idType": "ID_ISIN", "idValue": isin, "exchCode": exch} for isin, exch in jobs]
    for attempt in range(5):
        try:
            response = requests.post(OPENFIGI_URL, json=payload, timeout=60)
        except requests.RequestException:
            time.sleep(15 * (attempt + 1))
            continue
        if response.status_code == 429:
            time.sleep(30 * (attempt + 1))
            continue
        time.sleep(2.6)  # 25 requêtes par minute sans clé d'API
        if not response.ok:
            break
        return [next((d["ticker"] for d in (r.get("data") or []) if d.get("ticker")), None) for r in response.json()]
    return [None] * len(jobs)


def _resolve_isins(items: list[tuple[str, list[tuple[str, str, str]]]]) -> dict[str, tuple[str, str, str]]:
    """items : (isin, Bourses candidates dans l'ordre). Renvoie isin -> (ticker Bloomberg, suffixe Yahoo, pays).
    On essaie la 1re Bourse de chaque titre pour tous, puis la 2e pour ceux restés sans réponse, etc."""
    cache = json.loads(FIGI_CACHE.read_text(encoding="utf-8")) if FIGI_CACHE.exists() else {}
    resolved = {isin: tuple(v) for isin, v in cache.items()}
    pending = [(isin, candidates) for isin, candidates in items if isin not in resolved]
    for rank in range(max((len(c) for _, c in pending), default=0)):
        jobs = [(isin, candidates[rank]) for isin, candidates in pending if rank < len(candidates) and isin not in resolved]
        for i in range(0, len(jobs), 10):
            batch = jobs[i:i + 10]
            for (isin, (exch, suffix, country)), ticker in zip(batch, _figi_batch([(isin, c[0]) for isin, c in batch])):
                if ticker:
                    resolved[isin] = (ticker, suffix, country)
            FIGI_CACHE.write_text(json.dumps(resolved, indent=0, sort_keys=True), encoding="utf-8")
    return resolved


def _yahoo_symbol(bloomberg: str, suffix: str, name: str) -> str:
    symbol = bloomberg.rstrip("/").replace("/", "-").replace(" ", "-")  # "RR/" (Rolls-Royce) -> "RR"
    share_class = re.search(r"\b(?:CLASS|SER\.?|SERIES)\s+([A-Z])\b", name.upper())
    if suffix in NORDIC_SUFFIXES and share_class and symbol.endswith(share_class.group(1)) and "-" not in symbol:
        symbol = f"{symbol[:-1]}-{symbol[-1]}"
    return symbol + suffix


def _stoxx_600() -> list[dict]:
    content = requests.get(STOXX_600_URL, headers=HEADERS, timeout=60).content
    raw = pd.read_excel(io.BytesIO(content), header=None)
    header_row = next(i for i in range(10) if "ISIN" in raw.iloc[i].tolist())
    table = raw.iloc[header_row + 1:]
    table.columns = raw.iloc[header_row].tolist()
    table = table[table["Type of Security"] == "Aktien"]

    items, names = [], {}
    for _, row in table.iterrows():
        isin = str(row["ISIN"]).strip()
        names[isin] = str(row["Name"]).strip()
        country = COUNTRY_EXCHANGES.get(row["Country"])
        candidates = [country] + [c for c in FALLBACK_EXCHANGES if c != country] if country else FALLBACK_EXCHANGES
        items.append((isin, candidates))

    resolved = _resolve_isins(items)
    rows = []
    for isin, _ in items:
        if isin not in resolved:
            print(f"   ISIN non converti : {isin} {names[isin]}")
            continue
        ticker, suffix, country = resolved[isin]
        rows.append({"ticker": _yahoo_symbol(ticker, suffix, names[isin]), "name": names[isin].title(), "sector": None, "country": country})
    return rows


def _with_price(tickers: list[str]) -> set[str]:
    """Garde les tickers pour lesquels Yahoo connaît un cours (écarte les conversions ratées)."""
    import yfinance as yf
    ok = set()
    for i in range(0, len(tickers), 150):
        batch = tickers[i:i + 150]
        df = yf.download(batch, period="5d", progress=False, group_by="ticker", auto_adjust=False)
        for t in batch:
            try:
                if not (df[t]["Close"] if len(batch) > 1 else df["Close"]).dropna().empty:
                    ok.add(t)
            except KeyError:
                pass
    return ok


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

    try:
        rows = _stoxx_600()
        valid = _with_price([r["ticker"] for r in rows if r["ticker"] not in universe])
        kept = 0
        for row in rows:
            if row["ticker"] in universe or row["ticker"] in valid:
                add(row["ticker"], row["name"], row["sector"], "Europe", row["country"], "STOXX Europe 600")
                kept += 1
            else:
                print(f"   sans cours chez Yahoo, écarté : {row['ticker']} {row['name']}")
        print(f"STOXX Europe 600 : {len(rows)} lignes, {kept} gardées")
    except Exception as e:
        print(f"!! STOXX Europe 600 ignoré : {e}")

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
