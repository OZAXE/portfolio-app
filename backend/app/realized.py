"""
Plus-values réalisées et dividendes perçus, par année et par enveloppe, à partir de l'onglet
Opérations du Sheet modèle.

Plus-value d'une vente = montant net encaissé (frais et taxes déduits) - quantité vendue x PRU.
Le PRU suit la méthode du prix moyen pondéré (règle fiscale française), par compte et par titre,
frais d'achat inclus : une vente ne modifie pas le PRU des titres restants.

L'estimation d'impôt ne concerne que le CTO (prélèvement forfaitaire unique de 30 %) : le PEA
n'est pas imposé tant qu'on n'en retire rien. Elle reste indicative (moins-values reportables,
option pour le barème, prélèvements déjà faits à la source...).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .sheets import UNFORMATTED, _open_sheet, _serial_to_iso, _worksheet

FLAT_TAX = 0.30  # PFU : 12,8 % d'impôt sur le revenu + 17,2 % de prélèvements sociaux


@dataclass
class Operation:
    day: date
    account: str
    kind: str  # Achat / Vente / Dividende
    ticker: str
    quantity: float
    gross: float  # montant brut en euros
    fees: float
    taxes: float
    net: float  # achat : coût total ; vente et dividende : montant encaissé


@dataclass
class YearSummary:
    year: int
    envelopes: dict = field(default_factory=dict)
    sales: list = field(default_factory=list)
    dividends: list = field(default_factory=list)


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def read_operations(sheet_id: str) -> tuple[list[Operation], dict[str, str], dict[str, str]]:
    """Opérations datées, enveloppe de chaque compte (onglet Comptes) et nom de chaque titre (onglet Titres)."""
    sheet = _open_sheet(sheet_id)
    operations = []
    for row in _worksheet(sheet, "Opérations").get_values(value_render_option=UNFORMATTED)[1:]:
        row = (row + [""] * 12)[:12]
        iso = _serial_to_iso(row[0])
        if not iso or row[2] not in ("Achat", "Vente", "Dividende") or not isinstance(row[4], (int, float)):
            continue
        gross = row[8] if isinstance(row[8], (int, float)) else row[4] * _num(row[5]) * (_num(row[7]) or 1)
        fees, taxes = _num(row[9]), _num(row[10])
        net = row[11] if isinstance(row[11], (int, float)) else (gross + fees + taxes if row[2] == "Achat" else gross - fees - taxes)
        operations.append(Operation(date.fromisoformat(iso), str(row[1]), row[2], str(row[3]).strip().upper(),
                                    float(row[4]), gross, fees, taxes, net))
    envelopes = {str(r[0]): str(r[1]) for r in _worksheet(sheet, "Comptes").get_values()[1:] if len(r) > 1 and r[0]}
    names = {str(r[0]).upper(): str(r[2]) for r in _worksheet(sheet, "Titres").get_values()[1:] if len(r) > 2 and r[0]}
    return operations, envelopes, names


def compute_realized(operations: list[Operation], envelopes: dict[str, str], names: dict[str, str] | None = None) -> dict:
    names = names or {}
    positions: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])  # (compte, titre) -> [quantité, coût total]
    years: dict[int, YearSummary] = {}

    def envelope_bucket(year: int, envelope: str) -> dict:
        summary = years.setdefault(year, YearSummary(year))
        return summary.envelopes.setdefault(envelope, {
            "realized_gain": 0.0, "sales": 0, "sale_proceeds": 0.0,
            "dividends_gross": 0.0, "dividends_taxes": 0.0, "dividends_net": 0.0,
        })

    # Ordre chronologique ; le même jour, les achats avant les ventes
    order = {"Achat": 0, "Dividende": 1, "Vente": 2}
    for op in sorted(operations, key=lambda o: (o.day, order[o.kind])):
        envelope = envelopes.get(op.account, "Autre")
        position = positions[(op.account, op.ticker)]
        if op.kind == "Achat":
            position[0] += op.quantity
            position[1] += op.net
        elif op.kind == "Vente":
            unit_cost = position[1] / position[0] if position[0] > 0 else 0.0
            quantity = min(op.quantity, position[0]) if position[0] > 0 else op.quantity
            cost = quantity * unit_cost
            gain = op.net - cost
            position[0] -= quantity
            position[1] -= cost
            bucket = envelope_bucket(op.day.year, envelope)
            bucket["realized_gain"] += gain
            bucket["sales"] += 1
            bucket["sale_proceeds"] += op.net
            years[op.day.year].sales.append({
                "date": op.day.isoformat(), "account": op.account, "envelope": envelope, "ticker": op.ticker,
                "name": names.get(op.ticker, op.ticker), "quantity": op.quantity, "proceeds": round(op.net, 2),
                "unit_cost": round(unit_cost, 4), "cost": round(cost, 2), "gain": round(gain, 2),
            })
        else:
            bucket = envelope_bucket(op.day.year, envelope)
            bucket["dividends_gross"] += op.gross
            bucket["dividends_taxes"] += op.taxes + op.fees
            bucket["dividends_net"] += op.net
            years[op.day.year].dividends.append({
                "date": op.day.isoformat(), "account": op.account, "envelope": envelope, "ticker": op.ticker,
                "name": names.get(op.ticker, op.ticker), "gross": round(op.gross, 2),
                "taxes": round(op.taxes + op.fees, 2), "net": round(op.net, 2),
            })

    result = []
    for year in sorted(years, reverse=True):
        summary = years[year]
        envelopes_out = {}
        for envelope, b in summary.envelopes.items():
            rounded = {k: round(v, 2) if isinstance(v, float) else v for k, v in b.items()}
            if envelope == "CTO":
                # Base indicative : plus-values nettes de l'année (si positives) + dividendes bruts
                base = max(b["realized_gain"], 0.0) + b["dividends_gross"]
                rounded["estimated_tax"] = round(base * FLAT_TAX, 2)
            envelopes_out[envelope] = rounded
        result.append({"year": year, "envelopes": envelopes_out,
                       "sales": sorted(summary.sales, key=lambda s: s["date"], reverse=True),
                       "dividends": sorted(summary.dividends, key=lambda d: d["date"], reverse=True)})
    return {"years": result, "flat_tax_rate": FLAT_TAX}


def realized_summary(sheet_id: str) -> dict:
    operations, envelopes, names = read_operations(sheet_id)
    return compute_realized(operations, envelopes, names)
