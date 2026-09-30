"""
Logique de valorisation, inspirée de ce que font Baggr / Mungr :
- un DCF simplifié pour estimer une valeur intrinsèque
- une marge de sécurité (écart entre valeur intrinsèque et prix actuel)
- un score de qualité composite sur 20
- un prix juste qui croise plusieurs méthodes (DCF, PER du secteur, cours /
  valeur comptable justifié pour les banques), avec un verdict sous-évaluée /
  correcte / surévaluée

Tout est volontairement transparent et modifiable : contrairement à un
outil fermé, tu peux ajuster chaque hypothèse (taux de croissance, taux
d'actualisation) et voir l'impact direct sur le résultat.
"""

from dataclasses import dataclass
from .data import STATEMENTS_SOURCE, CompanyFinancials
from .sectors import DEFAULT_PROFILE, ScoreProfile, is_balance_sheet_business, score_profile


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
    # Prix juste : moyenne des méthodes disponibles (voir blend_fair_value)
    fair_value: float | None = None
    fair_value_low: float | None = None  # méthode la plus prudente
    fair_value_high: float | None = None  # méthode la plus optimiste
    fair_value_upside_pct: float | None = None  # (prix juste / cours - 1) : positif = potentiel de hausse
    fair_value_verdict: str | None = None  # VERDICT_UNDER, VERDICT_FAIR ou VERDICT_OVER
    fair_value_divergent: bool = False  # méthodes trop éloignées entre elles : prix juste fragile
    # Ingrédients par action, gardés tels quels d'une nuit sur l'autre (le verdict suit le cours du jour)
    fair_value_pe: float | None = None  # bénéfice par action x PER normal du secteur
    fair_value_pb: float | None = None  # valeur comptable par action x cours / valeur comptable justifié
    fair_pe_used: float | None = None
    justified_pb_used: float | None = None
    fair_value_hist_pe: float | None = None  # bénéfice par action x PER médian de l'action sur 10 ans
    hist_pe_median: float | None = None
    hist_pe_years: int | None = None


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

# Nombre d'exercices moyennés pour le FCF de départ (lisse une année de gros investissements)
NORMALIZATION_YEARS = 3

# Hors de cette fourchette (valeur intrinsèque / prix), le DCF est jugé non fiable
RELIABLE_RATIO_MIN = 0.4
RELIABLE_RATIO_MAX = 2.5

# Prix juste : au-delà de 15 % d'écart entre le cours et le prix juste, l'action est jugée
# sous- ou surévaluée ; en deçà, l'imprécision des estimations ne permet pas de trancher
VERDICT_BAND = 0.15
VERDICT_UNDER = "sous-évaluée"
VERDICT_FAIR = "correcte"
VERDICT_OVER = "surévaluée"
# Au-delà de ce rapport entre la méthode la plus optimiste et la plus prudente, le prix juste est fragile
DIVERGENCE_MAX = 2.0
# Au-delà de ce rapport entre PER passé et PER prévisionnel, les deux ne décrivent pas le même bénéfice
# (erreur de devise Yahoo, pence au lieu de livres à Londres) : seul le PER passé, publié, est gardé
MAX_EPS_GAP = 3.0
# Bornes du cours / valeur comptable justifié : un ROE exceptionnel ne justifie pas 10 fois les fonds propres
MIN_JUSTIFIED_PB = 0.3
MAX_JUSTIFIED_PB = 3.0


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


def _tier_points(value: float, tiers: tuple[float, float, float], higher_is_better: bool) -> float:
    """5 / 3,5 / 2 / 0 points selon le palier atteint."""
    for points, threshold in zip((5, 3.5, 2), tiers):
        if (value > threshold) if higher_is_better else (value < threshold):
            return points
    return 0


def compute_quality_score(cf: CompanyFinancials) -> tuple[float | None, list[str]]:
    """
    Score composite sur 20 : rentabilité (ROE), marges, endettement, valorisation
    (PER, et cours / valeur comptable pour les banques). Chaque pilier vaut 5 points,
    avec des paliers propres au secteur (voir sectors.py). Ramené sur 20 même si
    certains piliers sont indisponibles.
    """
    if cf.quote_type == "ETF":
        return None, ["Score qualité non pertinent pour un ETF, pas de fondamentaux d'entreprise"]

    profile = score_profile(cf.sector, cf.industry)
    notes = []
    points = 0.0
    pillars_scored = 0

    pillars = [
        (cf.return_on_equity, profile.roe, True, "ROE faible : rentabilité des capitaux propres à surveiller"),
        (cf.operating_margin, profile.operating_margin, True, "Marge opérationnelle faible pour le secteur"),
        (cf.debt_to_equity, profile.debt_to_equity, False, "Endettement élevé pour le secteur"),
        (cf.trailing_pe if cf.trailing_pe and cf.trailing_pe > 0 else None, profile.pe, False,
         "Valorisation élevée sur le PER pour le secteur (à mettre en regard de la croissance attendue)"),
        (cf.price_to_book if cf.price_to_book and cf.price_to_book > 0 else None, profile.price_to_book, False,
         "Cours élevé par rapport à la valeur comptable"),
    ]
    for value, tiers, higher_is_better, weak_note in pillars:
        if value is None or tiers is None:
            continue
        pillars_scored += 1
        earned = _tier_points(value, tiers, higher_is_better)
        points += earned
        if earned == 0:
            notes.append(weak_note)

    if pillars_scored == 0:
        return None, ["Données insuffisantes pour calculer un score"]

    if profile is not DEFAULT_PROFILE:
        notes.append(f"Score calibré sur les standards du secteur : {profile.label}")
    score_on_20 = (points / (pillars_scored * 5)) * 20
    return round(score_on_20, 1), notes


def normalized_eps(price: float | None, trailing_pe: float | None, forward_pe: float | None) -> float | None:
    """Bénéfice par action retrouvé à partir des PER (cours / PER) : moyenne du bénéfice des 12
    derniers mois et de celui attendu par les analystes, pour lisser une année exceptionnelle
    et tenir compte de la croissance attendue. None si l'entreprise perd de l'argent."""
    if not price or price <= 0:
        return None
    eps = [price / pe for pe in (trailing_pe, forward_pe) if pe is not None and pe > 0]
    if len(eps) == 2 and max(eps) / min(eps) > MAX_EPS_GAP:
        eps = eps[:1]
    return sum(eps) / len(eps) if eps else None


def pe_fair_value(cf: CompanyFinancials, profile: ScoreProfile) -> float | None:
    """Ce que vaudrait l'action si le marché la payait au PER normal de son secteur."""
    eps = normalized_eps(cf.current_price, cf.trailing_pe, cf.forward_pe)
    return eps * profile.fair_pe if eps else None


def justified_price_to_book(roe: float | None, cost_of_equity: float, growth: float = TERMINAL_GROWTH) -> float | None:
    """Cours / valeur comptable justifié = (ROE - g) / (r - g), formule classique pour les banques :
    une banque qui rapporte exactement son coût des fonds propres vaut sa valeur comptable (x1),
    une qui rapporte plus vaut davantage. Borné pour éviter les valeurs extrêmes."""
    if roe is None or cost_of_equity <= growth:
        return None
    pb = (roe - growth) / (cost_of_equity - growth)
    return min(max(pb, MIN_JUSTIFIED_PB), MAX_JUSTIFIED_PB)


def fair_value_verdict(price: float | None, fair_value: float | None) -> str | None:
    if not price or not fair_value:
        return None
    if price < fair_value * (1 - VERDICT_BAND):
        return VERDICT_UNDER
    if price > fair_value * (1 + VERDICT_BAND):
        return VERDICT_OVER
    return VERDICT_FAIR


def historical_pe_fair_value(pe_history: dict | None) -> float | None:
    """Bénéfice par action du dernier exercice x PER médian de l'action sur ses 10 dernières années
    (screener/financials.py). Corrige l'angle mort du PER du secteur : Air Liquide ou Hermès, que le
    marché paie durablement plus cher que leur secteur, sont jugées face à leur propre passé."""
    if not pe_history or not pe_history.get("median") or not pe_history.get("eps"):
        return None
    return pe_history["median"] * pe_history["eps"]


def blend_fair_value(
    price: float | None,
    dcf_value: float | None,
    pe_value: float | None,
    pb_value: float | None,
    hist_pe_value: float | None = None,
) -> dict:
    """
    Prix juste = moyenne simple des méthodes disponibles. Chaque méthode a ses angles morts :
    le DCF dépend beaucoup des hypothèses de croissance, le PER du secteur ignore la croissance
    propre à l'entreprise, le PER historique suppose que le marché la payait au bon prix en moyenne,
    le cours / valeur comptable ne vaut que pour les banques. Les
    croiser limite l'erreur.

    Comme pour le DCF, une méthode qui donne plus de 2,5 fois ou moins de 0,4 fois le cours
    est écartée : elle ne capte pas l'entreprise (bénéfice exceptionnel ou effondré) ou
    repose sur une donnée Yahoo aberrante (PER de 0,0007, cours / valeur comptable de 0,001).

    Même calcul que fairValueOf dans l'appli (frontend/index.html), qui le refait avec
    les hypothèses DCF personnelles de l'utilisateur.
    """
    methods = [
        v for v in (dcf_value, pe_value, pb_value, hist_pe_value)
        if v is not None and v > 0 and price and RELIABLE_RATIO_MIN <= v / price <= RELIABLE_RATIO_MAX
    ]
    if not methods:
        return {"fair_value": None, "fair_value_low": None, "fair_value_high": None,
                "fair_value_upside_pct": None, "fair_value_verdict": None, "fair_value_divergent": False}
    fair = sum(methods) / len(methods)
    low, high = min(methods), max(methods)
    return {
        "fair_value": round(fair, 2),
        "fair_value_low": round(low, 2),
        "fair_value_high": round(high, 2),
        "fair_value_upside_pct": round((fair / price - 1) * 100, 1) if price else None,
        "fair_value_verdict": fair_value_verdict(price, fair),
        "fair_value_divergent": high / low > DIVERGENCE_MAX,
    }


def _add_fair_value(result: ValuationResult, cf: CompanyFinancials, pe_history: dict | None = None) -> None:
    profile = score_profile(cf.sector, cf.industry)
    result.fair_value_pe = pe_fair_value(cf, profile)
    if result.fair_value_pe is not None:
        result.fair_value_pe = round(result.fair_value_pe, 2)
        result.fair_pe_used = profile.fair_pe

    if is_balance_sheet_business(cf.industry) and cf.current_price and cf.price_to_book and cf.price_to_book > 0:
        pb = justified_price_to_book(cf.return_on_equity, estimate_discount_rate(cf.beta))
        if pb is not None:
            book_value_per_share = cf.current_price / cf.price_to_book
            result.fair_value_pb = round(book_value_per_share * pb, 2)
            result.justified_pb_used = round(pb, 2)

    hist = historical_pe_fair_value(pe_history)
    if hist is not None:
        result.fair_value_hist_pe = round(hist, 2)
        result.hist_pe_median = pe_history["median"]
        result.hist_pe_years = len(pe_history.get("years") or [])

    fair = blend_fair_value(cf.current_price, result.intrinsic_value_per_share, result.fair_value_pe,
                            result.fair_value_pb, result.fair_value_hist_pe)
    for key, value in fair.items():
        setattr(result, key, value)
    if result.fair_value is None:
        result.notes.append(
            "Prix juste non calculé : aucune méthode (DCF, PER du secteur, PER historique, valeur comptable) "
            "ne donne un résultat exploitable, à moins de 0,4 ou plus de 2,5 fois le cours"
        )
    elif result.fair_value_divergent:
        result.notes.append(
            f"Prix juste à prendre avec prudence : les méthodes vont de {result.fair_value_low:g} "
            f"à {result.fair_value_high:g} (plus du double)"
        )


def evaluate_company(cf: CompanyFinancials, pe_history: dict | None = None) -> ValuationResult:
    """pe_history : PER historique de l'action archivé par screener/financials.py (facultatif)."""
    result = _evaluate_dcf(cf)
    if cf.quote_type != "ETF":
        _add_fair_value(result, cf, pe_history)
    return result


def _evaluate_dcf(cf: CompanyFinancials) -> ValuationResult:
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

    if is_balance_sheet_business(cf.industry):
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
