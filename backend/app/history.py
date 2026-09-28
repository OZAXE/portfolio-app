"""
Relevé quotidien de l'onglet Historique et plus-value de la semaine.

Le job nocturne (screener/snapshot.py) appelle POST /history/snapshot après chaque jour de bourse :
pour chaque utilisateur, une ligne est ajoutée à son onglet Historique (date, valeur et montant
investi du PEA et du CTO, lus dans l'onglet Positions déjà calculé par les formules du Sheet).
Remplace l'ancien relevé hebdomadaire par Apps Script.

La plus-value de la semaine retire les apports : c'est la variation de (valeur - investi)
entre le relevé du vendredi précédent et celui du jour.

Reconstitution (rebuild_history) : après un import ou la saisie d'une opération passée, l'historique
est recalculé jour de bourse par jour de bourse à partir des opérations et des cours de clôture Yahoo
en euros, comme le ferait l'onglet Positions ce jour-là (valeur = quantité x cours ; investi =
quantité x PRU frais compris). Les relevés en dehors de la période recalculée sont gardés.
"""

from datetime import date, timedelta

import pandas as pd

from .sheets import SHEETS_EPOCH, UNFORMATTED, HistoryPoint, _open_sheet, _worksheet, is_v2
from .sheets import parse_history_v2, parse_positions_v2

ENVELOPES = ("PEA", "CTO")


class SnapshotError(ValueError):
    """Relevé impossible (cours en erreur dans le Sheet) : mieux vaut aucun relevé qu'un relevé faux."""


def snapshot_totals(positions_rows: list[list]) -> dict[str, dict[str, float]]:
    """Valeur et montant investi par enveloppe, à partir des lignes de l'onglet Positions."""
    totals = {e: {"value": 0.0, "invested": 0.0} for e in ENVELOPES}
    for line, _ in parse_positions_v2(positions_rows):
        envelope = str(line.envelope or "").strip().upper()
        if envelope not in totals:
            continue
        if line.value is None or line.invested is None:
            raise SnapshotError(f"valeur illisible pour {line.ticker} (cours GOOGLEFINANCE en erreur ?)")
        totals[envelope]["value"] += line.value
        totals[envelope]["invested"] += line.invested
    return totals


def history_row(day: date, totals: dict, row_number: int) -> list:
    """Ligne de l'onglet Historique : la date en numéro de série (affichée par le format de la colonne),
    totaux et performance en formules comme dans le modèle."""
    n = row_number
    return [(day - SHEETS_EPOCH).days,
            round(totals["PEA"]["value"], 2), round(totals["PEA"]["invested"], 2),
            round(totals["CTO"]["value"], 2), round(totals["CTO"]["invested"], 2),
            f"=B{n}+D{n}", f"=C{n}+E{n}", f"=F{n}/G{n}-1"]


def point_from_totals(day: date, totals: dict) -> HistoryPoint:
    pea, cto = totals["PEA"], totals["CTO"]
    return parse_history_v2([[], [(day - SHEETS_EPOCH).days, pea["value"], pea["invested"], cto["value"], cto["invested"]]])[0]


def weekly_gain(points: list[HistoryPoint], end: date) -> dict | None:
    """Plus-value de la semaine se terminant à `end` (apports et retraits exclus).
    Référence : le dernier relevé d'au moins 6 jours plus tôt (le vendredi précédent, ou le samedi
    des anciens relevés hebdomadaires), à condition qu'il ait moins de deux semaines."""
    by_date = {p.date: p for p in points if p.total_value is not None and p.total_invested is not None}
    last = by_date.get(end.isoformat())
    if last is None:
        return None
    candidates = [d for d in by_date if d <= (end - timedelta(days=6)).isoformat()]
    if not candidates or max(candidates) < (end - timedelta(days=14)).isoformat():
        return None
    start = by_date[max(candidates)]
    gain = (last.total_value - last.total_invested) - (start.total_value - start.total_invested)
    return {
        "start": start.date, "end": last.date, "gain": round(gain, 2),
        "gain_pct": gain / start.total_value if start.total_value else None,
        "value": round(last.total_value, 2),
        "contributions": round(last.total_invested - start.total_invested, 2),
    }


def reconstruct(trades: list, envelopes: dict[str, str], prices_eur: pd.DataFrame,
                start: date, end: date) -> list[tuple[date, dict]]:
    """Valeur et investi par enveloppe, chaque jour ouvré de start à end. trades : opérations Achat /
    Vente (realized.Operation). Sans cours connu (titre pas encore coté chez Yahoo ce jour-là), une
    position vaut son dernier prix d'achat."""
    days = pd.bdate_range(start, end)
    if not len(days):
        return []
    prices = prices_eur.copy()
    prices.index = pd.to_datetime(prices.index).tz_localize(None).normalize()
    prices = prices[~prices.index.duplicated()].sort_index()
    prices = prices.reindex(prices.index.union(days)).ffill().reindex(days)
    pending = sorted(trades, key=lambda op: (op.day, op.kind != "Achat"))
    holdings: dict[tuple[str, str], list[float]] = {}  # (enveloppe, titre) -> [quantité, coût]
    last_price: dict[str, float] = {}
    rows = []
    for day in days:
        while pending and pd.Timestamp(pending[0].day) <= day:
            op = pending.pop(0)
            envelope = envelopes.get(op.account, "CTO") if envelopes.get(op.account) in ("PEA", "CTO") else "CTO"
            position = holdings.setdefault((envelope, op.ticker), [0.0, 0.0])
            if op.kind == "Achat":
                position[0] += op.quantity
                position[1] += op.net
                last_price[op.ticker] = op.net / op.quantity
            elif position[0] > 0:
                sold = min(op.quantity, position[0])
                position[1] -= position[1] * sold / position[0]
                position[0] -= sold
        totals = {e: {"value": 0.0, "invested": 0.0} for e in ENVELOPES}
        for (envelope, ticker), (quantity, cost) in holdings.items():
            if quantity <= 1e-9:
                continue
            price = prices.at[day, ticker] if ticker in prices.columns else float("nan")
            price = float(price) if not pd.isna(price) else last_price.get(ticker, 0.0)
            totals[envelope]["value"] += quantity * price
            totals[envelope]["invested"] += cost
        if any(t["invested"] for t in totals.values()):
            rows.append((day.date(), totals))
    return rows


def rebuild_history(sheet_id: str, since: date | None = None, today: date | None = None) -> dict:
    """Recalcule l'onglet Historique de `since` (par défaut : première opération) à la veille."""
    from .performance import eur_closes
    from .realized import read_ledger

    ledger = read_ledger(sheet_id)
    trades = [op for op in ledger.operations if op.kind in ("Achat", "Vente") and op.quantity]
    if not trades:
        return {"rows": 0, "from": None}
    first = min(op.day for op in trades)
    start = max(since or first, first)
    end = (today or date.today()) - timedelta(days=1)
    if start > end:
        return {"rows": 0, "from": start.isoformat()}
    tickers = sorted({op.ticker for op in trades})
    prices = eur_closes(tickers, ledger.currencies, (first - timedelta(days=10)).isoformat())
    computed = reconstruct(trades, ledger.envelopes, prices, start, end)

    sheet = _open_sheet(sheet_id, write=True)
    ws = _worksheet(sheet, "Historique")
    kept = []
    for row in ws.get_values(value_render_option=UNFORMATTED)[1:]:
        row = (list(row) + [""] * 5)[:5]
        if not isinstance(row[0], (int, float)):
            continue
        day = SHEETS_EPOCH + timedelta(days=int(row[0]))
        if not start <= day <= end:
            kept.append((day, {"PEA": {"value": row[1] or 0, "invested": row[2] or 0},
                               "CTO": {"value": row[3] or 0, "invested": row[4] or 0}}))
    merged = sorted(kept + computed, key=lambda r: r[0])
    values = [history_row(day, totals, i + 2) for i, (day, totals) in enumerate(merged)]
    if ws.row_count < len(values) + 1:
        ws.add_rows(len(values) + 1 - ws.row_count + 100)
    ws.batch_clear(["A2:H"])
    if values:
        ws.update(range_name="A2", values=values, value_input_option="USER_ENTERED")
    return {"rows": len(computed), "from": start.isoformat(), "total": len(values)}


def record_snapshot(sheet_id: str, day: date) -> dict:
    """Ajoute le relevé du jour s'il n'existe pas encore, puis calcule la plus-value de la semaine."""
    sheet = _open_sheet(sheet_id, write=True)
    if not is_v2(sheet):
        return {"recorded": False, "reason": "ancien format de Sheet"}
    ws = _worksheet(sheet, "Historique")
    rows = ws.get_values(value_render_option=UNFORMATTED)
    points = parse_history_v2(rows)
    totals = snapshot_totals(_worksheet(sheet, "Positions").get_values(value_render_option=UNFORMATTED))

    recorded = False
    if not any(t["invested"] for t in totals.values()):
        reason = "aucune position"
    elif points and points[-1].date >= day.isoformat():
        reason = "relevé déjà présent"
    else:
        n = max(len(rows), 1) + 1
        ws.update(range_name=f"A{n}", values=[history_row(day, totals, n)], value_input_option="USER_ENTERED")
        points.append(point_from_totals(day, totals))
        recorded, reason = True, None
    return {"recorded": recorded, "reason": reason, "weekly": weekly_gain(points, day)}
