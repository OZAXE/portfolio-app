"""Dernier calcul de l'onglet Perf. gardé dans le Sheet de l'utilisateur, pour l'afficher tout de suite
après un réveil du serveur.

Pourquoi : les caches de l'API sont en mémoire. Render (plan gratuit) s'endort après 15 min et ne peut pas
rester éveillé tout le mois (750 h partagées avec un autre projet d'Enzo, qui en prend 360) : à chaque réveil,
l'onglet Perf. retéléchargeait 5 ans de cours Yahoo pour chaque titre avant d'afficher quoi que ce soit.
Désormais chaque calcul est rangé dans l'onglet Réglages (clé `stats:<indice>`, JSON en RAW) ; le front
l'affiche d'abord, marqué « du <date> », pendant que le calcul frais tourne (/portfolio/stats?stored=1).

Une cellule Google Sheets tient 50 000 caractères : un résultat plus gros (des centaines de lignes en
contribution) n'est simplement pas gardé.
"""

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

KEY_PREFIX = "stats:"
MAX_CELL = 49_000


def _settings_tab(sheet_id: str, create: bool):
    from .notifications import SETTINGS_TAB, _tab

    return _tab(sheet_id, SETTINGS_TAB, ["CLÉ", "VALEUR"], create=create, write=create)


def _find(ws, key: str) -> tuple[int | None, str | None]:
    for n, row in enumerate(ws.get_values(), start=1):
        if n > 1 and row and row[0] == key:
            return n, row[1] if len(row) > 1 else ""
    return None, None


def load_stats(sheet_id: str, benchmark: str) -> dict | None:
    """{"stored_at": ISO, "result": ...} ou None (jamais calculé, illisible)."""
    try:
        ws = _settings_tab(sheet_id, create=False)
        if ws is None:
            return None
        _, text = _find(ws, KEY_PREFIX + benchmark)
        stored = json.loads(text) if text else None
        return stored if isinstance(stored, dict) and "result" in stored else None
    except Exception as e:  # le stockage n'est qu'un raccourci : jamais une erreur pour l'utilisateur
        log.warning("Perf. gardée illisible : %s", e)
        return None


def save_stats(sheet_id: str, benchmark: str, result: dict | None) -> bool:
    if result is None:
        return False
    text = json.dumps({"stored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": result},
                      separators=(",", ":"), ensure_ascii=False, default=str)
    if len(text) > MAX_CELL:
        return False
    from .sheets import neutral_writes

    try:
        with neutral_writes():
            return _write(sheet_id, KEY_PREFIX + benchmark, text)
    except Exception as e:
        log.warning("Perf. non gardée dans le Sheet : %s", e)
        return False


def _write(sheet_id: str, key: str, text: str) -> bool:
    ws = _settings_tab(sheet_id, create=True)
    row, _ = _find(ws, key)
    if row:
        ws.update(range_name=f"A{row}:B{row}", values=[[key, text]], value_input_option="RAW")
    else:
        ws.append_row([key, text], value_input_option="RAW")
    return True

