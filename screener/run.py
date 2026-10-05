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
3. la valeur intrinsèque et les ingrédients du prix juste sont gardés d'une
   nuit sur l'autre ; la marge de sécurité et le verdict du prix juste sont
   recalculés avec le cours du jour.

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
from app.sectors import normalize_sector  # noqa: E402
from app.valuation import RELIABLE_RATIO_MAX, RELIABLE_RATIO_MIN, blend_fair_value, evaluate_company  # noqa: E402
from app.metrics import fcf_yield  # noqa: E402
from translate_profiles import keep_translation  # noqa: E402
from followed import load_followed  # noqa: E402

UNIVERSE = Path(__file__).with_name("universe.csv")
OUTPUT_NAME = "screener.json"
HISTORY_NAME = "history.json"
# Présentations des entreprises, un petit fichier par action (profiles/<ticker>.json) : ~1,5 ko de texte
# par société triplerait screener.json, que l'appli télécharge en entier à chaque ouverture
PROFILES_DIR = "profiles"
HISTORY_EVERY_DAYS = 6  # un relevé par semaine (le run du samedi, après la clôture du vendredi)

# Valeurs de la veille gardées sur chaque fiche : les alertes comparent avec elles
TRACKED_FIELDS = ("price", "intrinsic_value", "margin_of_safety", "dcf_reliable", "quality_score", "dividend_cut")

PRICE_BATCH = 150
DELAY_BETWEEN_TICKERS = 0.8  # secondes
BLOCKED_PAUSE = 90  # pause après une série de refus de Yahoo
MAX_CONSECUTIVE_BLOCKS = 5  # refus d'affilée avant une pause
MAX_PAUSES = 3  # pauses avant d'abandonner la séance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("screener")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("app.data").setLevel(logging.WARNING)

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


def load_archive(data_dir: Path | None, ticker: str) -> dict:
    """Comptes annuels et PER historique archivés par screener/financials.py (vide tant que l'action n'y est pas
    passée)."""
    path = data_dir / "financials" / f"{ticker}.json" if data_dir else None
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_pe_history(data_dir: Path | None, ticker: str) -> dict | None:
    """PER historique archivé par screener/financials.py (absent tant que l'action n'y est pas passée)."""
    return load_archive(data_dir, ticker).get("pe_history")


def analyze(entry: dict, data_dir: Path | None = None) -> dict:
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
    if entry.get("followed"):
        record["followed"] = True  # titre de watchlist hors univers (followed.py), retiré quand plus personne ne le suit
        # Un ETF mis en watchlist n'a pas de comptes d'entreprise : fiche en erreur, que le Marché n'affiche pas (il
        # le trouve dans « Tes autres titres ») ; elle garde sa date pour ne pas repasser en tête chaque nuit
        if cf.quote_type and cf.quote_type != "EQUITY" and not cf.raw_error:
            record["error"] = f"pas une action ({cf.quote_type})"
    if record["error"]:
        return record
    archive = load_archive(data_dir, entry["ticker"])
    v = evaluate_company(cf, archive.get("pe_history"), archive.get("years"))
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
        "dividend_yield": cf.dividend_yield,
        "dividend_rate": cf.dividend_rate,
        "dividend_ttm": cf.dividend_ttm,
        "payout_ratio": cf.payout_ratio,
        "dividend_growth_5y": cf.dividend_growth_5y,
        "dividend_growth_10y": cf.dividend_growth_10y,
        "dividend_streak": cf.dividend_streak,
        "dividend_cut": cf.dividend_cut,
        "dividend_history": cf.dividend_history,
        "target_price": cf.target_mean_price,
        "target_low": cf.target_low_price,
        "target_high": cf.target_high_price,
        "recommendation": cf.recommendation_mean,
        "analyst_count": cf.analyst_count,
        "earnings_date": cf.earnings_date,
        "base_fcf": v.base_fcf,
        "net_debt": v.net_debt,
        "shares": v.shares_used,
        "fair_value": v.fair_value,
        "fair_value_low": v.fair_value_low,
        "fair_value_high": v.fair_value_high,
        "fair_value_upside_pct": v.fair_value_upside_pct,
        "fair_value_verdict": v.fair_value_verdict,
        "fair_value_divergent": v.fair_value_divergent,
        "fair_value_pe": v.fair_value_pe,
        "fair_value_pb": v.fair_value_pb,
        "fair_pe_used": v.fair_pe_used,
        "fair_value_hist_pe": v.fair_value_hist_pe,
        "hist_pe_median": v.hist_pe_median,
        "hist_pe_years": v.hist_pe_years,
        "shares_cagr": v.shares_cagr,
        "shares_years": v.shares_years,
        "fcf_per_share": v.fcf_per_share,
        "fcf_yield": v.fcf_yield,
        "net_debt_ebitda": v.net_debt_ebitda,
        "roic": v.roic,
        "roic_median": v.roic_median,
        "roic_years": v.roic_years,
        "interest_coverage": v.interest_coverage,
        "revenue_cagr": v.revenue_cagr,
        "revenue_years": v.revenue_years,
        "eps_cagr": v.eps_cagr,
        "eps_years": v.eps_years,
        "justified_pb_used": v.justified_pb_used,
        "notes": v.notes,
        "data_source": cf.data_source,
        "profile": company_profile(cf),
    })
    return record


def company_profile(cf) -> dict | None:
    """Présentation affichée dans la fiche. Absente quand quoteSummary est bloqué (STATEMENTS_SOURCE)."""
    if not cf.summary:
        return None
    return {"summary": cf.summary, "website": cf.website, "employees": cf.employees,
            "updated": datetime.now(timezone.utc).date().isoformat()}


def save_profile(data_dir: Path, ticker: str, profile: dict | None) -> None:
    """Sans nouvelle présentation (Yahoo partiellement bloqué), l'ancien fichier reste en place. La traduction
    française (translate_profiles.py) est gardée tant que le texte anglais n'a pas changé."""
    if not profile:
        return
    out_dir = data_dir / PROFILES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker}.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        old = None
    path.write_text(json.dumps(keep_translation(profile, old), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def refresh_with_price(record: dict, raw_price: float) -> None:
    """Cours du jour + marge de sécurité et prix juste recalculés sur les valeurs gardées."""
    price = raw_price * record.get("price_scale", 1.0)
    record["price"] = price
    iv = record.get("intrinsic_value")
    if iv and price:
        record["margin_of_safety"] = round((iv - price) / iv * 100, 1)
        record["dcf_reliable"] = RELIABLE_RATIO_MIN <= iv / price <= RELIABLE_RATIO_MAX
    if record.get("fcf_per_share") is not None:
        record["fcf_yield"] = fcf_yield(record["fcf_per_share"], price)
    # Fiches analysées avant l'arrivée du prix juste : complétées à leur prochaine analyse
    if "fair_value_pe" in record:
        record.update(blend_fair_value(price, iv, record.get("fair_value_pe"), record.get("fair_value_pb"),
                                       record.get("fair_value_hist_pe")))


def infer_price_scale(record: dict, raw_price: float | None) -> None:
    """Les cours groupés sont bruts (pence à Londres) alors que l'analyse les a convertis :
    on mémorise le facteur pour les nuits suivantes."""
    if raw_price and record.get("price"):
        ratio = record["price"] / raw_price
        record["price_scale"] = 0.01 if 0.005 < ratio < 0.02 else 1.0


def add_market_cap_eur(stocks: dict[str, dict]) -> None:
    """Capitalisation en euros, pour pouvoir trier ensemble des actions cotées en KRW, JPY, USD..."""
    currencies = {s["currency"] for s in stocks.values() if s.get("currency") and s["currency"] != "EUR"}
    rates = {"EUR": 1.0}
    pairs = [f"{c}EUR=X" for c in currencies]
    if pairs:
        try:
            df = yf.download(pairs, period="5d", progress=False, auto_adjust=False, group_by="ticker")
            for c in currencies:
                close = (df[f"{c}EUR=X"]["Close"] if len(pairs) > 1 else df["Close"]).dropna()
                if not close.empty:
                    rates[c] = float(close.iloc[-1])
        except Exception as e:
            log.warning("taux de change en erreur (%s)", e)
    for s in stocks.values():
        rate = rates.get(s.get("currency"))
        s["market_cap_eur"] = s["market_cap"] * rate if s.get("market_cap") and rate else None


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
    universe += load_followed(previous, {e["ticker"] for e in universe})
    stocks = {e["ticker"]: previous.get(e["ticker"], {"ticker": e["ticker"]}) for e in universe}
    for e in universe:
        if e.get("followed"):  # même avant sa première analyse réussie : la liste de secours de followed.py le lit
            stocks[e["ticker"]]["followed"] = True
    for record in stocks.values():
        for field in TRACKED_FIELDS:
            if field in record:
                record[f"prev_{field}"] = record[field]
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
        try:
            record = analyze(entry, Path(args.data_dir))
        except Exception as e:  # une donnée inattendue sur une action ne doit pas arrêter tout le screener
            # Journaux publics : le ticker d'une watchlist n'y apparaît pas
            log.warning("%s : analyse en erreur (%s)", "titre suivi" if entry.get("followed") else entry["ticker"], e)
            # L'analyse précédente reste affichée si elle existe ; la date avance pour passer à la suite
            record = {**stocks[entry["ticker"]], "fundamentals_updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if record.get("price") is None:
                record["error"] = f"analyse en erreur : {e}"
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
        save_profile(Path(args.data_dir), entry["ticker"], record.pop("profile", None))
        infer_price_scale(record, prices.get(entry["ticker"]))
        stocks[entry["ticker"]] = record
        done += 1
        if done % 50 == 0:
            log.info("%d fondamentaux mis à jour", done)
            save(out_path, stocks)  # sauvegarde régulière : rien de perdu si le job est interrompu
        time.sleep(DELAY_BETWEEN_TICKERS)

    add_market_cap_eur(stocks)
    save(out_path, stocks)
    update_history(Path(args.data_dir) / HISTORY_NAME, stocks)
    log.info("terminé : %d fondamentaux mis à jour en %.0f min", done, (time.monotonic() - started) / 60)


def update_history(path: Path, stocks: dict[str, dict]) -> None:
    """Relevé hebdomadaire compact : pour chaque action, [cours, valeur intrinsèque, marge, score, DCF fiable,
    prix juste]. Les séries sont alignées sur la liste des dates (None quand l'action n'avait pas de données).
    Le prix juste (6e valeur) est arrivé en septembre 2026 : les relevés plus anciens n'en ont que 5, et une
    fiche pas encore réanalysée depuis son arrivée donne None, jamais un faux chiffre."""
    history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"dates": [], "series": {}}
    today = datetime.now(timezone.utc).date()
    if history["dates"] and (today - datetime.fromisoformat(history["dates"][-1]).date()).days < HISTORY_EVERY_DAYS:
        return

    def rounded(x, digits):
        return round(x, digits) if isinstance(x, (int, float)) else None

    n = len(history["dates"])
    history["dates"].append(today.isoformat())
    for ticker, s in stocks.items():
        if s.get("error") or s.get("price") is None:
            point = None
        else:
            point = [rounded(s.get("price"), 4), rounded(s.get("intrinsic_value"), 2), rounded(s.get("margin_of_safety"), 1),
                     rounded(s.get("quality_score"), 1), 1 if s.get("dcf_reliable") else 0, rounded(s.get("fair_value"), 2)]
        series = history["series"].setdefault(ticker, [None] * n)
        series.extend([None] * (n - len(series)))  # action entrée dans l'univers en cours de route
        series.append(point)
    path.write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")
    log.info("historique : relevé du %s ajouté (%d relevés)", today, len(history["dates"]))


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
