"""
Performance du portefeuille comparée à un indice, reconstituée jour par jour à partir
des opérations datées (onglet Opérations) et des cours historiques Yahoo.

Le "portefeuille fantôme" investit chaque euro au même moment dans l'ETF de référence
(et revend le même montant lors d'une vente) : la comparaison mesure donc la qualité
des choix de titres, à flux d'argent identiques.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .realized import read_ledger

BENCHMARKS = {
    "cac40": ("^FCHI", "CAC 40"),
    "world": ("CW8.PA", "MSCI World (ETF Amundi CW8)"),
    "sp500": ("ESE.PA", "S&P 500 (ETF BNP Paribas Easy)"),
}


@dataclass
class Trade:
    day: date
    ticker: str
    quantity: float  # négatif pour une vente
    cash_eur: float  # argent investi (positif à l'achat, négatif à la vente), frais compris


def read_trades(sheet_id: str) -> tuple[list[Trade], dict[str, str]]:
    """Achats et ventes de l'onglet Opérations (montant net, frais compris), et devise de cotation
    de chaque titre (onglet Titres)."""
    ledger = read_ledger(sheet_id)
    trades = [Trade(op.day, op.ticker, op.quantity if op.kind == "Achat" else -op.quantity,
                    op.net if op.kind == "Achat" else -op.net)
              for op in ledger.operations if op.kind in ("Achat", "Vente")]
    return sorted(trades, key=lambda t: t.day), dict(ledger.currencies)


def _eur_prices(closes: pd.DataFrame, fx: pd.DataFrame, currencies: dict[str, str]) -> pd.DataFrame:
    """Cours de clôture convertis en euros (pence de Londres ramenés en livres)."""
    converted = {}
    for ticker in closes.columns:
        currency = currencies.get(ticker, "EUR")
        series = closes[ticker]
        if currency == "GBp":
            series, currency = series / 100, "GBP"
        if currency != "EUR":
            series = series * fx[currency]
        converted[ticker] = series
    return pd.DataFrame(converted)


def compute_performance(trades: list[Trade], prices_eur: pd.DataFrame, benchmark_eur: pd.Series) -> list[dict]:
    """Valeur du portefeuille, montant investi et valeur du portefeuille fantôme, jour par jour.
    prices_eur et benchmark_eur sont indexés par jour de bourse, cours déjà en euros."""
    days = prices_eur.index
    prices = prices_eur.ffill()
    bench = benchmark_eur.reindex(days).ffill()
    holdings: dict[str, float] = {}
    invested = bench_units = 0.0
    pending = list(trades)
    points = []
    for day in days:
        # Une opération d'un jour sans cotation (week-end) est prise en compte au jour de bourse suivant
        while pending and pd.Timestamp(pending[0].day) <= day:
            trade = pending.pop(0)
            holdings[trade.ticker] = holdings.get(trade.ticker, 0.0) + trade.quantity
            invested += trade.cash_eur
            if bench[day] and not pd.isna(bench[day]):
                bench_units += trade.cash_eur / bench[day]
        if not holdings:
            continue
        value = sum(q * prices.at[day, t] for t, q in holdings.items() if t in prices.columns and not pd.isna(prices.at[day, t]))
        points.append({  # float() : les types numpy ne passent pas en JSON
            "date": day.date().isoformat(),
            "value": round(float(value), 2),
            "invested": round(float(invested), 2),
            "benchmark": round(float(bench_units * bench[day]), 2) if not pd.isna(bench[day]) else None,
        })
    return points


def download_closes(tickers: list[str], start: str, adjusted: bool = True) -> pd.DataFrame:
    """Cours de clôture, une colonne par ticker (colonnes vides pour un ticker inconnu). Ajustés des
    dividendes par défaut (comparaison à un indice, dividendes réinvestis) ; bruts avec adjusted=False
    (valeur d'une position un jour donné, comme la voyait l'onglet Positions)."""
    import yfinance as yf

    raw = yf.download(tickers, start=start, progress=False, auto_adjust=adjusted, group_by="ticker")
    closes = {}
    for ticker in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            present = ticker in raw.columns.get_level_values(0)
            closes[ticker] = raw[ticker]["Close"] if present else pd.Series(dtype=float)
        else:
            closes[ticker] = raw["Close"]
    return pd.DataFrame(closes)


def unsplit(closes: pd.Series, splits: pd.Series) -> pd.Series:
    """Yahoo divise tous les cours passés lors d'une division d'action ou d'une attribution d'actions
    gratuites (Air Liquide : 1,1 pour 1). On remet le cours réel de chaque jour, celui qui s'appliquait
    à la quantité détenue ce jour-là."""
    factor = pd.Series(1.0, index=closes.index)
    for when, ratio in splits.items():
        when = pd.Timestamp(when)
        when = (when.tz_localize(None) if when.tzinfo else when).normalize()
        if ratio and ratio > 0:
            factor[closes.index < when] *= float(ratio)
    return closes * factor


def _splits(ticker: str) -> pd.Series:
    import yfinance as yf

    try:
        return yf.Ticker(ticker).splits
    except Exception:
        return pd.Series(dtype=float)


def eur_closes(tickers: list[str], currencies: dict[str, str], start: str) -> pd.DataFrame:
    """Cours de clôture réels en euros depuis `start` (sans ajustement des dividendes ni des divisions),
    une colonne par ticker (pence de Londres compris)."""
    closes = download_closes(tickers, start, adjusted=False).dropna(how="all")
    closes.index = pd.to_datetime(closes.index).tz_localize(None) if getattr(closes.index, "tz", None) else pd.to_datetime(closes.index)
    for ticker in closes.columns:
        splits = _splits(ticker)
        if len(splits):
            closes[ticker] = unsplit(closes[ticker], splits)
    needed_fx = sorted({("GBP" if c == "GBp" else c) for t, c in currencies.items() if t in tickers} - {"EUR"})
    fx = pd.DataFrame(index=closes.index)
    if needed_fx:
        fx = download_closes([f"{c}EUR=X" for c in needed_fx], start)
        fx.columns = needed_fx
        fx = fx.reindex(closes.index).ffill().bfill()
    return _eur_prices(closes, fx, currencies)


def portfolio_performance(sheet_id: str, benchmark: str) -> dict:
    if benchmark not in BENCHMARKS:
        raise ValueError(f"Indice inconnu (choix : {', '.join(BENCHMARKS)})")
    trades, currencies = read_trades(sheet_id)
    if not trades:
        return {"points": [], "benchmark": BENCHMARKS[benchmark][1]}
    bench_ticker, bench_label = BENCHMARKS[benchmark]
    tickers = sorted({t.ticker for t in trades})
    start = min(t.day for t in trades).isoformat()

    downloaded = download_closes(tickers + [bench_ticker], start)
    closes = downloaded[tickers].dropna(how="all")
    needed_fx = sorted({("GBP" if c == "GBp" else c) for t, c in currencies.items() if t in tickers} - {"EUR"})
    fx = pd.DataFrame(index=closes.index)
    if needed_fx:
        fx = download_closes([f"{c}EUR=X" for c in needed_fx], start)
        fx.columns = needed_fx
        fx = fx.reindex(closes.index).ffill().bfill()
    prices_eur = _eur_prices(closes, fx, currencies)
    points = compute_performance(trades, prices_eur, downloaded[bench_ticker])

    last = points[-1] if points else None
    summary = None
    if last and last["invested"]:
        summary = {
            "portfolio_pct": last["value"] / last["invested"] - 1,
            "benchmark_pct": (last["benchmark"] / last["invested"] - 1) if last["benchmark"] else None,
        }
    return {"benchmark": bench_label, "points": points, "summary": summary}


def chart_points(trades: list[dict], closes_eur: pd.Series) -> dict:
    """Cours en euros jour par jour, points d'achat et de vente, et PRU après chaque opération.
    trades : {date (ISO), type, quantity, price (euros par action, frais exclus), cost (net payé ou encaissé)}."""
    series = closes_eur.dropna()
    quantity = cost = 0.0
    pru = []
    for t in sorted(trades, key=lambda t: t["date"]):
        if t["type"] == "Achat":
            quantity += t["quantity"]
            cost += t["cost"]
        elif t["type"] == "Vente" and quantity > 0:
            sold = min(t["quantity"], quantity)
            cost -= cost / quantity * sold  # le PRU des titres restants ne bouge pas
            quantity -= sold
        pru.append({"date": t["date"], "pru": round(cost / quantity, 4) if quantity > 1e-9 else None})
    return {
        "points": [[d.date().isoformat(), round(float(v), 4)] for d, v in series.items()],
        "trades": sorted(trades, key=lambda t: t["date"]),
        "pru": pru,
    }


def position_chart(sheet_id: str, ticker: str) -> dict:
    """Graphique d'une ligne : cours depuis un mois avant le premier achat, en euros (comme les prix
    d'achat de l'onglet Opérations, frais exclus), avec chaque achat, vente et le PRU."""
    from datetime import timedelta

    from .realized import read_operations

    operations, _, _ = read_operations(sheet_id)
    ticker = ticker.upper()
    ops = [op for op in operations if op.ticker == ticker and op.kind in ("Achat", "Vente") and op.quantity]
    if not ops:
        raise ValueError(f"Aucun achat de {ticker} dans l'onglet Opérations")
    _, currencies = read_trades(sheet_id)
    start = (min(op.day for op in ops) - timedelta(days=30)).isoformat()
    closes = download_closes([ticker], start)[[ticker]].dropna(how="all")
    currency = currencies.get(ticker, "EUR")
    fx = pd.DataFrame(index=closes.index)
    base = "GBP" if currency == "GBp" else currency
    if base != "EUR":
        fx = download_closes([f"{base}EUR=X"], start)
        fx.columns = [base]
        fx = fx.reindex(closes.index).ffill().bfill()
    closes_eur = _eur_prices(closes, fx, {ticker: currency})[ticker]
    trades = [{"date": op.day.isoformat(), "type": op.kind, "quantity": op.quantity, "account": op.account,
               "price": round(op.gross / op.quantity, 4), "cost": round(op.net, 2)} for op in ops]
    return {"ticker": ticker, "currency": "EUR", **chart_points(trades, closes_eur)}
