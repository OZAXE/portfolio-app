"""
Screener : analyse les actions de universe.csv et écrit screener.json,
lu tel quel par l'onglet Marché de l'appli.

Lancé chaque nuit par GitHub Actions (.github/workflows/screener.yml), en local :
    python screener/run.py --data-dir data --max-fundamentals 20

Fonctionnement incrémental, pour ménager Yahoo :
1. cours du jour de toutes les actions, en quelques appels groupés (rapide) ;
2. fondamentaux (FCF, bilan, ratios) pour les actions les plus anciennement
   analysées seulement, dans la limite d'un budget de temps. Ils ne changent
   qu'à chaque publication de résultats, un rafraîchissement tous les quelques
   jours suffit ;
3. la valeur intrinsèque est gardée d'une nuit sur l'autre, et la marge de
   sécurité recalculée avec le cours du jour.

Si Yahoo bloque (limitation de débit), on fait une pause puis on reprend ;
après plusieurs blocages d'affilée on arrête proprement : ce qui a été
calculé est sauvegardé et la nuit suivante reprend là où on s'est arrêté.
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.data import SOURCE_UNAVAILABLE_ERROR, fetch_company_financials  # noqa: E402
from app.valuation import RELIABLE_RATIO_MAX, RELIABLE_RATIO_MIN, evaluate_company  # noqa: E402

UNIVERSE = Path(__file__).with_name("universe.csv")
OUTPUT_NAME = "screener.json"

PRICE_BATCH = 150
DELAY_BETWEEN_TICKERS = 0.8  # secondes
BLOCKED_PAUSE = 90  # pause après une série de refus de Yahoo
MAX_CONSECUTIVE_BLOCKS = 5  # refus d'affilée avant une pause
MAX_PAUSES = 3  # pauses avant d'abandonner la séance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("screener")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("app.data").setLevel(logging.WARNING)

# Secteurs GICS / ICB / Yahoo -> familles lisibles (premier mot-clé trouvé gagne, d'où l'ordre)
SECTOR_KEYWORDS = [
    ("Immobilier", ("real estate", "reit", "property", "properties")),
    ("Services publics", ("utilit", "electricity", "gas, water", "water")),
    ("Santé", ("health", "pharma", "biotech", "medical")),
    ("Technologie", ("technology", "software", "semiconductor", "information tech", "electronic")),
    ("Communication", ("communication", "telecom", "media", "entertainment")),
    ("Finance", ("financ", "bank", "insurance", "investment", "asset management", "capital market")),
    ("Énergie", ("energy", "oil", "gas", "coal", "renewable")),
    ("Matériaux", ("material", "basic resource", "chemical", "mining", "metal", "construction material", "steel", "paper")),
    ("Consommation", ("consumer", "retail", "food", "beverage", "personal", "household", "travel",
                      "leisure", "hospitality", "automobile", "auto", "tobacco", "apparel", "luxury")),
    ("Industrie", ("industrial", "aerospace", "defense", "construction", "engineering", "transport",
                   "capital goods", "machinery", "logistics", "commerce")),
]


def normalize_sector(*candidates: str | None) -> str:
    for raw in candidates:
        if not raw:
            continue
        text = raw.lower()
        for family, keywords in SECTOR_KEYWORDS:
            if any(k in text for k in keywords):
                return family
    return "Non classé"


def load_universe() -> list[dict]:
    with UNIVERSE.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_previous(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["ticker"]: s for s in data.get("stocks", [])}


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Dernier cours de clôture, par paquets (une requête pour PRICE_BATCH actions)."""
    prices = {}
    for i in range(0, len(tickers), PRICE_BATCH):
        batch = tickers[i:i + PRICE_BATCH]
        try:
            df = yf.download(batch, period="5d", progress=False, auto_adjust=False, threads=True, group_by="ticker")
        except Exception as e:
            log.warning("cours : paquet %d en erreur (%s)", i // PRICE_BATCH, e)
            continue
        for ticker in batch:
            try:
                close = df[ticker]["Close"].dropna() if len(batch) > 1 else df["Close"].dropna()
                if not close.empty:
                    prices[ticker] = float(close.iloc[-1])
            except KeyError:
                pass
        time.sleep(2)
    return prices


def analyze(entry: dict) -> dict:
    """Fondamentaux + valorisation, réduits aux champs utiles au screener."""
    cf = fetch_company_financials(entry["ticker"])
    record = {
        "ticker": entry["ticker"],
        "name": cf.name or entry["name"],
        "region": entry["region"],
        "country": entry["country"],
        "indices": entry["indices"].split("|") if entry["indices"] else [],
        "sector": normalize_sector(cf.sector, entry["sector"], cf.industry),
        "industry": cf.industry,
        "fundamentals_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "error": cf.raw_error,
    }
    if cf.raw_error:
        return record
    v = evaluate_company(cf)
    record.update({
        "currency": cf.currency,
        "price": cf.current_price,
        "price_scale": 1.0,  # cours Yahoo brut -> unité principale (0.01 pour les pence de Londres)
        "market_cap": cf.market_cap,
        "pe": cf.trailing_pe,
        "forward_pe": cf.forward_pe,
        "pb": cf.price_to_book,
        "ev_ebitda": cf.ev_to_ebitda,
        "roe": cf.return_on_equity,
        "operating_margin": cf.operating_margin,
        "debt_to_equity": cf.debt_to_equity,
        "quality_score": v.quality_score,
        "intrinsic_value": v.intrinsic_value_per_share,
        "margin_of_safety": v.margin_of_safety_pct,
        "dcf_reliable": v.dcf_reliable,
        "growth_rate": v.growth_rate_used,
        "discount_rate": v.discount_rate_used,
        "notes": v.notes,
        "data_source": cf.data_source,
    })
    return record


def refresh_with_price(record: dict, raw_price: float) -> None:
    """Cours du jour + marge de sécurité recalculée sur la valeur intrinsèque gardée."""
    price = raw_price * record.get("price_scale", 1.0)
    record["price"] = price
    iv = record.get("intrinsic_value")
    if iv and price:
        record["margin_of_safety"] = round((iv - price) / iv * 100, 1)
        record["dcf_reliable"] = RELIABLE_RATIO_MIN <= iv / price <= RELIABLE_RATIO_MAX


def infer_price_scale(record: dict, raw_price: float | None) -> None:
    """Les cours groupés sont bruts (pence à Londres) alors que l'analyse les a convertis :
    on mémorise le facteur pour les nuits suivantes."""
    if raw_price and record.get("price"):
        ratio = record["price"] / raw_price
        record["price_scale"] = 0.01 if 0.005 < ratio < 0.02 else 1.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--max-fundamentals", type=int, default=600)
    parser.add_argument("--time-budget-min", type=float, default=150)
    args = parser.parse_args()

    started = time.monotonic()
    out_path = Path(args.data_dir) / OUTPUT_NAME
    universe = load_universe()
    previous = load_previous(out_path)
    stocks = {e["ticker"]: previous.get(e["ticker"], {"ticker": e["ticker"]}) for e in universe}
    log.info("univers : %d actions, %d déjà analysées", len(universe), sum("fundamentals_updated" in s for s in stocks.values()))

    prices = fetch_prices(list(stocks))
    log.info("cours récupérés : %d / %d", len(prices), len(stocks))
    for ticker, record in stocks.items():
        if ticker in prices and "intrinsic_value" in record:
            refresh_with_price(record, prices[ticker])

    # Jamais analysées d'abord, puis les plus anciennes
    queue = sorted(universe, key=lambda e: stocks[e["ticker"]].get("fundamentals_updated", ""))
    queue = queue[: args.max_fundamentals]
    done = consecutive_blocks = pauses = 0
    for entry in queue:
        if time.monotonic() - started > args.time_budget_min * 60:
            log.info("budget de temps atteint")
            break
        record = analyze(entry)
        if record["error"] == SOURCE_UNAVAILABLE_ERROR:
            consecutive_blocks += 1
            if consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                pauses += 1
                if pauses > MAX_PAUSES:
                    log.warning("Yahoo bloque toujours, arrêt ; reprise à la prochaine exécution")
                    break
                log.warning("Yahoo bloque, pause de %ds (%d/%d)", BLOCKED_PAUSE, pauses, MAX_PAUSES)
                time.sleep(BLOCKED_PAUSE)
                consecutive_blocks = 0
            continue  # on garde l'ancienne analyse, elle sera retentée
        consecutive_blocks = 0
        infer_price_scale(record, prices.get(entry["ticker"]))
        stocks[entry["ticker"]] = record
        done += 1
        if done % 50 == 0:
            log.info("%d fondamentaux mis à jour", done)
            save(out_path, stocks)  # sauvegarde régulière : rien de perdu si le job est interrompu
        time.sleep(DELAY_BETWEEN_TICKERS)

    save(out_path, stocks)
    log.info("terminé : %d fondamentaux mis à jour en %.0f min", done, (time.monotonic() - started) / 60)


def save(path: Path, stocks: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    analysed = [s for s in stocks.values() if "fundamentals_updated" in s]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_size": len(stocks),
        "analysed": len(analysed),
        "stocks": analysed,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    main()
