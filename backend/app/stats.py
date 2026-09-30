"""
Performance par période, risque et contribution de chaque ligne, à partir de l'onglet Historique
(valeur de chaque jour de bourse) et des opérations datées.

Performance pondérée par le temps (TWR, celle des fonds et des indices) : chaque jour, la variation
de valeur est corrigée des flux du jour (achat = argent qui entre, vente et dividende = argent qui
sort), puis les rendements quotidiens sont enchaînés. Un apport de 1 000 € la veille d'une baisse ne
pèse donc pas plus lourd que les euros déjà placés : le résultat se compare directement à un indice.
Le TRI (returns.py) reste le bon chiffre pour « combien m'a rapporté mon argent ».

Risque (12 derniers mois) : volatilité annualisée, pire baisse depuis un sommet, ratio de Sharpe et
bêta face à l'indice choisi. Contribution d'une ligne sur une période (méthode de Dietz modifiée) :
gain en euros = valeur de fin - valeur de début - flux de la période ; en points = gain rapporté au
capital moyen engagé dans tout le portefeuille, de sorte que la somme des lignes donne le total.
"""

import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

RISK_FREE = 0.02  # taux sans risque (taux de dépôt BCE, ~2 % depuis juin 2025) pour le ratio de Sharpe
TRADING_DAYS = 252
MAX_DAILY_GAP = 5  # jours calendaires : au-delà (anciens relevés hebdomadaires), pas un rendement quotidien
MIN_DAILY_RETURNS = 40  # en dessous, volatilité et bêta ne veulent rien dire
MIN_SHARPE_DAYS = 180  # un rendement annualisé sur moins de 6 mois est trop bruité

PERIODS = (("1m", "1 mois"), ("ytd", "Depuis le 1er janv."), ("1y", "1 an"),
           ("3y", "3 ans"), ("5y", "5 ans"), ("all", "Depuis le début"))


def _years_back(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 février
        return day.replace(year=day.year - years, day=28)


def period_base(key: str, today: date) -> date | None:
    """Date de référence d'une période : la performance part du dernier relevé à cette date ou avant.
    Depuis le 1er janvier : relevé du 31 décembre (dernière clôture de l'année précédente)."""
    if key == "1m":
        month, year = (today.month - 1, today.year) if today.month > 1 else (12, today.year - 1)
        for day in (today.day, 30, 29, 28):
            try:
                return date(year, month, day)
            except ValueError:
                continue
    if key == "ytd":
        return date(today.year - 1, 12, 31)
    if key in ("1y", "3y", "5y"):
        return _years_back(today, int(key[0]))
    return None


@dataclass
class Flow:
    day: date
    amount: float  # argent qui entre dans le portefeuille (achat) ; négatif s'il en sort (vente, dividende)
    envelope: str
    ticker: str


def operation_flows(operations, envelopes: dict[str, str]) -> list[Flow]:
    """Flux vus du portefeuille. Le dividende sort : il n'est pas réinvesti dans les lignes, c'est un gain."""
    flows = []
    for op in operations:
        amount = op.net if op.kind == "Achat" else -op.net
        if amount:
            flows.append(Flow(op.day, amount, envelopes.get(op.account, "CTO"), op.ticker.upper()))
    return sorted(flows, key=lambda f: f.day)


class _Lookup:
    """Dernière valeur connue à une date (série triée) : un indice ne cote pas les jours fériés français."""

    def __init__(self, series: list[tuple[date, float]]):
        self.days = [d for d, _ in series]
        self.values = [v for _, v in series]

    def at(self, day: date) -> float | None:
        i = bisect_right(self.days, day)
        return self.values[i - 1] if i else None


def twr_index(series: list[tuple[date, float]], flows: list[Flow]) -> list[dict]:
    """Indice de performance (1 au premier relevé). Rendement du jour : (V - flux) / V de la veille - 1.
    Un relevé qui suit une valeur nulle (tout vendu, puis rachat) ne crée pas de rendement."""
    points, index, f = [], 1.0, 0
    for i, (day, value) in enumerate(series):
        inflow = 0.0
        while f < len(flows) and flows[f].day <= day:
            if i:
                inflow += flows[f].amount
            f += 1
        ret, gap = None, None
        if i and series[i - 1][1] > 0:
            prev_day, prev_value = series[i - 1]
            ret, gap = (value - inflow) / prev_value - 1, (day - prev_day).days
            index *= 1 + ret
        points.append({"date": day, "value": value, "index": index, "return": ret, "gap": gap})
    return points


def _annualize(total: float, days: int) -> float | None:
    return (1 + total) ** (365 / days) - 1 if days >= 365 and total > -1 else None


def compute_periods(points: list[dict], flows: list[Flow], today: date, bench: _Lookup | None) -> list[dict]:
    """Performance et gain en euros de chaque période. Période indisponible si l'historique commence après
    sa date de référence (pas de valeur de départ)."""
    if not points:
        return []
    by_day = _Lookup([(p["date"], i) for i, p in enumerate(points)])
    end = points[-1]
    result = []
    for key, label in PERIODS:
        base_day = period_base(key, today)
        if key == "all":
            base_i = 0
        else:
            base_i = by_day.at(base_day)
            if base_i is None or base_i == len(points) - 1:
                result.append({"key": key, "label": label, "available": False})
                continue
        base = points[base_i]
        # Gain en euros : depuis le début, tout l'argent versé compte (valeur de départ nulle)
        start_value = 0.0 if key == "all" else base["value"]
        net_flows = sum(fl.amount for fl in flows if key == "all" or base["date"] < fl.day <= end["date"])
        twr = end["index"] / base["index"] - 1
        days = (end["date"] - base["date"]).days
        row = {"key": key, "label": label, "available": True, "from": base["date"].isoformat(),
               "days": days, "twr": round(twr, 6), "annualized": _round(_annualize(twr, days)),
               "gain": round(end["value"] - start_value - net_flows, 2)}
        if bench:
            b0, b1 = bench.at(base["date"]), bench.at(end["date"])
            row["benchmark"] = round(b1 / b0 - 1, 6) if b0 and b1 else None
        result.append(row)
    return result


def _round(x: float | None, digits: int = 6) -> float | None:
    return round(x, digits) if x is not None and math.isfinite(x) else None


def _stdev(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def drawdown(series: list[tuple[date, float]]) -> dict | None:
    """Pire baisse depuis un sommet (sur un indice de performance ou de cours), et baisse actuelle."""
    if len(series) < 2:
        return None
    peak_day, peak = series[0]
    worst = {"depth": 0.0, "peak": peak_day, "trough": peak_day}
    for day, value in series:
        if value > peak:
            peak_day, peak = day, value
        depth = value / peak - 1
        if depth < worst["depth"]:
            worst = {"depth": depth, "peak": peak_day, "trough": day}
    peak_value = dict(series)[worst["peak"]]
    recovered = next((d for d, v in series if d > worst["trough"] and v >= peak_value), None)
    top = max(v for _, v in series)
    return {"max": round(worst["depth"], 6), "peak": worst["peak"].isoformat(), "trough": worst["trough"].isoformat(),
            "recovered": recovered.isoformat() if recovered else None, "current": round(series[-1][1] / top - 1, 6)}


def compute_risk(points: list[dict], today: date, bench: _Lookup | None) -> dict | None:
    """Volatilité, Sharpe et bêta sur les 12 derniers mois (ou depuis le début si plus court) ; pire baisse
    depuis le début. Seuls les écarts d'au plus 5 jours entre relevés comptent comme rendements quotidiens."""
    if len(points) < 2:
        return None
    window_start = _years_back(today, 1)
    daily = [p for p in points if p["return"] is not None and p["gap"] <= MAX_DAILY_GAP and p["date"] > window_start]
    result = {"daily_returns": len(daily), "drawdown": drawdown([(p["date"], p["index"]) for p in points])}
    if len(daily) < MIN_DAILY_RETURNS:
        return result | {"volatility": None, "sharpe": None, "beta": None}
    volatility = _stdev([p["return"] for p in daily]) * math.sqrt(TRADING_DAYS)
    base = next((p for p in reversed(points) if p["date"] <= window_start), points[0])
    span = (points[-1]["date"] - base["date"]).days
    annual = (points[-1]["index"] / base["index"]) ** (365 / span) - 1 if span >= MIN_SHARPE_DAYS else None
    result |= {"from": base["date"].isoformat(), "volatility": _round(volatility),
               "sharpe": _round((annual - RISK_FREE) / volatility, 3) if annual is not None and volatility else None,
               "beta": None}
    if bench:
        pairs = []
        for p in daily:
            prev_day = p["date"] - timedelta(days=p["gap"])
            b0, b1 = bench.at(prev_day), bench.at(p["date"])
            if b0 and b1:
                pairs.append((p["return"], b1 / b0 - 1))
        if len(pairs) >= MIN_DAILY_RETURNS:
            mp = sum(a for a, _ in pairs) / len(pairs)
            mb = sum(b for _, b in pairs) / len(pairs)
            var_b = sum((b - mb) ** 2 for _, b in pairs)
            if var_b:
                result["beta"] = round(sum((a - mp) * (b - mb) for a, b in pairs) / var_b, 3)
            result["benchmark_volatility"] = _round(_stdev([b for _, b in pairs]) * math.sqrt(TRADING_DAYS))
        first, last = points[0]["date"], points[-1]["date"]
        bench_series = [(d, v) for d, v in zip(bench.days, bench.values) if first <= d <= last]
        result["benchmark_drawdown"] = drawdown(bench_series)
    return result


def compute_attribution(operations, envelopes: dict[str, str], current: dict[tuple[str, str], float],
                        closes: dict[str, _Lookup], base_day: date | None, today: date,
                        names: dict[str, str]) -> dict:
    """Gain de chaque ligne (enveloppe, titre) sur la période qui suit base_day (None : depuis le début).
    current : valeur actuelle de chaque ligne ; closes : cours de clôture en euros de chaque titre."""
    quantities: dict[tuple[str, str], float] = defaultdict(float)
    lines: dict[tuple[str, str], dict] = defaultdict(lambda: {"start": 0.0, "flows": 0.0, "weighted": 0.0})
    missing = set()
    first_day = min((op.day for op in operations), default=today)
    start = base_day or first_day
    span = max((today - start).days, 1)
    for op in sorted(operations, key=lambda o: o.day):
        key = (envelopes.get(op.account, "CTO"), op.ticker.upper())
        if base_day is not None and op.day <= base_day:
            if op.kind in ("Achat", "Vente"):
                quantities[key] += op.quantity if op.kind == "Achat" else -op.quantity
            continue
        amount = op.net if op.kind == "Achat" else -op.net
        line = lines[key]
        line["flows"] += amount
        # Poids de Dietz : un flux compte au prorata du temps qu'il reste investi sur la période
        line["weighted"] += amount * max((today - op.day).days, 0) / span
    for key, quantity in quantities.items():
        if quantity > 1e-9:
            price = closes.get(key[1]).at(base_day) if key[1] in closes else None
            if price is None:
                missing.add(key[1])
            else:
                lines[key]["start"] = quantity * price
    for key in current:
        lines[key]  # ligne détenue sans opération sur la période : son gain est sa variation de valeur
    capital = sum(line["start"] + line["weighted"] for line in lines.values())
    rows = []
    for (envelope, ticker), line in lines.items():
        gain = current.get((envelope, ticker), 0.0) - line["start"] - line["flows"]
        if abs(gain) < 0.005:
            continue
        rows.append({"ticker": ticker, "name": names.get(ticker) or ticker, "envelope": envelope,
                     "start": round(line["start"], 2), "end": round(current.get((envelope, ticker), 0.0), 2),
                     "gain": round(gain, 2), "points": _round(gain / capital) if capital > 0 else None})
    rows.sort(key=lambda r: r["gain"], reverse=True)
    return {"from": start.isoformat(), "lines": rows, "missing": sorted(missing),
            "capital": round(capital, 2), "total": round(sum(r["gain"] for r in rows), 2)}


def portfolio_stats(history, operations, envelopes: dict[str, str], holdings, names: dict[str, str],
                    today: date, closes: dict[str, _Lookup] | None, bench: _Lookup | None) -> dict:
    """history : relevés de l'onglet Historique ; holdings : lignes actuelles de l'onglet Positions (valeur
    en euros), qui donnent le point « en direct » du jour quand tous les cours sont lisibles."""
    flows = operation_flows(operations, envelopes)
    current = defaultdict(float)
    live_ok = True
    for h in holdings:
        envelope = str(h.envelope or "").upper()
        if envelope not in ("PEA", "CTO"):
            continue
        if h.value is None:
            live_ok = False
        else:
            current[(envelope, (h.yahoo_ticker or h.ticker).upper())] += h.value

    result = {"as_of": today.isoformat(), "risk_free": RISK_FREE, "envelopes": {}}
    for envelope in ("Total", "PEA", "CTO"):
        field = {"Total": "total_value", "PEA": "pea_value", "CTO": "cto_value"}[envelope]
        series = [(date.fromisoformat(p.date), float(getattr(p, field))) for p in history
                  if getattr(p, field) is not None and p.date < today.isoformat()]
        live = sum(v for (e, _), v in current.items() if envelope in ("Total", e))
        if live_ok and current and (not series or series[-1][0] < today):
            series.append((today, live))
        env_flows = [f for f in flows if envelope in ("Total", f.envelope)]
        # On ne garde l'historique qu'à partir du premier relevé non nul (avant : enveloppe pas encore ouverte)
        while series and series[0][1] <= 0:
            series.pop(0)
        if len(series) < 2:
            continue
        points = twr_index(series, [f for f in env_flows if f.day > series[0][0]] if series else [])
        result["envelopes"][envelope] = {"periods": compute_periods(points, env_flows, today, bench),
                                         "risk": compute_risk(points, today, bench)}

    result["attribution"] = {}
    for key, label in PERIODS:
        base_day = period_base(key, today)
        if base_day is not None and closes is None:
            continue
        if base_day is not None and not any(op.day <= base_day for op in operations):
            continue  # portefeuille pas encore ouvert à cette date
        attribution = compute_attribution(operations, envelopes, current, closes or {}, base_day, today, names)
        result["attribution"][key] = attribution | {"label": label}
    return result


def stats_summary(sheet_id: str, benchmark: str, today: date | None = None) -> dict | None:
    """None pour un Sheet à l'ancien format. Sans réponse de Yahoo, les périodes et le risque restent
    calculés (onglet Historique), sans indice ni contribution sur les périodes qui ont un point de départ."""
    from .performance import BENCHMARKS, download_closes, eur_closes
    from .realized import read_ledger
    from .sheets import _open_sheet, get_overview, is_v2

    if not is_v2(_open_sheet(sheet_id)):
        return None
    today = today or date.today()
    ledger = read_ledger(sheet_id)
    overview = get_overview(sheet_id)
    operations = [op for op in ledger.operations if op.kind in ("Achat", "Vente", "Dividende")]
    first = min((op.day for op in operations), default=today) - timedelta(days=10)
    closes = bench = None
    try:
        # Cours bruts (comme l'onglet Positions ce jour-là) des titres détenus à une date de départ
        tickers = sorted({op.ticker.upper() for op in operations if op.kind in ("Achat", "Vente")})
        start = max(first, _years_back(today, 5) - timedelta(days=10))
        frame = eur_closes(tickers, {t.upper(): c for t, c in ledger.currencies.items()}, start.isoformat())
        closes = {t: _Lookup([(d.date(), float(v)) for d, v in frame[t].dropna().items()]) for t in frame.columns}
    except Exception:
        pass
    try:
        ticker, _ = BENCHMARKS[benchmark]
        series = download_closes([ticker], first.isoformat())[ticker].dropna()
        series.index = series.index.tz_localize(None) if getattr(series.index, "tz", None) else series.index
        bench = _Lookup([(d.date(), float(v)) for d, v in series.items()]) if len(series) else None
    except Exception:
        pass
    names = {t.upper(): n for t, n in ledger.names.items()}
    result = portfolio_stats(overview.history, operations, ledger.envelopes, overview.holdings, names,
                             today, closes, bench)
    return result | {"benchmark": BENCHMARKS[benchmark][1] if bench else None}
