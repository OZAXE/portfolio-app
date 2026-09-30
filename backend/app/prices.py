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
