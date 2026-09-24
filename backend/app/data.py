"""
Récupération des données financières brutes pour une action donnée.

Source : yfinance (gratuit, non officiel, pioche sur Yahoo Finance).
Couverture correcte sur les actions US et européennes (ticker suffixé,
ex: "AIR.PA" pour Airbus à Paris, "MC.PA" pour LVMH).

Limite connue : la profondeur historique des comptes de résultat / bilans
est parfois moins complète hors US. À vérifier ticker par ticker.
"""

from dataclasses import dataclass, field
import time
import yfinance as yf

# Yahoo renvoie parfois un info partiel (bilan et ratios absents) sur un appel isolé :
# si tous ces champs manquent, on retente avant de conclure qu'ils sont indisponibles
CRITICAL_INFO_KEYS = ("totalDebt", "totalCash", "returnOnEquity", "operatingMargins")
MAX_EXTRA_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 1.5

# Message utilisé par main.py pour distinguer un ticker inconnu (404) d'une panne de source (502)
INVALID_TICKER_ERROR = "Ticker invalide ou données introuvables"


@dataclass
class CompanyFinancials:
    ticker: str
    name: str | None = None
    quote_type: str | None = None  # "EQUITY", "ETF", ...
    currency: str | None = None
    current_price: float | None = None
    market_cap: float | None = None

    # Ratios de valorisation
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    ev_to_ebitda: float | None = None

    # Qualité / rentabilité
    return_on_equity: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    debt_to_equity: float | None = None

    # Cash flow (nécessaire pour le DCF)
    free_cash_flow: float | None = None
    fcf_history: list[float] = field(default_factory=list)  # du plus ancien au plus récent
    shares_outstanding: float | None = None

    # Bilan (pour passer de la valeur d'entreprise à la valeur des capitaux propres)
    total_debt: float | None = None
    total_cash: float | None = None

    raw_error: str | None = None


def _fetch_ticker_with_retry(ticker: str) -> tuple[yf.Ticker, dict]:
    """
    Récupère t.info, en retentant jusqu'à MAX_EXTRA_ATTEMPTS fois si tous les
    champs critiques sont absents. Pas de retry pour un ticker inconnu (info
    sans symbole) ni pour un ETF, qui n'ont de toute façon pas ces champs.
    """
    for attempt in range(MAX_EXTRA_ATTEMPTS + 1):
        if attempt > 0:
            time.sleep(RETRY_DELAY_SECONDS)
        t = yf.Ticker(ticker)  # nouvel objet à chaque tentative : yfinance met info en cache
        info = t.info or {}
        is_unknown = not info.get("symbol") and not info.get("shortName")
        if is_unknown or info.get("quoteType") == "ETF":
            break
        if any(info.get(key) is not None for key in CRITICAL_INFO_KEYS):
            break
    return t, info


def fetch_company_financials(ticker: str) -> CompanyFinancials:
    """
    Va chercher les fondamentaux d'une entreprise.
    En cas d'échec partiel (donnée manquante), on renvoie quand même
    l'objet avec les champs disponibles à None plutôt que de planter :
    le scoring downstream doit savoir gérer les None.
    """
    result = CompanyFinancials(ticker=ticker)
    try:
        t, info = _fetch_ticker_with_retry(ticker)

        # Sur un ticker inconnu, yfinance ne lève pas d'exception : il renvoie un info quasi vide
        if not info.get("symbol") and not info.get("shortName"):
            result.raw_error = INVALID_TICKER_ERROR
            return result

        result.name = info.get("longName") or info.get("shortName")
        result.quote_type = info.get("quoteType")
        result.currency = info.get("currency")
        result.current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        result.market_cap = info.get("marketCap")

        result.trailing_pe = info.get("trailingPE")
        result.forward_pe = info.get("forwardPE")
        result.price_to_book = info.get("priceToBook")
        result.ev_to_ebitda = info.get("enterpriseToEbitda")

        result.return_on_equity = info.get("returnOnEquity")
        result.gross_margin = info.get("grossMargins")
        result.operating_margin = info.get("operatingMargins")
        result.debt_to_equity = info.get("debtToEquity")

        result.free_cash_flow = info.get("freeCashflow")
        result.shares_outstanding = info.get("sharesOutstanding")

        result.total_debt = info.get("totalDebt")
        result.total_cash = info.get("totalCash")

        # Historique de cash flow libre sur les années disponibles (pour projeter le DCF)
        try:
            cf = t.cashflow  # DataFrame, colonnes = exercices, plus récent en premier
            if cf is not None and "Free Cash Flow" in cf.index:
                fcf_row = cf.loc["Free Cash Flow"].dropna()
                result.fcf_history = list(reversed(fcf_row.tolist()))
        except Exception:
            pass  # pas bloquant, le DCF peut retomber sur free_cash_flow seul

    except Exception as e:
        result.raw_error = str(e)

    return result
