"""
Récupération des données financières brutes pour une action donnée.

Source : yfinance (gratuit, non officiel, pioche sur Yahoo Finance).
Couverture correcte sur les actions US et européennes (ticker suffixé,
ex: "AIR.PA" pour Airbus à Paris, "MC.PA" pour LVMH).

Limite connue : la profondeur historique des comptes de résultat / bilans
est parfois moins complète hors US. À vérifier ticker par ticker.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import logging
import threading
import time
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

logger = logging.getLogger(__name__)

# Yahoo renvoie parfois un info partiel (bilan et ratios absents) sur un appel isolé :
# si tous ces champs manquent, on retente avant de conclure qu'ils sont indisponibles
CRITICAL_INFO_KEYS = ("totalDebt", "totalCash", "returnOnEquity", "operatingMargins")
MAX_EXTRA_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 4  # assez espacé pour ne pas déclencher le rate limiting de Yahoo

# Messages utilisés par main.py pour choisir le code HTTP : ticker inconnu (404),
# Yahoo qui refuse l'accès (503), toute autre erreur (502)
INVALID_TICKER_ERROR = "Ticker invalide ou données introuvables"
SOURCE_UNAVAILABLE_ERROR = "Source de données Yahoo indisponible (accès refusé ou limité par Yahoo)"

QUOTE_SUMMARY_SOURCE = "quoteSummary"
STATEMENTS_SOURCE = "etats_financiers"

# Sur un refus d'accès (crumb rejeté, rate limiting), yfinance ne lève pas d'exception :
# il logue l'erreur HTTP et renvoie un info vide, comme pour un ticker inconnu.
# On distingue les deux cas grâce à ces logs.
_ACCESS_DENIED_MARKERS = ("HTTP Error 401", "HTTP Error 429", "Invalid Crumb", "Unauthorized", "rate-limited")
# Les deux derniers viennent de l'API chart (history), qui répond même quand quoteSummary est bloqué
_NOT_FOUND_MARKERS = ("HTTP Error 404", "Quote not found", "may be delisted", "possibly delisted")


class _ThreadLogCapture(logging.Handler):
    """Garde les messages de yfinance émis par le thread courant (les requêtes FastAPI tournent en parallèle)."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.thread_id = threading.get_ident()
        self.messages: list[str] = []

    def emit(self, record):
        if record.thread == self.thread_id:
            self.messages.append(record.getMessage())


@contextmanager
def capture_yfinance_errors():
    handler = _ThreadLogCapture()
    yf_logger = logging.getLogger("yfinance")
    yf_logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        yf_logger.removeHandler(handler)


def classify_empty_response(yahoo_errors: list[str]) -> str:
    """Ticker inconnu ou accès refusé, d'après les erreurs loguées par yfinance."""
    if any(m in e for e in yahoo_errors for m in _NOT_FOUND_MARKERS):
        return INVALID_TICKER_ERROR
    if any(m in e for e in yahoo_errors for m in _ACCESS_DENIED_MARKERS):
        return SOURCE_UNAVAILABLE_ERROR
    return INVALID_TICKER_ERROR


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

    # Risque de marché (sert au taux d'actualisation du DCF)
    beta: float | None = None
    # Devise des états financiers, parfois différente de celle de la cotation (ADR, cotations étrangères)
    financial_currency: str | None = None

    # Cash flow (nécessaire pour le DCF)
    free_cash_flow: float | None = None
    fcf_history: list[float] = field(default_factory=list)  # du plus ancien au plus récent
    shares_outstanding: float | None = None

    # Bilan (pour passer de la valeur d'entreprise à la valeur des capitaux propres)
    total_debt: float | None = None
    total_cash: float | None = None

    # QUOTE_SUMMARY_SOURCE (ratios Yahoo glissants) ou STATEMENTS_SOURCE (recalculés sur le dernier exercice)
    data_source: str | None = None

    raw_error: str | None = None


def _is_identified(info: dict) -> bool:
    return bool(info.get("symbol") or info.get("shortName"))


def _has_critical_fields(info: dict) -> bool:
    return any(info.get(key) is not None for key in CRITICAL_INFO_KEYS)


def _fetch_info(ticker: str, attempt: int) -> tuple[yf.Ticker, dict, list[str]]:
    t = yf.Ticker(ticker)  # nouvel objet à chaque tentative : yfinance met info en cache
    with capture_yfinance_errors() as yahoo_errors:
        info = t.info or {}
    logger.info(
        "%s tentative %d : %d clés, symbol=%r, champs critiques=%s",
        ticker, attempt, len(info), info.get("symbol"),
        {key: info.get(key) for key in CRITICAL_INFO_KEYS},
    )
    if not _is_identified(info):
        logger.warning(
            "%s tentative %d : info vide ou sans identifiant, brut=%r, erreurs yfinance=%r",
            ticker, attempt, info, yahoo_errors,
        )
    return t, info, yahoo_errors


def _fetch_ticker_with_retry(ticker: str) -> tuple[yf.Ticker, dict, list[str]]:
    """
    Récupère t.info. La validité du ticker se juge sur la première tentative
    uniquement. Si le ticker est identifié mais que tous les champs critiques
    manquent, on retente jusqu'à MAX_EXTRA_ATTEMPTS fois pour les compléter.
    Une tentative suivante vide ou en erreur (rate limiting probable) est
    ignorée : on garde la première réponse, déjà valide. Pas de retry pour un
    ETF, qui n'a de toute façon pas ces champs.
    """
    t, info, yahoo_errors = _fetch_info(ticker, attempt=1)
    if not _is_identified(info) or info.get("quoteType") == "ETF" or _has_critical_fields(info):
        return t, info, yahoo_errors

    for attempt in range(2, MAX_EXTRA_ATTEMPTS + 2):
        time.sleep(RETRY_DELAY_SECONDS)
        try:
            retry_t, retry_info, retry_errors = _fetch_info(ticker, attempt)
        except Exception as e:
            logger.warning("%s tentative %d en erreur, ignorée : %s", ticker, attempt, e)
            continue
        if _has_critical_fields(retry_info):
            return retry_t, retry_info, retry_errors

    logger.warning("%s : champs critiques toujours absents après %d tentatives", ticker, MAX_EXTRA_ATTEMPTS + 1)
    return t, info, yahoo_errors


def fetch_company_financials(ticker: str) -> CompanyFinancials:
    """
    Va chercher les fondamentaux d'une entreprise.
    En cas d'échec partiel (donnée manquante), on renvoie quand même
    l'objet avec les champs disponibles à None plutôt que de planter :
    le scoring downstream doit savoir gérer les None.
    """
    result = CompanyFinancials(ticker=ticker)
    try:
        t, info, yahoo_errors = _fetch_ticker_with_retry(ticker)

        if _is_identified(info):
            _fill_from_info(result, info)
        else:
            # Ticker inconnu ou accès refusé : dans les deux cas yfinance renvoie un info quasi vide
            error = classify_empty_response(yahoo_errors)
            if error != SOURCE_UNAVAILABLE_ERROR:
                result.raw_error = error
                return result
            # quoteSummary est bloqué (cas de Render) mais pas l'historique ni les états financiers
            logger.warning("%s : quoteSummary refusé, calcul des ratios depuis les états financiers", ticker)
            t = yf.Ticker(ticker)
            if not _fill_from_statements(result, t):
                return result

        _fill_fcf_history(result, t)

    except YFRateLimitError:
        result.raw_error = SOURCE_UNAVAILABLE_ERROR
    except Exception as e:
        result.raw_error = str(e)

    return result


def _fill_from_info(result: CompanyFinancials, info: dict) -> None:
    result.data_source = QUOTE_SUMMARY_SOURCE
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

    result.beta = info.get("beta")
    result.financial_currency = info.get("financialCurrency")

    result.free_cash_flow = info.get("freeCashflow")
    result.shares_outstanding = info.get("sharesOutstanding")

    result.total_debt = info.get("totalDebt")
    result.total_cash = info.get("totalCash")


def _latest(df, *labels) -> float | None:
    """Valeur du dernier exercice pour la première ligne disponible parmi `labels` (colonnes : plus récent en premier)."""
    if df is None or df.empty:
        return None
    for label in labels:
        if label in df.index:
            values = df.loc[label].dropna()
            if not values.empty:
                return float(values.iloc[0])
    return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator or denominator <= 0:
        return None
    return numerator / denominator


def _fill_from_statements(result: CompanyFinancials, t: yf.Ticker) -> bool:
    """
    Remplace t.info quand Yahoo refuse quoteSummary : identité et cours depuis
    l'historique (API chart), ratios recalculés sur le dernier exercice annuel
    (API fundamentals-timeseries). Mêmes unités que t.info (debt_to_equity en %).
    Renvoie False, avec raw_error renseigné, si le ticker est introuvable ou
    si ces services sont bloqués aussi.
    """
    with capture_yfinance_errors() as yahoo_errors:
        history = t.history(period="5d")
        meta = t.history_metadata or {}
    if history.empty or not meta.get("symbol"):
        result.raw_error = classify_empty_response(yahoo_errors)
        return False

    result.data_source = STATEMENTS_SOURCE
    result.name = meta.get("longName") or meta.get("shortName")
    result.quote_type = meta.get("instrumentType")
    result.currency = meta.get("currency")
    result.current_price = float(history["Close"].iloc[-1])
    try:
        result.shares_outstanding = t.fast_info.shares
    except Exception:
        pass  # repli sur le bilan plus bas

    if result.quote_type == "ETF":
        return True  # pas d'états financiers d'entreprise pour un ETF

    balance_sheet, income = t.balance_sheet, t.income_stmt
    result.total_debt = _latest(balance_sheet, "Total Debt")
    result.total_cash = _latest(
        balance_sheet, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"
    )
    equity = _latest(balance_sheet, "Stockholders Equity", "Common Stock Equity")
    if not result.shares_outstanding:
        result.shares_outstanding = _latest(balance_sheet, "Ordinary Shares Number")

    revenue = _latest(income, "Total Revenue", "Operating Revenue")
    net_income = _latest(income, "Net Income")
    ebitda = _latest(income, "EBITDA", "Normalized EBITDA")

    if result.shares_outstanding:
        result.market_cap = result.current_price * result.shares_outstanding

    result.return_on_equity = _ratio(net_income, equity)
    result.operating_margin = _ratio(_latest(income, "Operating Income"), revenue)
    result.gross_margin = _ratio(_latest(income, "Gross Profit"), revenue)
    debt_ratio = _ratio(result.total_debt, equity)
    result.debt_to_equity = debt_ratio * 100 if debt_ratio is not None else None

    if net_income is not None and net_income > 0:
        result.trailing_pe = _ratio(result.market_cap, net_income)
    result.price_to_book = _ratio(result.market_cap, equity)
    if None not in (result.market_cap, result.total_debt, result.total_cash):
        enterprise_value = result.market_cap + result.total_debt - result.total_cash
        result.ev_to_ebitda = _ratio(enterprise_value, ebitda)
    # forward_pe reste à None : les prévisions d'analystes ne sont disponibles que via quoteSummary
    return True


def _fill_fcf_history(result: CompanyFinancials, t: yf.Ticker) -> None:
    """Historique de cash flow libre sur les années disponibles (pour projeter le DCF)."""
    try:
        cf = t.cashflow  # DataFrame, colonnes = exercices, plus récent en premier
        if cf is not None and "Free Cash Flow" in cf.index:
            fcf_row = cf.loc["Free Cash Flow"].dropna()
            result.fcf_history = list(reversed(fcf_row.tolist()))
            if result.free_cash_flow is None and result.fcf_history:
                result.free_cash_flow = result.fcf_history[-1]
    except Exception:
        pass  # pas bloquant, le DCF peut retomber sur free_cash_flow seul
