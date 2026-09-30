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
from .workbook import TITRES_HEADERS

PEA_CEILING = 150_000.0


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 février
        return day.replace(year=day.year + years, day=28)


def pea_ceiling(operations: list[Operation], envelopes: dict[str, str], today: date,
                deposits: float | None = None) -> dict | None:
    """deposits : versements réels sur le PEA quand ils sont saisis (cash.pea_deposits). Sinon, estimation :
    le plus haut montant net investi (achats - ventes - dividendes), le minimum qu'il a fallu verser."""
    pea_ops = sorted((op for op in operations if envelopes.get(op.account) == "PEA"), key=lambda o: o.day)
    if not pea_ops:
        return None
    running = peak = 0.0
    for op in pea_ops:
        running += op.net if op.kind == "Achat" else -op.net
        peak = max(peak, running)
    estimated = deposits is None
    peak = peak if estimated else deposits
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
        "estimated": estimated,
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


FEE_COLUMN = TITRES_HEADERS.index("Frais courants %")  # colonne I


def manual_fees(titres: list[list]) -> dict[str, float]:
    """Frais courants saisis à la main dans l'onglet Titres, en % (0,15 = 0,15 %).
    Une cellule au format pourcentage (0,15 % -> 0,0015) est reconnue : aucun ETF ne coûte moins de 0,02 %."""
    fees = {}
    for row in titres[1:]:
        if len(row) <= FEE_COLUMN or not row[0]:
            continue
        value = row[FEE_COLUMN]
        if isinstance(value, str):
            try:
                value = float(value.replace("%", "").replace(",", ".").strip())
            except ValueError:
                continue
        if isinstance(value, (int, float)) and value > 0:
            fees[str(row[0]).strip().upper()] = round(value * 100 if value < 0.02 else value, 4)
    return fees


def ensure_fee_column(worksheet) -> None:
    """Ajoute l'en-tête « Frais courants % » aux onglets Titres créés avant cette colonne."""
    header = worksheet.row_values(1)
    if len(header) > FEE_COLUMN and header[FEE_COLUMN]:
        return
    if worksheet.col_count <= FEE_COLUMN:
        worksheet.add_cols(FEE_COLUMN + 1 - worksheet.col_count)
    worksheet.update_cell(1, FEE_COLUMN + 1, TITRES_HEADERS[FEE_COLUMN])


def etf_costs(holdings: list[dict], ter: dict[str, float | None]) -> dict:
    """holdings : ETF détenus {ticker, name, value} ; ter : frais courants en % (0,38 = 0,38 %),
    saisis dans l'onglet Titres ou, à défaut, récupérés auprès de Yahoo."""
    lines, unknown = [], []
    for h in holdings:
        rate = ter.get(h["ticker"])
        if rate is None:
            unknown.append(h["name"] or h["ticker"])
            continue
        lines.append({**h, "ter": rate, "annual": round((h["value"] or 0) * rate / 100, 2), "manual": h.get("manual", False)})
    lines.sort(key=lambda l: -l["annual"])
    covered = sum(l["value"] or 0 for l in lines)
    return {"lines": lines, "unknown": unknown, "annual": round(sum(l["annual"] for l in lines), 2),
            "weighted_ter": round(sum(l["annual"] for l in lines) / covered * 100, 3) if covered else None}
