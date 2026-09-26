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

from .sheets import UNFORMATTED, _open_sheet, _serial_to_iso, _worksheet

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
    """Achats et ventes de l'onglet Opérations, et devise de cotation de chaque titre (onglet Titres)."""
    sheet = _open_sheet(sheet_id)
    trades = []
    for row in _worksheet(sheet, "Opérations").get_values(value_render_option=UNFORMATTED)[1:]:
        row = (row + [""] * 12)[:12]
        iso = _serial_to_iso(row[0])
        if not iso or row[2] not in ("Achat", "Vente") or not isinstance(row[4], (int, float)):
            continue
        sign = 1 if row[2] == "Achat" else -1
        cash = row[11] if isinstance(row[11], (int, float)) else row[4] * (row[5] or 0) * (row[7] or 1)
        trades.append(Trade(date.fromisoformat(iso), str(row[3]).strip().upper(), sign * row[4], sign * cash))
    currencies = {}
    for row in _worksheet(sheet, "Titres").get_values(value_render_option=UNFORMATTED)[1:]:
        if len(row) > 5 and row[0]:
            currencies[str(row[0]).strip().upper()] = str(row[5] or "EUR")
    return sorted(trades, key=lambda t: t.day), currencies


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


def download_closes(tickers: list[str], start: str) -> pd.DataFrame:
    """Cours de clôture ajustés, une colonne par ticker (colonnes vides pour un ticker inconnu)."""
    import yfinance as yf

    raw = yf.download(tickers, start=start, progress=False, auto_adjust=True, group_by="ticker")
    closes = {}
    for ticker in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            present = ticker in raw.columns.get_level_values(0)
            closes[ticker] = raw[ticker]["Close"] if present else pd.Series(dtype=float)
        else:
            closes[ticker] = raw["Close"]
    return pd.DataFrame(closes)


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
