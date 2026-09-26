"""
Familles de secteurs et seuils du score qualité propres à chacune.

Un PER de 30 est cher pour un industriel mais courant pour un éditeur de
logiciels ; une dette égale aux fonds propres est lourde pour une société de
luxe mais normale pour un réseau électrique. Chaque famille a donc ses propres
paliers. Les seuils sont des ordres de grandeur usuels, à ajuster à ta guise.
"""

from dataclasses import dataclass

# Secteurs GICS / ICB / Yahoo -> familles lisibles (premier mot-clé trouvé gagne, d'où l'ordre)
SECTOR_KEYWORDS = [
    ("Immobilier", ("real estate", "reit", "property", "properties")),
    ("Services publics", ("utilit", "electricity", "gas, water", "water")),
    ("Santé", ("health", "pharma", "biotech", "medical")),
    ("Technologie", ("technology", "software", "semiconductor", "information tech", "electronic")),
    ("Communication", ("communication", "telecom", "media", "entertainment")),
    ("Finance", ("financ", "bank", "insurance", "investment", "asset management", "capital market")),
    ("Énergie", ("energy", "oil", "gas", "coal", "renewable")),
    ("Matériaux", ("material", "basic resource", "chemical", "mining", "metal", "steel", "paper")),
    ("Consommation", ("consumer", "retail", "food", "beverage", "personal", "household", "travel",
                      "leisure", "hospitality", "automobile", "auto", "tobacco", "apparel", "luxury")),
    ("Industrie", ("industrial", "aerospace", "defense", "construction", "engineering", "transport",
                   "capital goods", "machinery", "logistics", "commerce")),
]

# Industries Yahoo pour lesquelles marges, dette et FCF ne mesurent pas la rentabilité
# (Visa / Mastercard sont en "Credit Services" et restent notées comme des entreprises classiques)
BALANCE_SHEET_INDUSTRIES = (
    "bank", "insurance", "capital markets", "asset management", "mortgage", "financial conglomerates",
)


def normalize_sector(*candidates: str | None) -> str:
    for raw in candidates:
        if not raw:
            continue
        text = raw.lower()
        for family, keywords in SECTOR_KEYWORDS:
            if any(k in text for k in keywords):
                return family
    return "Non classé"


def is_balance_sheet_business(industry: str | None) -> bool:
    text = (industry or "").lower()
    return any(k in text for k in BALANCE_SHEET_INDUSTRIES)


@dataclass(frozen=True)
class ScoreProfile:
    """Paliers (5 / 3,5 / 2 points) de chaque pilier. None = pilier non pertinent pour la famille."""
    label: str
    roe: tuple[float, float, float] | None = (0.20, 0.12, 0.05)  # au-dessus = mieux
    operating_margin: tuple[float, float, float] | None = (0.20, 0.10, 0.03)  # au-dessus = mieux
    debt_to_equity: tuple[float, float, float] | None = (50, 100, 200)  # en %, en dessous = mieux
    pe: tuple[float, float, float] | None = (15, 25, 40)  # en dessous = mieux
    price_to_book: tuple[float, float, float] | None = None  # en dessous = mieux


DEFAULT_PROFILE = ScoreProfile("général")

PROFILES = {
    "Technologie": ScoreProfile("technologie", operating_margin=(0.25, 0.15, 0.05), pe=(22, 35, 55)),
    "Santé": ScoreProfile("santé", operating_margin=(0.25, 0.15, 0.05), pe=(20, 30, 45)),
    "Communication": ScoreProfile("communication", operating_margin=(0.25, 0.15, 0.05), pe=(18, 28, 45)),
    "Consommation": ScoreProfile("consommation", operating_margin=(0.15, 0.08, 0.03), pe=(16, 25, 38)),
    "Industrie": ScoreProfile("industrie", operating_margin=(0.15, 0.09, 0.04), pe=(15, 22, 32)),
    "Matériaux": ScoreProfile("matériaux", operating_margin=(0.18, 0.10, 0.04), pe=(12, 18, 28)),
    "Énergie": ScoreProfile("énergie", operating_margin=(0.18, 0.10, 0.04), debt_to_equity=(40, 80, 150), pe=(10, 15, 25)),
    "Services publics": ScoreProfile("services publics", roe=(0.12, 0.09, 0.05), operating_margin=(0.20, 0.12, 0.06),
                                     debt_to_equity=(100, 175, 275), pe=(14, 20, 28)),
    "Immobilier": ScoreProfile("immobilier", roe=(0.10, 0.07, 0.03), operating_margin=(0.40, 0.25, 0.10),
                               debt_to_equity=(80, 150, 250), pe=(15, 25, 40)),
    "Finance": ScoreProfile("finance", pe=(14, 22, 35)),
}

# Banques, assurances, gestionnaires : notées sur ROE, PER et cours / valeur comptable
BALANCE_SHEET_PROFILE = ScoreProfile(
    "banque / assurance", roe=(0.14, 0.10, 0.06), operating_margin=None, debt_to_equity=None,
    pe=(9, 13, 20), price_to_book=(1.0, 1.6, 2.5),
)


def score_profile(sector: str | None, industry: str | None) -> ScoreProfile:
    if is_balance_sheet_business(industry):
        return BALANCE_SHEET_PROFILE
    return PROFILES.get(normalize_sector(sector, industry), DEFAULT_PROFILE)
