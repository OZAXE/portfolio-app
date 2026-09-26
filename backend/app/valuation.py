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
from .data import STATEMENTS_SOURCE, CompanyFinancials


@dataclass
class ValuationResult:
    ticker: str
    intrinsic_value_per_share: float | None
    current_price: float | None
    margin_of_safety_pct: float | None  # positif = sous-évaluée, négatif = surévaluée
    quality_score: float | None  # sur 20
    notes: list[str]
    # False quand l'écart avec le prix est tel que le DCF simple ne capte manifestement pas l'entreprise
    dcf_reliable: bool = False
    growth_rate_used: float | None = None
    discount_rate_used: float | None = None
    # Ingrédients du DCF, pour que l'appli le recalcule avec les hypothèses de l'utilisateur
    base_fcf: float | None = None
    net_debt: float | None = None
    shares_used: float | None = None


# Hypothèses du DCF. La croissance et l'actualisation sont ajustées par entreprise
# (historique du FCF, bêta) mais bornées pour éviter les extrapolations délirantes.
DEFAULT_GROWTH_RATE = 0.05
MIN_GROWTH_RATE = 0.0
MAX_GROWTH_RATE = 0.12
TERMINAL_GROWTH = 0.02

DEFAULT_DISCOUNT_RATE = 0.09
RISK_FREE_RATE = 0.04
EQUITY_RISK_PREMIUM = 0.05
MIN_DISCOUNT_RATE = 0.07
MAX_DISCOUNT_RATE = 0.11

# Industries Yahoo pour lesquelles un DCF sur cash-flow libre n'a pas de sens
# (Visa / Mastercard sont en "Credit Services" et gardent leur DCF)
FINANCIAL_INDUSTRIES_WITHOUT_DCF = (
    "bank", "insurance", "capital markets", "asset management", "mortgage", "financial conglomerates",
)

# Nombre d'exercices moyennés pour le FCF de départ (lisse une année de gros investissements)
NORMALIZATION_YEARS = 3

# Hors de cette fourchette (valeur intrinsèque / prix), le DCF est jugé non fiable
RELIABLE_RATIO_MIN = 0.4
RELIABLE_RATIO_MAX = 2.5


def normalized_fcf(fcf_history: list[float]) -> float | None:
    """Moyenne des derniers exercices connus : un FCF ponctuellement écrasé par
    un pic d'investissement ne doit pas servir seul de base à 10 ans de projection."""
    recent = [x for x in fcf_history[-NORMALIZATION_YEARS:] if x is not None]
    if not recent:
        return None
    return sum(recent) / len(recent)


def estimate_growth_rate(fcf_history: list[float]) -> float:
    """Croissance annuelle moyenne du FCF sur l'historique, ramenée à mi-chemin du
    défaut (3-4 ans d'historique ne suffisent pas à extrapoler 10 ans), puis bornée.
    Retombe sur le défaut si l'historique ne permet pas le calcul (trop court, valeur négative)."""
    values = [x for x in fcf_history if x is not None]
    if len(values) < 3 or values[0] <= 0 or values[-1] <= 0:
        return DEFAULT_GROWTH_RATE
    cagr = (values[-1] / values[0]) ** (1 / (len(values) - 1)) - 1
    blended = (cagr + DEFAULT_GROWTH_RATE) / 2
    return min(max(blended, MIN_GROWTH_RATE), MAX_GROWTH_RATE)


def estimate_discount_rate(beta: float | None) -> float:
    """Coût des fonds propres façon MEDAF (taux sans risque + bêta x prime de risque), borné."""
    if beta is None or beta <= 0:
        return DEFAULT_DISCOUNT_RATE
    rate = RISK_FREE_RATE + beta * EQUITY_RISK_PREMIUM
    return min(max(rate, MIN_DISCOUNT_RATE), MAX_DISCOUNT_RATE)


def compute_dcf(
    base_fcf: float | None,
    growth_rate: float = DEFAULT_GROWTH_RATE,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    terminal_growth: float = TERMINAL_GROWTH,
    projection_years: int = 10,
) -> float | None:
    """
    DCF à deux phases : la croissance part de `growth_rate` et décroît
    linéairement jusqu'à `terminal_growth` sur `projection_years` (une
    entreprise ne garde pas 12 % par an pendant 10 ans), puis valeur
    terminale à croissance stable (formule de Gordon-Shapiro).

    Renvoie la valeur d'entreprise (flux actualisés), pas une valeur par
    action : le passage aux capitaux propres se fait dans
    `equity_value_per_share`, pour tenir compte de la dette nette.
    """
    if base_fcf is None or base_fcf <= 0:
        return None

    pv_sum = 0.0
    fcf = base_fcf
    for year in range(1, projection_years + 1):
        fade = (year - 1) / (projection_years - 1) if projection_years > 1 else 1
        fcf = fcf * (1 + growth_rate + (terminal_growth - growth_rate) * fade)
        pv_sum += fcf / ((1 + discount_rate) ** year)

    terminal_value = (fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** projection_years)

    return pv_sum + pv_terminal


def equity_value_per_share(
    enterprise_value: float | None,
    total_debt: float,
    total_cash: float,
    shares_outstanding: float | None,
) -> float | None:
    """
    Valeur des capitaux propres par action = (valeur d'entreprise - dette nette) / actions,
    avec dette nette = dette totale - trésorerie. Dette et trésorerie doivent
    être connues (0 est une vraie valeur, None doit être filtré en amont).
    Renvoie None si les capitaux propres ressortent négatifs (la dette dépasse
    la valeur des flux futurs).
    """
    if enterprise_value is None or not shares_outstanding:
        return None

    net_debt = total_debt - total_cash
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
    quality_score, notes = compute_quality_score(cf)
    if cf.data_source == STATEMENTS_SOURCE and cf.quote_type != "ETF":
        notes.append(
            "Ratios recalculés sur le dernier exercice annuel (données Yahoo en temps réel "
            "inaccessibles depuis ce serveur) : PER prévisionnel indisponible"
        )

    result = ValuationResult(
        ticker=cf.ticker,
        intrinsic_value_per_share=None,
        current_price=cf.current_price,
        margin_of_safety_pct=None,
        quality_score=quality_score,
        notes=notes,
    )
    if cf.quote_type == "ETF":
        return result
    if cf.financial_currency and cf.currency and cf.financial_currency != cf.currency:
        notes.append(
            f"Comptes publiés en {cf.financial_currency} mais cotation en {cf.currency} : "
            "DCF non calculé pour éviter de mélanger les devises"
        )
        return result

    industry = (cf.industry or "").lower()
    if any(k in industry for k in FINANCIAL_INDUSTRIES_WITHOUT_DCF):
        notes.append(
            "Banque, assurance ou gestion d'actifs : le cash-flow libre ne mesure pas leur "
            "rentabilité (l'argent est leur matière première), DCF non calculé. "
            "Regarder plutôt le ROE et le cours / valeur comptable"
        )
        return result

    if cf.converted_from_currency:
        notes.append(
            f"Comptes publiés en {cf.converted_from_currency}, convertis en {cf.currency} "
            "au taux de change du jour pour le DCF"
        )

    base_fcf = normalized_fcf(cf.fcf_history)
    if base_fcf is None:
        base_fcf = cf.free_cash_flow
    if base_fcf is None:
        notes.append("Historique de cash-flow libre indisponible : DCF non calculé")
        return result
    if base_fcf <= 0:
        notes.append(
            "Cash-flow libre moyen négatif ou nul sur les derniers exercices : "
            "un DCF n'a pas de sens tant que l'entreprise consomme du cash"
        )
        return result

    latest = cf.fcf_history[-1] if cf.fcf_history else None
    if latest is not None and latest < 0.5 * base_fcf:
        notes.append(
            "Dernier cash-flow libre très inférieur à la moyenne (investissements lourds ?) : "
            f"le DCF part de la moyenne des {NORMALIZATION_YEARS} derniers exercices"
        )

    growth = estimate_growth_rate(cf.fcf_history)
    discount = estimate_discount_rate(cf.beta)
    result.growth_rate_used = round(growth, 4)
    result.discount_rate_used = round(discount, 4)

    # None = donnée absente chez Yahoo, à ne pas confondre avec une dette ou trésorerie réellement à 0
    if cf.total_debt is None or cf.total_cash is None:
        notes.append(
            "Dette nette indisponible (données Yahoo incomplètes), valeur intrinsèque "
            "non calculée pour éviter un chiffre trompeur"
        )
        return result

    # Pour les sociétés à plusieurs classes d'actions (Alphabet), Yahoo ne donne que le nombre
    # d'actions de la classe cotée : la capitalisation / le cours donne le total, cohérent avec le FCF
    shares = cf.shares_outstanding
    if cf.market_cap and cf.current_price:
        shares = cf.market_cap / cf.current_price

    result.base_fcf = base_fcf
    result.net_debt = cf.total_debt - cf.total_cash
    result.shares_used = shares
    intrinsic_value = equity_value_per_share(
        compute_dcf(base_fcf, growth, discount), cf.total_debt, cf.total_cash, shares
    )
    if intrinsic_value is None:
        notes.append(
            "La dette nette dépasse la valeur actualisée des cash-flows : DCF non applicable "
            "(fréquent pour les entreprises très endettées, comme les utilities)"
        )
        return result

    result.intrinsic_value_per_share = round(intrinsic_value, 2)
    if cf.current_price:
        result.margin_of_safety_pct = round(
            (intrinsic_value - cf.current_price) / intrinsic_value * 100, 1
        )
        ratio = intrinsic_value / cf.current_price
        result.dcf_reliable = RELIABLE_RATIO_MIN <= ratio <= RELIABLE_RATIO_MAX
        if not result.dcf_reliable:
            notes.append(
                f"Valeur intrinsèque trop éloignée du cours (x{ratio:.2f}) : le marché intègre "
                f"des perspectives que ce DCF simple (croissance {growth:.0%} décroissante, "
                f"actualisation {discount:.1%}) ne capte pas. Chiffre indicatif seulement"
            )

    return result
