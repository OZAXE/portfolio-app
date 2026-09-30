"""
Variation du jour et effet de change des positions (octobre 2026, demande d'Enzo).

Variation du jour : ce que chaque ligne a gagné ou perdu depuis la clôture précédente, en euros, change
compris. Yahoo donne la variation en pourcentage (deux dernières clôtures quotidiennes du titre, et du taux de
change pour une action cotée en devise) ; la valeur de la ligne vient de l'onglet Positions (GOOGLEFINANCE).
Une ligne achetée ou renforcée pendant la séance ne compte que ce qu'elle a gagné depuis l'achat, une vente
de la séance compte ce qu'elle a rapporté de plus que la clôture précédente. Une ligne entièrement vendue
pendant la séance n'est plus dans l'onglet Positions : elle n'est pas comptée.

Effet de change : part de la plus-value latente d'une ligne cotée en devise qui vient du taux de change.
Taux moyen payé = coût en euros / coût en devise, chaque achat converti au taux Yahoo de son jour (les imports
Trade Republic sont en euros, sans le taux). Effet = valeur x (1 - taux payé / taux actuel). Apple acheté
2 000 € quand 1 $ valait 0,92 € (2 174 $), qui vaut 1 978 € à 0,86 € (2 300 $) : au taux d'achat, la ligne
vaudrait 2 116 € ; le change lui a fait perdre 138 €, l'action a rapporté le reste. Un ETF coté en euros qui
détient des actions américaines n'en a pas : seule la devise de cotation compte.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .realized import Operation


@dataclass
class Quote:
    day: date  # séance de la dernière clôture
    change: float  # dernière clôture / clôture précédente - 1


def quote_change(closes: pd.Series) -> Quote | None:
    """Variation entre les deux dernières clôtures connues (Yahoo : la séance en cours compte comme la
    dernière, à son dernier cours). Cours nuls ou vides ignorés."""
    closes = closes.dropna()
    closes = closes[closes > 0]
    if len(closes) < 2:
        return None
    return Quote(pd.Timestamp(closes.index[-1]).date(), float(closes.iloc[-1] / closes.iloc[-2] - 1))


def line_day_change(value: float | None, quantity: float | None, change: float | None, bought_qty: float = 0.0,
                    bought_net: float = 0.0, sold_qty: float = 0.0, sold_net: float = 0.0) -> float | None:
    """Gain de la ligne depuis la clôture précédente. change : variation du cours en euros (titre et change).
    10 actions valant 1 000 € après +2 % : cours de la veille 98,04 €, gain 19,61 €. Si 5 ont été achetées
    496 € dans la séance : 1 000 - 5 x 98,04 - 496 = 13,80 €."""
    if not quantity or value is None or change is None:
        return None
    previous_price = value / quantity / (1 + change)
    held_before = max(quantity - bought_qty + sold_qty, 0.0)
    return value - held_before * previous_price - bought_net + sold_net


def currency_effect(operations: list[Operation], rate_at, value: float, rate_now: float) -> dict | None:
    """operations : achats et ventes de la ligne ; rate_at(jour) : 1 unité de devise en euros ce jour-là.
    Les ventes retirent leur part du coût en euros et en devise, comme pour le PRU."""
    quantity = cost_eur = cost_local = 0.0
    for op in sorted(operations, key=lambda o: (o.day, o.kind == "Vente")):
        if op.kind == "Achat":
            rate = rate_at(op.day)
            if not rate:
                return None
            quantity += op.quantity
            cost_eur += op.net
            cost_local += op.net / rate
        elif op.kind == "Vente" and quantity > 0:
            sold = min(op.quantity, quantity)
            cost_eur -= cost_eur * sold / quantity
            cost_local -= cost_local * sold / quantity
            quantity -= sold
    if quantity <= 1e-9 or cost_local <= 0 or not rate_now:
        return None
    rate_paid = cost_eur / cost_local
    return {"effect": value * (1 - rate_paid / rate_now), "rate_paid": rate_paid, "rate_now": rate_now}


class RateHistory:
    """Taux de change quotidiens : dernier taux connu à une date (week-end, jour férié)."""

    def __init__(self, series: pd.Series):
        series = series.dropna()
        series = series[series > 0]
        self.days = [pd.Timestamp(d).date() for d in series.index]
        self.values = [float(v) for v in series]

    def at(self, day: date) -> float | None:
        i = bisect_right(self.days, day)
        return self.values[i - 1] if i else (self.values[0] if self.values else None)

    @property
    def last(self) -> float | None:
        return self.values[-1] if self.values else None


def base_currency(currency: str | None) -> str:
    """Devise du taux de change : les pence de Londres (GBp) suivent la livre."""
    currency = str(currency or "EUR").strip()
    return "GBP" if currency == "GBp" else currency.upper()


def daily_summary(holdings, operations: list[Operation], envelopes: dict[str, str], quotes: dict[str, Quote],
                  fx_quotes: dict[str, Quote], fx_history: dict[str, RateHistory]) -> dict:
    """holdings : lignes de l'onglet Positions (valeur, quantité, devise) ; operations : quantités sur la base
    d'aujourd'hui (Ledger.operations) ; quotes / fx_quotes : variation du titre et du taux de change."""
    by_line: dict[tuple[str, str], list[Operation]] = {}
    for op in operations:
        if op.kind in ("Achat", "Vente"):
            by_line.setdefault((str(envelopes.get(op.account, "CTO")).upper(), op.ticker.upper()), []).append(op)

    lines, fx_lines, missing = {}, {}, []
    total = base = 0.0
    fx_total, fx_by_currency, sessions = 0.0, {}, []
    for h in holdings:
        ticker = str(h.yahoo_ticker or h.ticker).upper()
        envelope = str(h.envelope or "").upper()
        key = f"{envelope}|{ticker}"
        ops = by_line.get((envelope, ticker), [])
        currency = base_currency(h.currency)
        quote = quotes.get(ticker)
        fx_quote = fx_quotes.get(currency) if currency != "EUR" else None
        if quote is None or h.value is None:
            missing.append(ticker)
        else:
            fx_change = fx_quote.change if fx_quote else 0.0
            change = (1 + quote.change) * (1 + fx_change) - 1
            today = [op for op in ops if op.day >= quote.day]
            amount = line_day_change(
                h.value, h.quantity, change,
                sum(op.quantity for op in today if op.kind == "Achat"), sum(op.net for op in today if op.kind == "Achat"),
                sum(op.quantity for op in today if op.kind == "Vente"), sum(op.net for op in today if op.kind == "Vente"))
            if amount is not None:
                start = h.value - amount
                lines[key] = {"change": round(amount, 2), "pct": amount / start if start > 0 else None,
                              "stock_pct": quote.change, "fx_pct": fx_quote.change if fx_quote else None,
                              "session": quote.day.isoformat()}
                total += amount
                base += start
                sessions.append(quote.day)
            else:
                missing.append(ticker)
        history = fx_history.get(currency) if currency != "EUR" else None
        if history is not None and h.value:
            split = currency_effect(ops, history.at, h.value, history.last)
            if split is not None:
                gain = h.gain if h.gain is not None else (h.value - h.invested if h.invested is not None else None)
                fx_lines[key] = {"currency": currency, "effect": round(split["effect"], 2),
                                 "stock_effect": round(gain - split["effect"], 2) if gain is not None else None,
                                 "rate_paid": round(split["rate_paid"], 6), "rate_now": round(split["rate_now"], 6)}
                fx_total += split["effect"]
                entry = fx_by_currency.setdefault(currency, {"currency": currency, "effect": 0.0, "value": 0.0})
                entry["effect"] += split["effect"]
                entry["value"] += h.value
    by_currency = sorted(({**e, "effect": round(e["effect"], 2), "value": round(e["value"], 2)} for e in fx_by_currency.values()),
                         key=lambda e: -e["value"])
    return {
        "session": max(sessions).isoformat() if sessions else None,
        "total": {"change": round(total, 2), "pct": total / base if base > 0 else None, "lines": len(lines),
                  "missing": sorted(set(missing))},
        "lines": lines,
        "currency": {"total": round(fx_total, 2), "by_currency": by_currency, "lines": fx_lines},
    }


def portfolio_daily(sheet_id: str, today: date | None = None) -> dict:
    """Variation du jour et effet de change du portefeuille : deux téléchargements Yahoo (cours des titres
    sur 10 jours, taux de change depuis le premier achat en devise)."""
    from .performance import download_closes
    from .realized import read_ledger
    from .sheets import get_overview

    today = today or date.today()
    ledger = read_ledger(sheet_id)
    holdings = [h for h in get_overview(sheet_id).holdings if h.quantity]
    tickers = sorted({str(h.yahoo_ticker or h.ticker).upper() for h in holdings})
    quotes = {}
    if tickers:
        closes = download_closes(tickers, (today - timedelta(days=10)).isoformat(), adjusted=False)
        quotes = {t: q for t in closes.columns if (q := quote_change(closes[t])) is not None}
    currencies = sorted({base_currency(h.currency) for h in holdings} - {"EUR"})
    fx_quotes, fx_history = {}, {}
    if currencies:
        foreign = {str(h.yahoo_ticker or h.ticker).upper() for h in holdings if base_currency(h.currency) != "EUR"}
        first = min((op.day for op in ledger.operations if op.ticker.upper() in foreign), default=today)
        rates = download_closes([f"{c}EUR=X" for c in currencies], (first - timedelta(days=10)).isoformat())
        for c in currencies:
            series = rates.get(f"{c}EUR=X")
            if series is None:
                continue
            if (q := quote_change(series)) is not None:
                fx_quotes[c] = q
            history = RateHistory(series)
            if history.values:
                fx_history[c] = history
    return daily_summary(holdings, ledger.operations, ledger.envelopes, quotes, fx_quotes, fx_history)
