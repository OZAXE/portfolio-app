"""
Plus-values réalisées et dividendes perçus, par année et par enveloppe, à partir de l'onglet
Opérations du Sheet modèle.

Plus-value d'une vente = montant net encaissé (frais et taxes déduits) - quantité vendue x PRU.
Le PRU suit la méthode du prix moyen pondéré (règle fiscale française), par compte et par titre,
frais d'achat inclus : une vente ne modifie pas le PRU des titres restants.

L'estimation d'impôt ne concerne que le CTO (prélèvement forfaitaire unique, 31,4 % depuis 2026) : le PEA
n'est pas imposé tant qu'on n'en retire rien. C'est l'impôt qui reste à payer (négatif : à récupérer),
dividende par dividende (voir dividend_tax) : les retenues de la colonne Taxes sont séparées en part
française et part étrangère, et la part étrangère ne s'impute que sur les 12,8 % d'impôt sur le revenu,
au taux de la convention fiscale. Elle reste indicative (moins-values reportables, option pour le barème).
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date

from . import sheets
from .sheets import UNFORMATTED, _open_sheet, _serial_to_iso, _worksheet
from .workbook import SHARE_TYPES, TRADE_TYPES

# PFU : 12,8 % d'impôt sur le revenu + prélèvements sociaux (17,2 %, puis 18,6 % depuis la hausse de CSG de 2026)
FLAT_TAX = 0.30
FLAT_TAX_2026 = 0.314


def flat_tax_rate(year: int) -> float:
    return FLAT_TAX_2026 if year >= 2026 else FLAT_TAX


INCOME_TAX = 0.128  # part impôt sur le revenu du PFU ; le reste, ce sont les prélèvements sociaux

# Crédit d'impôt des conventions fiscales avec la France (dividendes de portefeuille), par place de
# cotation : 15 % par défaut (États-Unis, Allemagne, Suisse...), 10 % Japon et Taïwan, 0 quand le pays
# ne prélève rien (France, Royaume-Uni, Hong Kong). Un ETF coté en Europe est presque toujours
# irlandais ou luxembourgeois : pas de retenue, donc pas de crédit.
TREATY_CREDIT = {".PA": 0.0, ".L": 0.0, ".HK": 0.0, ".T": 0.10, ".TW": 0.10}
DEFAULT_TREATY_CREDIT = 0.15
ROUNDING = 0.015  # les retenues sont arrondies au centime, parfois en deux parts


def treaty_credit(ticker: str, kind: str = "") -> float:
    dot = ticker.rfind(".")
    suffix = ticker[dot:] if dot > 0 else ""
    if kind == "ETF" and suffix:
        return 0.0
    return TREATY_CREDIT.get(suffix, DEFAULT_TREATY_CREDIT)


def dividend_tax(gross: float, withheld: float, credit_rate: float, year: int) -> dict:
    """Impôt français restant sur un dividende du CTO (négatif : acompte à récupérer).

    Un établissement français prélève à la source soit rien (courtier étranger), soit les prélèvements
    sociaux seuls (dispense d'acompte), soit l'acompte de 12,8 % en plus : on garde le plus grand de
    ces trois montants qui laisse au pays d'origine au moins la retenue de la convention. Le reste de la
    colonne Taxes est la retenue étrangère ; elle efface l'impôt sur le revenu jusqu'au taux de la
    convention (une retenue plus forte, 35 % en Suisse, se réclame au pays d'origine).
    Ex. Applied Materials chez Trade Republic, 2026 : brut 0,47, retenu 0,22 -> France 0,1476 (31,4 %),
    États-Unis 0,0724 ; dû 0,47 x 18,6 % = 0,0874 (impôt sur le revenu effacé) : 0,06 à récupérer."""
    rate = flat_tax_rate(year)
    social = rate - INCOME_TAX
    french = 0.0
    for candidate in (rate * gross, social * gross):
        if withheld - candidate >= credit_rate * gross - ROUNDING:
            french = candidate
            break
    foreign = max(withheld - french, 0.0)
    due = social * gross + max(INCOME_TAX * gross - min(foreign, credit_rate * gross), 0.0)
    return {"remaining": due - french, "french": french, "foreign": foreign}


@dataclass
class Operation:
    day: date
    account: str
    kind: str  # Achat / Vente / Dividende (Division / Actions gratuites dans Ledger.raw seulement)
    ticker: str
    quantity: float
    gross: float  # montant brut en euros
    fees: float
    taxes: float
    net: float  # achat : coût total ; vente et dividende : montant encaissé


@dataclass
class CashMovement:
    day: date
    account: str
    kind: str  # Versement / Retrait / Intérêts
    amount: float  # positif, en euros : montant net, qui arrive réellement sur le compte
    gross: float | None = None  # intérêts : montant brut, avant les prélèvements (colonne Taxes)
    taxes: float = 0.0


@dataclass
class YearSummary:
    year: int
    envelopes: dict = field(default_factory=dict)
    sales: list = field(default_factory=list)
    dividends: list = field(default_factory=list)


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def apply_splits(operations: list[Operation]) -> list[Operation]:
    """Opérations sans divisions ni actions gratuites, les quantités d'avant chaque division ramenées sur la
    base d'aujourd'hui. Les cours Yahoo sont corrigés des divisions : 10 Apple achetées en 2019 à 200 $,
    division 4 pour 1 en août 2020, deviennent 40 actions à 50 $, ce qui colle au cours Yahoo de 2019 (50 $)
    au lieu de compter 10 actions à 50 $ dans l'historique. Le coût et les montants ne changent pas, donc le
    PRU, les plus-values et le rendement sont les mêmes qu'en rejouant les opérations d'origine.

    Rapport d'une division = (quantité détenue + actions reçues) / quantité détenue, dans le compte concerné :
    Air Liquide 1 pour 10, 20 actions + 2 reçues -> x 1,1. Une division sans actions détenues est ignorée."""
    order = {"Achat": 0, "Dividende": 1, "Division": 2, "Actions gratuites": 2, "Vente": 3}
    ordered = sorted(operations, key=lambda o: (o.day, order.get(o.kind, 1)))
    adjusted = [replace(op) for op in ordered if op.kind not in SHARE_TYPES]
    positions: dict[tuple[str, str], list[Operation]] = defaultdict(list)  # (compte, titre) -> opérations vues
    held: dict[tuple[str, str], float] = defaultdict(float)
    copies = iter(adjusted)
    for op in ordered:
        key = (op.account, op.ticker)
        if op.kind in SHARE_TYPES:
            if held[key] > 1e-9 and held[key] + op.quantity > 1e-9:
                ratio = (held[key] + op.quantity) / held[key]
                for earlier in positions[key]:
                    earlier.quantity *= ratio
                held[key] += op.quantity
            continue
        copy = next(copies)
        positions[key].append(copy)
        if op.kind == "Achat":
            held[key] += op.quantity
        elif op.kind == "Vente":
            held[key] = max(held[key] - op.quantity, 0.0)
    return adjusted


@dataclass
class Ledger:
    operations: list[Operation]
    envelopes: dict[str, str]  # compte -> PEA / CTO (onglet Comptes)
    names: dict[str, str]  # titre -> nom (onglet Titres)
    currencies: dict[str, str]  # titre -> devise de cotation (onglet Titres)
    kinds: dict[str, str] = field(default_factory=dict)  # titre -> Action / ETF / Crypto (onglet Titres)
    # Versements, retraits et intérêts, à part : les calculs de rendement ne voient que les titres
    cash: list[CashMovement] = field(default_factory=list)
    # Opérations telles que saisies (quantités d'origine, divisions comprises) : operations les ramène sur
    # la base d'aujourd'hui (apply_splits). Seul le repérage des doublons à l'import compare aux originales
    raw: list[Operation] = field(default_factory=list)


# Rendement, plus-values, frais, dividendes et comparaison à un indice lisent tous les opérations :
# elles sont analysées une fois et partagées tant que le Sheet n'a pas été modifié par l'appli
_ledgers: dict[str, tuple[float, int, Ledger]] = {}
_ledgers_lock = threading.Lock()


def read_ledger(sheet_id: str) -> Ledger:
    with _ledgers_lock:
        cached = _ledgers.get(sheet_id)
    if cached and cached[1] == sheets.cache_generation() and time.time() - cached[0] < sheets.CACHE_SECONDS:
        return cached[2]
    generation = sheets.cache_generation()
    ledger = _parse_ledger(sheet_id)
    with _ledgers_lock:
        _ledgers[sheet_id] = (time.time(), generation, ledger)
    return ledger


def read_operations(sheet_id: str, raw: bool = False) -> tuple[list[Operation], dict[str, str], dict[str, str]]:
    """Opérations datées, enveloppe de chaque compte (onglet Comptes) et nom de chaque titre (onglet Titres).
    raw : quantités telles que saisies, divisions comprises (sinon ramenées sur la base d'aujourd'hui)."""
    ledger = read_ledger(sheet_id)
    return list(ledger.raw if raw else ledger.operations), dict(ledger.envelopes), dict(ledger.names)


def read_cash(sheet_id: str) -> list[CashMovement]:
    """Versements, retraits et intérêts de l'onglet Opérations."""
    return list(read_ledger(sheet_id).cash)


def _parse_ledger(sheet_id: str) -> Ledger:
    sheet = _open_sheet(sheet_id)
    operations, cash = [], []
    for row in _worksheet(sheet, "Opérations").get_values(value_render_option=UNFORMATTED)[1:]:
        row = (row + [""] * 12)[:12]
        iso = _serial_to_iso(row[0])
        if iso and row[2] in ("Versement", "Retrait", "Intérêts"):
            amount = next((v for v in (row[11], row[8]) if isinstance(v, (int, float))), None)
            if amount is None:
                amount = _num(row[4] or 1) * _num(row[5])
            if amount:
                gross = row[8] if isinstance(row[8], (int, float)) else _num(row[4] or 1) * _num(row[5])
                cash.append(CashMovement(date.fromisoformat(iso), str(row[1]), row[2], abs(float(amount)),
                                         abs(float(gross or amount)), _num(row[10])))
            continue
        if not iso or row[2] not in (*TRADE_TYPES, *SHARE_TYPES) or not isinstance(row[4], (int, float)):
            continue
        if row[2] in SHARE_TYPES:
            operations.append(Operation(date.fromisoformat(iso), str(row[1]), row[2], str(row[3]).strip().upper(),
                                        float(row[4]), 0.0, 0.0, 0.0, 0.0))
            continue
        gross = row[8] if isinstance(row[8], (int, float)) else row[4] * _num(row[5]) * (_num(row[7]) or 1)
        fees, taxes = _num(row[9]), _num(row[10])
        net = row[11] if isinstance(row[11], (int, float)) else (gross + fees + taxes if row[2] == "Achat" else gross - fees - taxes)
        operations.append(Operation(date.fromisoformat(iso), str(row[1]), row[2], str(row[3]).strip().upper(),
                                    float(row[4]), gross, fees, taxes, net))
    comptes = _worksheet(sheet, "Comptes").get_values(value_render_option=UNFORMATTED)[1:]
    titres = _worksheet(sheet, "Titres").get_values(value_render_option=UNFORMATTED)[1:]
    envelopes = {str(r[0]): str(r[1]) for r in comptes if len(r) > 1 and r[0]}
    names = {str(r[0]).strip().upper(): str(r[2]) for r in titres if len(r) > 2 and r[0]}
    currencies = {str(r[0]).strip().upper(): str(r[5] or "EUR").strip() for r in titres if len(r) > 5 and r[0]}
    kinds = {str(r[0]).strip().upper(): str(r[6]).strip() for r in titres if len(r) > 6 and r[0]}
    return Ledger(apply_splits(operations), envelopes, names, currencies, kinds, cash, raw=operations)


def compute_realized(operations: list[Operation], envelopes: dict[str, str], names: dict[str, str] | None = None,
                     kinds: dict[str, str] | None = None, cash: list[CashMovement] | None = None) -> dict:
    names, kinds = names or {}, kinds or {}
    positions: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])  # (compte, titre) -> [quantité, coût total]
    years: dict[int, YearSummary] = {}

    def envelope_bucket(year: int, envelope: str) -> dict:
        summary = years.setdefault(year, YearSummary(year))
        return summary.envelopes.setdefault(envelope, {
            "realized_gain": 0.0, "sales": 0, "sale_proceeds": 0.0,
            "dividends_gross": 0.0, "dividends_taxes": 0.0, "dividends_net": 0.0,
            "dividends_tax_remaining": 0.0, "foreign_withheld": 0.0,
            "interest_gross": 0.0, "interest_taxes": 0.0,
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
            tax = dividend_tax(op.gross, op.taxes + op.fees, treaty_credit(op.ticker, kinds.get(op.ticker, "")), op.day.year)
            bucket["dividends_tax_remaining"] += tax["remaining"]
            bucket["foreign_withheld"] += tax["foreign"]
            years[op.day.year].dividends.append({
                "date": op.day.isoformat(), "account": op.account, "envelope": envelope, "ticker": op.ticker,
                "name": names.get(op.ticker, op.ticker), "gross": round(op.gross, 2),
                "taxes": round(op.taxes + op.fees, 2), "net": round(op.net, 2),
            })

    # Intérêts des espèces (Trade Republic) : imposés au prélèvement forfaitaire comme les plus-values, sans
    # convention fiscale ni abattement. Sur le PEA, rien n'est imposé tant qu'on ne retire rien.
    for m in cash or []:
        if m.kind != "Intérêts" or envelopes.get(m.account) == "PEA":
            continue
        bucket = envelope_bucket(m.day.year, "CTO")
        bucket["interest_gross"] += m.gross if m.gross is not None else m.amount
        bucket["interest_taxes"] += m.taxes

    result = []
    for year in sorted(years, reverse=True):
        summary = years[year]
        envelopes_out = {}
        for envelope, b in summary.envelopes.items():
            internal = ("dividends_tax_remaining", "foreign_withheld")
            rounded = {k: round(v, 2) if isinstance(v, float) else v for k, v in b.items() if k not in internal}
            if envelope == "CTO":
                rate = flat_tax_rate(year)
                # Négatif : l'acompte de 12,8 % prélevé sur des dividendes étrangers dépasse l'impôt dû
                rounded["flat_tax_rate"] = rate
                # Intérêts : dû = brut x flat tax, moins ce que le courtier a déjà prélevé (Trade Republic : parfois
                # rien, tout reste à payer à la déclaration, case 2TR). Ex. 100 € bruts en 2026 sans retenue : 31,40 €
                interest_remaining = b["interest_gross"] * rate - b["interest_taxes"]
                rounded["interest_tax_remaining"] = round(interest_remaining, 2)
                rounded["estimated_tax"] = round(max(b["realized_gain"], 0.0) * rate + b["dividends_tax_remaining"]
                                                 + interest_remaining, 2)
                rounded["withheld_tax"] = round(b["dividends_taxes"], 2)
                rounded["foreign_withheld"] = round(b["foreign_withheld"], 2)
            envelopes_out[envelope] = rounded
        result.append({"year": year, "envelopes": envelopes_out,
                       "sales": sorted(summary.sales, key=lambda s: s["date"], reverse=True),
                       "dividends": sorted(summary.dividends, key=lambda d: d["date"], reverse=True)})
    return {"years": result, "flat_tax_rate": flat_tax_rate(date.today().year)}


def realized_summary(sheet_id: str) -> dict:
    ledger = read_ledger(sheet_id)
    return compute_realized(ledger.operations, ledger.envelopes, ledger.names, ledger.kinds, ledger.cash)
