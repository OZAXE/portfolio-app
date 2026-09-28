"""
Relevé quotidien de l'onglet Historique et plus-value de la semaine.

Le job nocturne (screener/snapshot.py) appelle POST /history/snapshot après chaque jour de bourse :
pour chaque utilisateur, une ligne est ajoutée à son onglet Historique (date, valeur et montant
investi du PEA et du CTO, lus dans l'onglet Positions déjà calculé par les formules du Sheet).
Remplace l'ancien relevé hebdomadaire par Apps Script.

La plus-value de la semaine retire les apports : c'est la variation de (valeur - investi)
entre le relevé du vendredi précédent et celui du jour.
"""

from datetime import date, timedelta

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
