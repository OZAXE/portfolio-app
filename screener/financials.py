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

import math
from statistics import median

import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.data import MINOR_CURRENCIES, _number  # noqa: E402
from app.metrics import cagr  # noqa: E402

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
    # Pour le ROIC et la couverture des intérêts (metrics.py, octobre 2026)
    "short_term_debt": ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
}
# Le dividende par action vient de l'historique des versements (Yahoo, dans screener.json) :
# certaines sociétés déclarent à la SEC un montant trimestriel sous le concept annuel
INSTANT_METRICS = {"equity", "long_term_debt", "short_term_debt", "cash"}  # valeurs de bilan (à une date), pas des flux sur l'année

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
    "short_term_debt": ("balance_sheet", ["Current Debt", "Current Debt And Capital Lease Obligation"]),
    "cash": ("balance_sheet", ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]),
    "pretax_income": ("income_stmt", ["Pretax Income"]),
    "income_tax": ("income_stmt", ["Tax Provision"]),
    "interest_expense": ("income_stmt", ["Interest Expense", "Interest Expense Non Operating"]),
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
    # Yahoo compte les investissements (et parfois les intérêts) en négatif, la SEC en positif : on aligne sur la SEC
    for values in years.values():
        for key in ("capex", "interest_expense"):
            if values.get(key) is not None:
                values[key] = abs(values[key])
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


# PER historique propre à l'action : cours moyen de chaque année / bénéfice par action de l'année
PE_HISTORY_YEARS = 10
PE_MIN_YEARS = 3  # en dessous, une médiane ne veut rien dire
PE_MAX = 100  # au-delà, bénéfice quasi nul (année de crise) : le PER de l'année ne dit rien
MIN_MONTHS = 6  # cours moyen d'une année calculé sur au moins 6 clôtures mensuelles


def adjusted_shares(shares: float, year: int, splits: list[tuple[date, float]], reference: float) -> float:
    """Nombre d'actions d'un exercice ramené à la base actuelle. Les cours Yahoo sont corrigés des divisions
    d'actions, mais un ancien rapport donne le nombre d'actions d'avant (Apple, division par 4 en 2020 :
    ~4,3 milliards d'actions en 2019 dans le 10-K de 2019, ~17 milliards après). Les rapports récents, eux,
    retraitent les exercices comparés. On essaie donc chaque produit des divisions postérieures à l'exercice
    et on garde le plus proche du nombre d'actions actuel : un rachat ou une émission ne change le nombre
    d'actions que de quelques % par an, une division le multiplie d'un coup. Une division en cours d'exercice
    compte aussi (nombre moyen d'actions de l'année à cheval sur les deux bases)."""
    later = [ratio for day, ratio in sorted(splits) if day >= date(year, 1, 1) and ratio > 0]
    candidates = [shares * math.prod(later[k:]) for k in range(len(later) + 1)]
    return min(candidates, key=lambda c: abs(math.log(c / reference)))


def historical_pe(years: list[dict], closes: dict[int, list[float]], splits: list[tuple[date, float]],
                  shares_now: float | None = None) -> dict | None:
    """PER de chaque exercice des 10 dernières années (cours moyen de l'année civile / bénéfice net par action
    ramené à la base actuelle), leur médiane et le bénéfice par action du dernier exercice. Le cours et le
    bénéfice viennent chacun d'une seule source : un prix juste = médiane x BPA reste dans l'unité du cours.
    closes : clôtures mensuelles corrigées des divisions, par année civile. shares_now : nombre d'actions
    actuel (screener), sur la même base que les cours ; le BPA actuel en dépend plutôt que du dernier rapport,
    qui peut être sur l'ancienne base (Air Liquide 2025 : 579 millions d'actions en moyenne sur l'exercice,
    ~637 millions aujourd'hui après l'attribution gratuite de juin 2025, 1 pour 10, dont Yahoo corrige les cours)."""
    usable = [y for y in years if y.get("net_income") is not None and y.get("shares")]
    if not usable:
        return None
    latest = max(usable, key=lambda y: y["year"])
    reference = shares_now or latest["shares"] * math.prod(r for d, r in splits if d > date(latest["year"], 12, 31) and r > 0)
    points = []
    for y in usable:
        prices = closes.get(y["year"], [])
        if y["year"] <= latest["year"] - PE_HISTORY_YEARS or len(prices) < MIN_MONTHS:
            continue
        eps = y["net_income"] / adjusted_shares(y["shares"], y["year"], splits, reference)
        pe = (sum(prices) / len(prices)) / eps if eps > 0 else None
        if pe is not None and 0 < pe <= PE_MAX:
            points.append({"year": y["year"], "pe": round(pe, 1)})
    points.sort(key=lambda p: p["year"])
    eps_now = latest["net_income"] / reference
    # Croissance du bénéfice par action, chaque exercice ramené à la base d'actions actuelle (divisions, actions
    # gratuites) : les rachats d'actions la font monter plus vite que le bénéfice total
    growth = cagr({y["year"]: y["net_income"] / adjusted_shares(y["shares"], y["year"], splits, reference) for y in usable})
    return {"years": points, "median": round(median(p["pe"] for p in points), 1) if len(points) >= PE_MIN_YEARS else None,
            "eps": round(eps_now, 4) if eps_now > 0 else None, "eps_year": latest["year"],
            "eps_cagr": round(growth[0], 4) if growth else None, "eps_years": growth[1] if growth else None,
            **shares_trend(usable, splits, reference)}


SHARES_TREND_YEARS = 5


def shares_trend(years: list[dict], splits: list[tuple[date, float]], reference: float) -> dict:
    """Évolution annuelle moyenne du nombre d'actions sur 5 exercices au plus (au moins 2), sur la base
    actuelle : négative quand l'entreprise rachète ses actions (chaque action restante détient une plus grande
    part du bénéfice), positive quand elle en émet (dilution). Ex. Apple 2020 -> 2025 : 17,5 -> 15,0 milliards
    d'actions, (15,0 / 17,5)^(1/5) - 1 = -3,0 % par an."""
    by_year = {y["year"]: adjusted_shares(y["shares"], y["year"], splits, reference) for y in years}
    latest = max(by_year)
    start = next((latest - k for k in range(SHARES_TREND_YEARS, 1, -1) if latest - k in by_year), None)
    if start is None:
        return {"shares_cagr": None, "shares_years": None}
    span = latest - start
    return {"shares_cagr": round((by_year[latest] / by_year[start]) ** (1 / span) - 1, 4), "shares_years": span}


def fetch_pe_history(ticker: str, years: list[dict], reporting_currency: str | None,
                     shares_now: float | None = None) -> dict | None:
    """Clôtures mensuelles sur 11 ans (API chart de Yahoo) et divisions d'actions. Pas de PER historique
    quand comptes et cotation sont dans deux devises (Shell : dollars / pence) : le change sur 10 ans
    fausserait les PER passés, même règle que le DCF."""
    t = yf.Ticker(ticker)
    history = t.history(period="11y", interval="1mo", auto_adjust=False)
    if history is None or history.empty:
        return None
    currency = (t.history_metadata or {}).get("currency")
    factor = 1.0
    if currency in MINOR_CURRENCIES:
        currency, factor = MINOR_CURRENCIES[currency]
    if reporting_currency and currency and reporting_currency != currency:
        return {"skipped": f"comptes en {reporting_currency}, cotation en {currency}"}
    closes: dict[int, list[float]] = {}
    for day, close in history["Close"].dropna().items():
        closes.setdefault(day.year, []).append(float(close) / factor)
    splits = [(d.date(), float(r)) for d, r in t.splits.items()] if t.splits is not None else []
    return historical_pe(years, closes, splits, shares_now)


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
    # Nombre d'actions actuel de chaque fiche du screener (lancé juste avant, même dossier)
    screener_path = Path(args.data_dir) / "screener.json"
    stocks = json.loads(screener_path.read_text(encoding="utf-8")).get("stocks", []) if screener_path.exists() else []
    shares_now = {st["ticker"]: st["shares"] for st in stocks if st.get("shares")}
    # Titres de watchlist hors univers (followed.py) : même historique que les autres (PER historique, ROIC)
    universe += [{"ticker": st["ticker"], "region": st.get("region", ""), "followed": True} for st in stocks
                 if st.get("followed") and not st.get("error")]

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
        label = "titre suivi" if entry.get("followed") else ticker  # journaux publics : pas les tickers des watchlists
        path = out_dir / f"{ticker}.json"
        try:
            is_us = entry["region"] == "US" and ticker in ciks
            fresh = from_sec(ciks[ticker]) if is_us else from_yahoo(ticker)
            if not fresh["years"]:
                continue
            existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            merged = merge(existing, fresh)
            try:
                merged["pe_history"] = fetch_pe_history(ticker, merged["years"], merged["currency"], shares_now.get(ticker))
            except Exception as e:  # cours indisponibles : on garde l'ancien PER historique s'il existe
                log.warning("%s : PER historique en erreur (%s)", label, e)
                merged["pe_history"] = (existing or {}).get("pe_history")
            path.write_text(json.dumps({"ticker": ticker, **merged}, separators=(",", ":")), encoding="utf-8")
            done += 1
        except Exception as e:
            log.warning("%s : historique en erreur (%s)", label, e)
    log.info("historique financier : %d actions mises à jour", done)


if __name__ == "__main__":
    main()
