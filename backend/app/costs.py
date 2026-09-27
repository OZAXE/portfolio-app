"""
Plafond du PEA et frais payés, à partir de l'onglet Opérations.

Plafond PEA : 150 000 € de versements (argent déposé), pas de valeur. Les dépôts d'espèces ne
figurent pas dans l'onglet Opérations : ils sont estimés par ce qui est sorti de la poche de
l'investisseur, soit les achats moins l'argent déjà présent dans le PEA (ventes et dividendes,
réinvestis sans nouveau versement). Le cumul le plus haut atteint est retenu, car une vente
ne rend pas de place sous le plafond. Il n'y a qu'un PEA par personne : toutes les lignes
d'enveloppe PEA comptent ensemble. Cinq ans après le premier versement, les gains retirés ne
sont plus soumis qu'aux prélèvements sociaux.

Frais : courtage et taxes (TTF) des achats et ventes, retenues sur dividendes, par année ;
frais courants des ETF (TER), prélevés dans la valeur de l'ETF et donc invisibles sur les relevés,
estimés sur la valeur actuelle.
"""

from collections import defaultdict
from datetime import date

from .realized import Operation

PEA_CEILING = 150_000.0


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 février
        return day.replace(year=day.year + years, day=28)


def pea_ceiling(operations: list[Operation], envelopes: dict[str, str], today: date) -> dict | None:
    pea_ops = sorted((op for op in operations if envelopes.get(op.account) == "PEA"), key=lambda o: o.day)
    if not pea_ops:
        return None
    running = peak = 0.0
    for op in pea_ops:
        running += op.net if op.kind == "Achat" else -op.net
        peak = max(peak, running)
    first = pea_ops[0].day
    five_years = _add_years(first, 5)
    return {
        "deposits": round(peak, 2),
        "ceiling": PEA_CEILING,
        "remaining": round(max(PEA_CEILING - peak, 0.0), 2),
        "used": round(min(peak / PEA_CEILING, 1.0), 4),
        "first_operation": first.isoformat(),
        "five_years": five_years.isoformat(),
        "five_years_reached": today >= five_years,
    }


def fees_by_year(operations: list[Operation], envelopes: dict[str, str]) -> list[dict]:
    years = defaultdict(lambda: {"brokerage": 0.0, "transaction_tax": 0.0, "dividend_tax": 0.0, "invested": 0.0})
    for op in operations:
        y = years[op.day.year]
        if op.kind == "Dividende":
            y["dividend_tax"] += op.taxes + op.fees
        else:
            y["brokerage"] += op.fees
            y["transaction_tax"] += op.taxes
            if op.kind == "Achat":
                y["invested"] += op.gross
    result = []
    for year in sorted(years, reverse=True):
        y = {k: round(v, 2) for k, v in years[year].items()}
        trading = y["brokerage"] + y["transaction_tax"]
        result.append({"year": year, **y, "total": round(trading + y["dividend_tax"], 2),
                       # Part des achats et ventes partie en frais : le coût réel de chaque euro investi
                       "trading_cost_pct": round(trading / y["invested"], 5) if y["invested"] else None})
    return result


def etf_costs(holdings: list[dict], ter: dict[str, float | None]) -> dict:
    """holdings : ETF détenus {ticker, name, value} ; ter : frais courants en % (0,38 = 0,38 %)."""
    lines, unknown = [], []
    for h in holdings:
        rate = ter.get(h["ticker"])
        if rate is None:
            unknown.append(h["name"] or h["ticker"])
            continue
        lines.append({**h, "ter": rate, "annual": round((h["value"] or 0) * rate / 100, 2)})
    lines.sort(key=lambda l: -l["annual"])
    covered = sum(l["value"] or 0 for l in lines)
    return {"lines": lines, "unknown": unknown, "annual": round(sum(l["annual"] for l in lines), 2),
            "weighted_ter": round(sum(l["annual"] for l in lines) / covered * 100, 3) if covered else None}
