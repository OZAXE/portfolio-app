"""
Courbe de cours d'une action pour la fiche de l'appli : clôtures quotidiennes sur 10 ans.

Vient de l'API chart de Yahoo (history), qui répond même quand quoteSummary est bloqué sur Render.
Cours non ajustés des dividendes (auto_adjust=False), comme chez un courtier : le cours affiché un
jour donné est celui qui s'échangeait vraiment. Les divisions d'actions restent corrigées par Yahoo,
sinon NVIDIA (division par 10 en 2024) ferait une chute de 90 % sur la courbe.
"""

import math

import pandas as pd

PRICE_HISTORY_PERIOD = "10y"


def closes_to_points(closes: pd.Series) -> list[list]:
    """[date ISO, clôture] du plus ancien au plus récent, sans les jours vides ni les cours aberrants
    (Yahoo renvoie parfois 0 ou NaN un jour férié local)."""
    points = []
    for day, close in closes.items():
        value = float(close) if close is not None else math.nan
        if math.isfinite(value) and value > 0:
            points.append([pd.Timestamp(day).date().isoformat(), round(value, 4)])
    return points


def fetch_price_history(ticker: str) -> dict:
    """Cours en unité principale, comme la fiche : Yahoo cote Londres en pence (GBp), ramenés en livres."""
    import yfinance as yf

    from .data import MINOR_CURRENCIES

    t = yf.Ticker(ticker)
    history = t.history(period=PRICE_HISTORY_PERIOD, auto_adjust=False)
    if history is None or history.empty or "Close" not in history:
        raise ValueError(f"Pas de cours disponibles pour {ticker}")
    currency = (getattr(t, "history_metadata", None) or {}).get("currency")
    closes = history["Close"]
    if currency in MINOR_CURRENCIES:
        currency, factor = MINOR_CURRENCIES[currency]
        closes = closes / factor
    points = closes_to_points(closes)
    if len(points) < 2:
        raise ValueError(f"Pas assez de cours pour tracer la courbe de {ticker}")
    return {"ticker": ticker, "currency": currency, "points": points}


# --- Cours de secours quand GOOGLEFINANCE n'en donne pas (onglet Positions) ---
# Google Finance ne connaît pas tous les ETF européens : l'Amundi MSCI World Information Technology
# (LU0533033667, offert par Trade Republic) restait sans cours, donc sans valeur, et le relevé de nuit
# refusait d'enregistrer un total incomplet. Dernière clôture Yahoo en euros, gardée 1 h.
QUOTE_CACHE_SECONDS = 3600
_quote_cache: dict[str, tuple[float, float | None]] = {}


def yahoo_price_eur(ticker: str) -> float | None:
    import time

    import yfinance as yf

    from .data import MINOR_CURRENCIES, _fx_rate

    key = ticker.strip().upper()
    cached = _quote_cache.get(key)
    if cached and time.monotonic() - cached[0] < QUOTE_CACHE_SECONDS:
        return cached[1]
    price = None
    try:
        t = yf.Ticker(key)
        history = t.history(period="5d", auto_adjust=False)
        closes = history["Close"].dropna() if history is not None and "Close" in history else []
        if len(closes):
            price = float(closes.iloc[-1])
            currency = (t.history_metadata or {}).get("currency") or "EUR"
            if currency in MINOR_CURRENCIES:
                currency, factor = MINOR_CURRENCIES[currency]
                price /= factor
            if currency != "EUR":
                rate = _fx_rate(currency, "EUR")
                price = price * rate if rate else None
    except Exception:
        price = None
    if price is not None and not (math.isfinite(price) and price > 0):
        price = None
    _quote_cache[key] = (time.monotonic(), price)
    return price


def fill_missing_values(lines: list[tuple], price_eur=yahoo_price_eur) -> None:
    """Lignes (HoldingLine, quantité) sans valeur (cours GOOGLEFINANCE en erreur) : valeur, plus-value et
    pourcentage recalculés sur la dernière clôture Yahoo en euros ; `quote_source` le signale à l'appli."""
    for line, quantity in lines:
        if line.value is not None or not quantity or not line.yahoo_ticker:
            continue
        price = price_eur(line.yahoo_ticker)
        if price is None:
            continue
        line.value = round(quantity * price, 2)
        line.quote_source = "Yahoo"
        if line.invested is not None:
            line.gain = round(line.value - line.invested, 2)
            line.gain_pct = line.gain / line.invested if line.invested else None
