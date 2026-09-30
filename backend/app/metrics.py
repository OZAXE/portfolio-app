"""
Ratios de qualité complémentaires (octobre 2026, demande d'Enzo) : ROIC, rendement du cash-flow libre, dette nette
sur EBITDA, couverture des intérêts, croissance du chiffre d'affaires et du bénéfice par action.

Deux sources, comme pour le prix juste :
- les comptes annuels archivés chaque semaine par screener/financials.py (15 à 19 ans à la SEC pour les actions
  américaines, 4 exercices Yahoo archivés au fil des ans ailleurs) : ROIC, croissance, couverture des intérêts,
  qui ont besoin de plusieurs lignes des comptes ou de plusieurs années ;
- les données Yahoo du jour (CompanyFinancials) : rendement du cash-flow libre (dépend du cours) et dette nette sur
  EBITDA (derniers chiffres publiés).

Données Yahoo non fiables : chaque ratio est borné, un chiffre hors bornes est remplacé par « N/A » plutôt que
d'afficher un ROIC de 900 %. Banques et assurances : ROIC, cash-flow libre et dette n'ont pas de sens (l'argent est
leur matière première), ratios non calculés.
"""

from statistics import median

# Impôt retenu quand les comptes ne donnent pas le taux effectif (proche du taux moyen des grands pays)
DEFAULT_TAX_RATE = 0.25
MAX_TAX_RATE = 0.5
GROWTH_YEARS = 5  # croissance mesurée sur 5 exercices au plus...
MIN_GROWTH_YEARS = 3  # ... et 3 au moins : sur 1 ou 2 ans, une seule bonne année fait la moyenne
ROIC_MEDIAN_YEARS = 5
BOUNDS = {
    "roic": (-1.0, 2.0),
    "fcf_yield": (-0.5, 0.5),
    "net_debt_ebitda": (-20.0, 50.0),
    "interest_coverage": (0.0, 1000.0),
    "growth": (-0.5, 1.0),
}


def bounded(value: float | None, kind: str) -> float | None:
    """None si la valeur sort de bornes plausibles (donnée Yahoo aberrante)."""
    low, high = BOUNDS[kind]
    return value if value is not None and low <= value <= high else None


def tax_rate(year: dict) -> float:
    """Taux effectif de l'exercice (impôt / résultat avant impôt), sinon 25 %. Borné à 0-50 % : une année de
    crédit d'impôt exceptionnel ne doit pas gonfler le ROIC."""
    tax, pretax = year.get("income_tax"), year.get("pretax_income")
    if tax is None or not pretax or pretax <= 0:
        return DEFAULT_TAX_RATE
    return min(max(tax / pretax, 0.0), MAX_TAX_RATE)


def roic(year: dict) -> float | None:
    """Rentabilité du capital investi : résultat opérationnel après impôt / (fonds propres + dettes - trésorerie).
    Contrairement au ROE, une entreprise ne l'améliore pas en s'endettant. Ex. résultat opérationnel 10 Md, impôt
    21 %, fonds propres 40 Md, dettes 20 Md, trésorerie 10 Md : 7,9 / 50 = 15,8 %. Une année sans ligne de dette
    compte une dette nulle (Yahoo n'affiche pas la ligne d'une entreprise sans dette)."""
    operating, equity, cash = year.get("operating_income"), year.get("equity"), year.get("cash")
    if operating is None or equity is None or cash is None:
        return None
    invested = equity + (year.get("long_term_debt") or 0.0) + (year.get("short_term_debt") or 0.0) - cash
    if invested <= 0:
        return None  # plus de trésorerie que de capitaux investis : ratio sans signification
    return bounded(operating * (1 - tax_rate(year)) / invested, "roic")


def cagr(series: dict[int, float], years: int = GROWTH_YEARS, min_years: int = MIN_GROWTH_YEARS) -> tuple[float, int] | None:
    """Croissance annuelle moyenne entre le dernier exercice et celui d'il y a `years` ans (ou le plus ancien
    disponible, au moins `min_years` ans avant). (croissance, nombre d'années) ; None si une des deux valeurs est
    négative ou nulle (une perte ne se compare pas en %). Ex. 100 -> 161 en 5 ans : +10 %/an."""
    values = {y: v for y, v in series.items() if v is not None}
    if not values:
        return None
    latest = max(values)
    start = next((latest - k for k in range(years, min_years - 1, -1) if latest - k in values), None)
    if start is None or values[start] <= 0 or values[latest] <= 0:
        return None
    span = latest - start
    growth = bounded((values[latest] / values[start]) ** (1 / span) - 1, "growth")
    return (growth, span) if growth is not None else None


def interest_coverage(year: dict) -> float | None:
    """Combien de fois le résultat opérationnel couvre les intérêts de la dette : sous 3, un creux d'activité
    peut mettre l'entreprise en difficulté. None sans intérêts publiés (pas de dette, ou ligne absente)."""
    operating, interest = year.get("operating_income"), year.get("interest_expense")
    if operating is None or not interest:
        return None
    return bounded(operating / abs(interest), "interest_coverage")


def archive_metrics(years: list[dict] | None) -> dict:
    """Ratios tirés de l'historique archivé (liste d'exercices {year, revenue, operating_income...})."""
    years = sorted(years or [], key=lambda y: y["year"])
    result = {"roic": None, "roic_median": None, "roic_years": None, "interest_coverage": None,
              "revenue_cagr": None, "revenue_years": None}
    roics = [(y["year"], r) for y in years if (r := roic(y)) is not None]
    if roics:
        result["roic"] = round(roics[-1][1], 4)
        recent = [r for year, r in roics if year > roics[-1][0] - ROIC_MEDIAN_YEARS]
        if len(recent) >= MIN_GROWTH_YEARS:
            result["roic_median"], result["roic_years"] = round(median(recent), 4), len(recent)
    coverage = next((c for y in reversed(years) if (c := interest_coverage(y)) is not None), None)
    result["interest_coverage"] = round(coverage, 1) if coverage is not None else None
    revenue = cagr({y["year"]: y.get("revenue") for y in years})
    if revenue:
        result["revenue_cagr"], result["revenue_years"] = round(revenue[0], 4), revenue[1]
    return result


def fcf_yield(fcf_per_share: float | None, price: float | None) -> float | None:
    """Cash-flow libre par action / cours : ce que rapporterait l'action si toute la trésorerie produite était
    distribuée. 5 % = l'entreprise « rembourse » son prix en 20 ans au rythme actuel. Recalculé chaque nuit avec
    le cours (refresh_with_price) et dans l'appli."""
    if fcf_per_share is None or not price or price <= 0:
        return None
    return bounded(fcf_per_share / price, "fcf_yield")


def net_debt_to_ebitda(total_debt: float | None, total_cash: float | None, ebitda: float | None) -> float | None:
    """Années de résultat brut d'exploitation qu'il faudrait pour rembourser la dette nette : sous 1,5 peu endettée,
    au-delà de 3 très endettée. Négatif : plus de trésorerie que de dettes. None si l'EBITDA est négatif."""
    if total_debt is None or total_cash is None or not ebitda or ebitda <= 0:
        return None
    return bounded((total_debt - total_cash) / ebitda, "net_debt_ebitda")
