"""
Récupération des données financières brutes pour une action donnée.

Source : yfinance (gratuit, non officiel, pioche sur Yahoo Finance).
Couverture correcte sur les actions US et européennes (ticker suffixé,
ex: "AIR.PA" pour Airbus à Paris, "MC.PA" pour LVMH).

Limite connue : la profondeur historique des comptes de résultat / bilans
est parfois moins complète hors US. À vérifier ticker par ticker.
"""

from dataclasses import dataclass, field
import yfinance as yf


@dataclass
class CompanyFinancials:
    ticker: str
    name: str | None = None
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

    raw_error: str | None = None


def fetch_company_financials(ticker: str) -> CompanyFinancials:
    """
    Va chercher les fondamentaux d'une entreprise.
    En cas d'échec partiel (donnée manquante), on renvoie quand même
    l'objet avec les champs disponibles à None plutôt que de planter :
    le scoring downstream doit savoir gérer les None.
    """
    result = CompanyFinancials(ticker=ticker)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        result.name = info.get("longName") or info.get("shortName")
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
