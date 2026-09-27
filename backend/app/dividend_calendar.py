"""
Dividendes à venir et revenus projetés sur les 12 prochains mois.

Yahoo ne donne pas de calendrier fiable depuis le serveur (quoteSummary souvent bloqué),
mais l'historique des versements passe toujours (API chart). La projection répète donc
chaque dividende des 12 derniers mois un an plus tard, au même montant, avec la quantité
détenue aujourd'hui : c'est l'hypothèse « l'an prochain comme l'an dernier », sans hausse.

Les dates sont des dates de détachement (ex-dividende) : il faut détenir l'action la veille
pour toucher le dividende, versé en général quelques jours à quelques semaines plus tard.

Net estimé : rien n'est prélevé dans le PEA tant qu'on n'en retire rien ; sur le CTO, flat tax
de l'année (la retenue à la source étrangère, 15 % aux États-Unis, est imputée dessus).
"""

from collections import defaultdict
from datetime import date, timedelta

from .realized import flat_tax_rate, read_operations
from .sheets import UNFORMATTED, _open_sheet, _worksheet, is_v2

MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}
FREQUENCIES = {1: "annuel", 2: "semestriel", 3: "trimestriel", 4: "trimestriel", 12: "mensuel"}


def _next_year(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 février
        return day.replace(year=day.year + 1, day=28)


def project_events(history: list[tuple[date, float]], today: date) -> list[tuple[date, float]]:
    """Versements des 365 derniers jours, décalés d'un an : tous tombent dans les 12 prochains mois."""
    start = today - timedelta(days=365)
    return sorted((_next_year(d), amount) for d, amount in history if start < d <= today and amount > 0)


def frequency_label(count: int) -> str:
    return FREQUENCIES.get(count, f"{count} fois par an")


def compute_calendar(holdings: list[dict], histories: dict[str, list[tuple[date, float]]],
                     eur_rates: dict[str, float | None], today: date) -> dict:
    """holdings : {ticker, name, envelope, quantity} ; histories : versements par action, en devise
    de cotation (unité principale) ; eur_rates : conversion de cette devise en euros."""
    events, missing = [], []
    for h in holdings:
        rate = eur_rates.get(h["ticker"])
        projected = project_events(histories.get(h["ticker"], []), today)
        if projected and rate is None:
            missing.append(h["ticker"])
            continue
        for day, per_share in projected:
            gross = per_share * h["quantity"] * rate
            tax = flat_tax_rate(day.year) if h["envelope"] == "CTO" else 0.0
            events.append({
                "date": day.isoformat(), "ticker": h["ticker"], "name": h["name"], "envelope": h["envelope"],
                "per_share": round(per_share, 4), "quantity": h["quantity"],
                "gross": round(gross, 2), "net": round(gross * (1 - tax), 2),
                "frequency": frequency_label(len(projected)),
            })
    events.sort(key=lambda e: (e["date"], e["name"]))

    # Du mois en cours au même mois l'an prochain (13 mois : les deux bouts sont partiels)
    month_keys = []
    year, month = today.year, today.month
    for _ in range(13):
        month_keys.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    by_month = defaultdict(lambda: [0.0, 0.0])
    by_envelope = defaultdict(lambda: {"gross": 0.0, "net": 0.0})
    for e in events:
        by_month[e["date"][:7]][0] += e["gross"]
        by_month[e["date"][:7]][1] += e["net"]
        by_envelope[e["envelope"]]["gross"] += e["gross"]
        by_envelope[e["envelope"]]["net"] += e["net"]
    months = [{"month": key, "gross": round(by_month[key][0], 2), "net": round(by_month[key][1], 2)} for key in month_keys]

    gross = sum(e["gross"] for e in events)
    return {
        "events": events,
        "months": months,
        "annual_gross": round(gross, 2),
        "annual_net": round(sum(e["net"] for e in events), 2),
        "envelopes": {k: {"gross": round(v["gross"], 2), "net": round(v["net"], 2)} for k, v in sorted(by_envelope.items())},
        "missing": missing,
    }


def _history(ticker: str, divisor: float) -> list[tuple[date, float]]:
    import yfinance as yf

    try:
        series = yf.Ticker(ticker).dividends
    except Exception:
        return []
    if series is None or series.empty:
        return []
    return [(ts.date(), float(v) / divisor) for ts, v in series.items()]


def dividend_calendar(sheet_id: str) -> dict | None:
    """None pour un Sheet à l'ancien format (sans onglet Opérations)."""
    from .data import _fx_rate

    sheet = _open_sheet(sheet_id)
    if not is_v2(sheet):
        return None
    operations, envelopes, names = read_operations(sheet_id)
    currencies = {}
    for row in _worksheet(sheet, "Titres").get_values(value_render_option=UNFORMATTED)[1:]:
        if len(row) > 5 and row[0]:
            currencies[str(row[0]).strip().upper()] = str(row[5] or "EUR").strip()

    quantities: dict[tuple[str, str], float] = defaultdict(float)
    for op in operations:
        if op.kind in ("Achat", "Vente"):
            sign = 1 if op.kind == "Achat" else -1
            quantities[(envelopes.get(op.account, "Autre"), op.ticker)] += sign * op.quantity
    holdings = [{"ticker": t, "name": names.get(t, t), "envelope": env, "quantity": q}
                for (env, t), q in sorted(quantities.items()) if q > 1e-9]

    histories, eur_rates, fx_cache = {}, {}, {"EUR": 1.0}
    for ticker in sorted({h["ticker"] for h in holdings}):
        currency, divisor = MINOR_UNITS.get(currencies.get(ticker, "EUR"), (currencies.get(ticker, "EUR"), 1))
        histories[ticker] = _history(ticker, divisor)
        if currency not in fx_cache:
            fx_cache[currency] = _fx_rate(currency, "EUR")
        eur_rates[ticker] = fx_cache[currency]
    return compute_calendar(holdings, histories, eur_rates, date.today())
