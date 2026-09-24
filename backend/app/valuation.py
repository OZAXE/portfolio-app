"""
Logique de valorisation, inspirée de ce que font Baggr / Mungr :
- un DCF simplifié pour estimer une valeur intrinsèque
- une marge de sécurité (écart entre valeur intrinsèque et prix actuel)
- un score de qualité composite sur 20

Tout est volontairement transparent et modifiable : contrairement à un
outil fermé, tu peux ajuster chaque hypothèse (taux de croissance, taux
d'actualisation) et voir l'impact direct sur le résultat.
"""

from dataclasses import dataclass
from .data import CompanyFinancials


@dataclass
class ValuationResult:
    ticker: str
    intrinsic_value_per_share: float | None
    current_price: float | None
    margin_of_safety_pct: float | None  # positif = sous-évaluée, négatif = surévaluée
    quality_score: float | None  # sur 20
    notes: list[str]


def compute_dcf(
    fcf_history: list[float],
    shares_outstanding: float | None,
    growth_rate: float = 0.05,
    discount_rate: float = 0.09,
    terminal_growth: float = 0.02,
    projection_years: int = 10,
) -> float | None:
    """
    DCF à deux phases : croissance explicite pendant `projection_years`,
    puis valeur terminale à croissance stable (formule de Gordon-Shapiro).

    growth_rate / discount_rate / terminal_growth sont les hypothèses clés :
    c'est là que se joue la subjectivité de toute valorisation DCF, donc
    à ajuster selon ta propre lecture de l'entreprise plutôt qu'à prendre
    tel quel.
    """
    if not fcf_history or not shares_outstanding:
        return None

    base_fcf = fcf_history[-1]  # dernier FCF connu
    if base_fcf is None or base_fcf <= 0:
        return None

    pv_sum = 0.0
    fcf = base_fcf
    for year in range(1, projection_years + 1):
        fcf = fcf * (1 + growth_rate)
        pv_sum += fcf / ((1 + discount_rate) ** year)

    terminal_value = (fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** projection_years)

    enterprise_value = pv_sum + pv_terminal
    return enterprise_value / shares_outstanding


def compute_quality_score(cf: CompanyFinancials) -> tuple[float | None, list[str]]:
    """
    Score composite sur 20, construit à partir de 4 piliers à 5 points chacun :
    rentabilité, marges, endettement, valorisation relative.
    C'est une base de départ simple, à affiner avec le temps (secteur par
    secteur par exemple, un ROE de 15% n'a pas le même sens en banque
    qu'en tech).
    """
    notes = []
    points = 0.0
    pillars_scored = 0

    if cf.return_on_equity is not None:
        pillars_scored += 1
        if cf.return_on_equity > 0.20:
            points += 5
        elif cf.return_on_equity > 0.12:
            points += 3.5
        elif cf.return_on_equity > 0.05:
            points += 2
        else:
            notes.append("ROE faible : rentabilité des capitaux propres à surveiller")

    if cf.operating_margin is not None:
        pillars_scored += 1
        if cf.operating_margin > 0.20:
            points += 5
        elif cf.operating_margin > 0.10:
            points += 3.5
        elif cf.operating_margin > 0.03:
            points += 2
        else:
            notes.append("Marge opérationnelle faible")

    if cf.debt_to_equity is not None:
        pillars_scored += 1
        if cf.debt_to_equity < 50:
            points += 5
        elif cf.debt_to_equity < 100:
            points += 3.5
        elif cf.debt_to_equity < 200:
            points += 2
        else:
            notes.append("Endettement élevé par rapport aux capitaux propres")

    if cf.trailing_pe is not None and cf.trailing_pe > 0:
        pillars_scored += 1
        if cf.trailing_pe < 15:
            points += 5
        elif cf.trailing_pe < 25:
            points += 3.5
        elif cf.trailing_pe < 40:
            points += 2
        else:
            notes.append("Valorisation élevée sur le PER (à mettre en regard de la croissance attendue)")

    if pillars_scored == 0:
        return None, ["Données insuffisantes pour calculer un score"]

    # Ramené sur 20 même si tous les piliers ne sont pas disponibles
    score_on_20 = (points / (pillars_scored * 5)) * 20
    return round(score_on_20, 1), notes


def evaluate_company(cf: CompanyFinancials) -> ValuationResult:
    intrinsic_value = compute_dcf(cf.fcf_history, cf.shares_outstanding)
    quality_score, notes = compute_quality_score(cf)

    margin_of_safety = None
    if intrinsic_value is not None and cf.current_price:
        margin_of_safety = ((intrinsic_value - cf.current_price) / intrinsic_value) * 100

    return ValuationResult(
        ticker=cf.ticker,
        intrinsic_value_per_share=round(intrinsic_value, 2) if intrinsic_value else None,
        current_price=cf.current_price,
        margin_of_safety_pct=round(margin_of_safety, 1) if margin_of_safety is not None else None,
        quality_score=quality_score,
        notes=notes,
    )
