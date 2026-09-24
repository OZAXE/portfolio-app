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


# Défauts du DCF, réutilisés dans l'alerte sur les écarts extrêmes
DEFAULT_GROWTH_RATE = 0.05
DEFAULT_DISCOUNT_RATE = 0.09

# Au-delà de cet écart (en %), on signale que les hypothèses par défaut collent sans doute mal
EXTREME_MARGIN_THRESHOLD_PCT = 75


def compute_dcf(
    fcf_history: list[float],
    growth_rate: float = DEFAULT_GROWTH_RATE,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    terminal_growth: float = 0.02,
    projection_years: int = 10,
) -> float | None:
    """
    DCF à deux phases : croissance explicite pendant `projection_years`,
    puis valeur terminale à croissance stable (formule de Gordon-Shapiro).

    Renvoie la valeur d'entreprise (flux actualisés), pas une valeur par
    action : le passage aux capitaux propres se fait dans
    `equity_value_per_share`, pour tenir compte de la dette nette.

    growth_rate / discount_rate / terminal_growth sont les hypothèses clés :
    c'est là que se joue la subjectivité de toute valorisation DCF, donc
    à ajuster selon ta propre lecture de l'entreprise plutôt qu'à prendre
    tel quel.
    """
    if not fcf_history:
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

    return pv_sum + pv_terminal


def equity_value_per_share(
    enterprise_value: float | None,
    total_debt: float | None,
    total_cash: float | None,
    shares_outstanding: float | None,
) -> float | None:
    """
    Valeur des capitaux propres par action = (valeur d'entreprise - dette nette) / actions,
    avec dette nette = dette totale - trésorerie. Une dette ou une trésorerie
    inconnue est comptée à 0. Renvoie None si les capitaux propres ressortent
    négatifs (la dette dépasse la valeur des flux futurs).
    """
    if enterprise_value is None or not shares_outstanding:
        return None

    net_debt = (total_debt or 0) - (total_cash or 0)
    equity_value = enterprise_value - net_debt
    if equity_value <= 0:
        return None
    return equity_value / shares_outstanding


def compute_quality_score(cf: CompanyFinancials) -> tuple[float | None, list[str]]:
    """
    Score composite sur 20, construit à partir de 4 piliers à 5 points chacun :
    rentabilité, marges, endettement, valorisation relative.
    C'est une base de départ simple, à affiner avec le temps (secteur par
    secteur par exemple, un ROE de 15% n'a pas le même sens en banque
    qu'en tech).
    """
    if cf.quote_type == "ETF":
        return None, ["Score qualité non pertinent pour un ETF, pas de fondamentaux d'entreprise"]

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
    enterprise_value = compute_dcf(cf.fcf_history)
    intrinsic_value = equity_value_per_share(
        enterprise_value, cf.total_debt, cf.total_cash, cf.shares_outstanding
    )
    quality_score, notes = compute_quality_score(cf)

    margin_of_safety = None
    if intrinsic_value is not None and cf.current_price:
        margin_of_safety = ((intrinsic_value - cf.current_price) / intrinsic_value) * 100
        if abs(margin_of_safety) > EXTREME_MARGIN_THRESHOLD_PCT:
            notes.append(
                f"Écart important : les hypothèses DCF par défaut (croissance "
                f"{DEFAULT_GROWTH_RATE:.0%}, actualisation {DEFAULT_DISCOUNT_RATE:.0%}) sont "
                f"probablement mal adaptées à cette entreprise, à ajuster manuellement"
            )

    return ValuationResult(
        ticker=cf.ticker,
        intrinsic_value_per_share=round(intrinsic_value, 2) if intrinsic_value else None,
        current_price=cf.current_price,
        margin_of_safety_pct=round(margin_of_safety, 1) if margin_of_safety is not None else None,
        quality_score=quality_score,
        notes=notes,
    )
