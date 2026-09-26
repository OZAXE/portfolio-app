"""
Historique financier annuel de chaque action du screener, un fichier par action
(data/financials/<ticker>.json), affiché en graphiques sur la fiche de l'appli.

- États-Unis : comptes déposés à la SEC (API XBRL "companyfacts"), environ 15 à 19 ans.
- Europe / Asie : Yahoo ne donne que les 4 derniers exercices. Chaque passage fusionne
  les nouveaux exercices avec ceux déjà archivés : l'historique s'allonge d'année en année.

Lancé chaque nuit après le screener, sur un lot limité (les plus anciens d'abord) :
    python screener/financials.py --data-dir data --max 300 --time-budget-min 25
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.data import _number  # noqa: E402

UNIVERSE = Path(__file__).with_name("universe.csv")
SEC_HEADERS = {"User-Agent": "portfolio-app enzocabos192004@gmail.com", "Accept-Encoding": "gzip, deflate"}
SEC_DELAY = 0.15
REFRESH_AFTER_DAYS = 7  # les comptes annuels changent rarement : un passage par semaine suffit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("financials")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Indicateur -> concepts US-GAAP possibles, par ordre de préférence (les sociétés changent de libellé)
SEC_CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
# Le dividende par action vient de l'historique des versements (Yahoo, dans screener.json) :
# certaines sociétés déclarent à la SEC un montant trimestriel sous le concept annuel
INSTANT_METRICS = {"equity", "long_term_debt"}  # valeurs de bilan (à une date), pas des flux sur l'année

# Lignes Yahoo pour les mêmes indicateurs
YAHOO_ROWS = {
    "revenue": ("income_stmt", ["Total Revenue", "Operating Revenue"]),
    "operating_income": ("income_stmt", ["Operating Income"]),
    "net_income": ("income_stmt", ["Net Income", "Net Income Common Stockholders"]),
    "eps": ("income_stmt", ["Diluted EPS", "Basic EPS"]),
    "shares": ("income_stmt", ["Diluted Average Shares", "Basic Average Shares"]),
    "operating_cash_flow": ("cashflow", ["Operating Cash Flow"]),
    "capex": ("cashflow", ["Capital Expenditure"]),
    "equity": ("balance_sheet", ["Stockholders Equity", "Common Stock Equity"]),
    "long_term_debt": ("balance_sheet", ["Long Term Debt"]),
}


def sec_get(url: str) -> requests.Response:
    time.sleep(SEC_DELAY)
    response = requests.get(url, headers=SEC_HEADERS, timeout=90)
    response.raise_for_status()
    return response


def sec_cik_map() -> dict[str, int]:
    data = sec_get("https://www.sec.gov/files/company_tickers.json").json()
    return {v["ticker"].replace(".", "-"): v["cik_str"] for v in data.values()}


def _annual_facts(facts: list[dict], instant: bool) -> dict[int, float]:
    """Valeurs annuelles des rapports 10-K : un exercice complet (environ 365 jours) pour un flux,
    la date de clôture pour un poste de bilan. En cas de retraitement, le dépôt le plus récent gagne."""
    by_year: dict[int, tuple[str, float]] = {}
    for f in facts:
        if not f.get("form", "").startswith("10-K") or "end" not in f:
            continue
        if not instant:
            if "start" not in f:
                continue
            days = (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days
            if not 330 <= days <= 400:
                continue
        year = int(f["end"][:4])
        if year not in by_year or f.get("filed", "") > by_year[year][0]:
            by_year[year] = (f.get("filed", ""), f["val"])
    return {y: v for y, (_, v) in by_year.items()}


def from_sec(cik: int) -> dict:
    gaap = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()["facts"].get("us-gaap", {})
    years: dict[int, dict] = {}
    for metric, concepts in SEC_CONCEPTS.items():
        for concept in concepts:  # le premier concept renseigné pour une année l'emporte
            units = gaap.get(concept, {}).get("units", {})
            facts = next((units[u] for u in ("USD", "USD/shares", "shares") if u in units), None)
            if not facts:
                continue
            for year, value in _annual_facts(facts, metric in INSTANT_METRICS).items():
                years.setdefault(year, {}).setdefault(metric, value)
    return {"currency": "USD", "source": "SEC (10-K)", "years": years}


def from_yahoo(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    years: dict[int, dict] = {}
    for metric, (statement, rows) in YAHOO_ROWS.items():
        df = getattr(t, statement)
        if df is None or df.empty:
            continue
        row = next((r for r in rows if r in df.index), None)
        if row is None:
            continue
        for column, value in df.loc[row].items():
            value = _number(value)
            if value is not None:
                years.setdefault(column.year, {})[metric] = value
    # Yahoo compte les investissements en négatif, la SEC en positif : on aligne sur la SEC
    for values in years.values():
        if values.get("capex") is not None:
            values["capex"] = abs(values["capex"])
    try:
        currency = t.info.get("financialCurrency")
    except Exception:
        currency = None
    return {"currency": currency, "source": "Yahoo Finance (4 derniers exercices, archivés au fil des ans)", "years": years}


def with_ratios(values: dict) -> dict:
    """Ajoute les ratios dérivés à une année : cash-flow libre, marges, ROE."""
    v = dict(values)
    if v.get("operating_cash_flow") is not None and v.get("capex") is not None:
        v["free_cash_flow"] = v["operating_cash_flow"] - v["capex"]
    revenue = v.get("revenue")
    if revenue:
        if v.get("operating_income") is not None:
            v["operating_margin"] = v["operating_income"] / revenue
        if v.get("net_income") is not None:
            v["net_margin"] = v["net_income"] / revenue
    if v.get("net_income") is not None and v.get("equity"):
        v["roe"] = v["net_income"] / v["equity"]
    return v


def merge(existing: dict | None, fresh: dict) -> dict:
    """Garde les exercices archivés, remplace ceux que la nouvelle source fournit à nouveau."""
    years = {int(y["year"]): {k: val for k, val in y.items() if k != "year"} for y in (existing or {}).get("years", [])}
    for year, values in fresh["years"].items():
        years[int(year)] = {**years.get(int(year), {}), **values}
    current_year = datetime.now(timezone.utc).year
    return {
        "currency": fresh["currency"] or (existing or {}).get("currency"),
        "source": fresh["source"],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "years": [{"year": y, **with_ratios(v)} for y, v in sorted(years.items()) if y <= current_year],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--max", type=int, default=300)
    parser.add_argument("--time-budget-min", type=float, default=25)
    args = parser.parse_args()
    started = time.monotonic()

    out_dir = Path(args.data_dir) / "financials"
    out_dir.mkdir(parents=True, exist_ok=True)
    with UNIVERSE.open(encoding="utf-8") as f:
        universe = list(csv.DictReader(f))

    def last_update(ticker: str) -> str:
        path = out_dir / f"{ticker}.json"
        if not path.exists():
            return ""
        return json.loads(path.read_text(encoding="utf-8")).get("updated", "")

    now = datetime.now(timezone.utc)
    queue = []
    for entry in universe:
        updated = last_update(entry["ticker"])
        if not updated or (now - datetime.fromisoformat(updated)).days >= REFRESH_AFTER_DAYS:
            queue.append((updated, entry))
    queue.sort(key=lambda x: x[0])  # jamais faits d'abord, puis les plus anciens
    log.info("historique financier : %d actions à mettre à jour, lot de %d", len(queue), args.max)

    ciks = sec_cik_map()
    done = 0
    for _, entry in queue[: args.max]:
        if time.monotonic() - started > args.time_budget_min * 60:
            log.info("budget de temps atteint")
            break
        ticker = entry["ticker"]
        path = out_dir / f"{ticker}.json"
        try:
            is_us = entry["region"] == "US" and ticker in ciks
            fresh = from_sec(ciks[ticker]) if is_us else from_yahoo(ticker)
            if not fresh["years"]:
                continue
            existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            path.write_text(json.dumps({"ticker": ticker, **merge(existing, fresh)}, separators=(",", ":")), encoding="utf-8")
            done += 1
        except Exception as e:
            log.warning("%s : historique en erreur (%s)", ticker, e)
    log.info("historique financier : %d actions mises à jour", done)


if __name__ == "__main__":
    main()
