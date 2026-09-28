"""
Repartir de zéro : efface les opérations (toutes, ou celles d'un compte, ou seulement les lignes
importées) pour réimporter ses relevés proprement, avec une sauvegarde pour revenir en arrière.

Avant d'effacer, l'onglet Opérations est copié dans un nouvel onglet « Sauvegarde opérations … » (et
l'Historique dans « Sauvegarde historique … » quand tout est effacé). restore_backup() remet ces
copies en place : formules comprises, puisqu'elles ne font référence qu'à leur propre ligne.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from .operations import OperationError
from .sheets import _find_worksheet, _open_sheet, _worksheet

OPERATIONS_BACKUP = "Sauvegarde opérations"
HISTORY_BACKUP = "Sauvegarde historique"


def rows_to_delete(rows: list[list], account: str | None, imported_only: bool) -> list[int]:
    """Numéros de ligne (1 = en-tête) des opérations à effacer."""
    selected = []
    for i, row in enumerate(rows[1:], start=2):
        row = (list(row) + [""] * 16)[:16]
        if not any(str(v).strip() for v in row[:5]):
            continue
        if account and str(row[1]).strip() != account:
            continue
        if imported_only and not str(row[15]).startswith("Import"):
            continue
        selected.append(i)
    return selected


def _row_blocks(rows: list[int]) -> list[tuple[int, int]]:
    """Lignes consécutives regroupées, du bas vers le haut : [(début, fin incluse), ...]."""
    blocks = []
    for r in sorted(rows):
        if blocks and r == blocks[-1][1] + 1:
            blocks[-1][1] = r
        else:
            blocks.append([r, r])
    return [tuple(b) for b in reversed(blocks)]


def reset_operations(sheet_id: str, account: str | None, imported_only: bool, dry_run: bool = False) -> dict:
    sheet = _open_sheet(sheet_id, write=not dry_run)
    ops = _worksheet(sheet, "Opérations")
    rows = ops.get_values()
    targets = rows_to_delete(rows, account or None, imported_only)
    everything = not account and not imported_only
    if dry_run or not targets:
        return {"count": len(targets), "everything": everything}

    stamp = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d %Hh%M %Ss")
    backup = sheet.duplicate_sheet(ops.id, new_sheet_name=f"{OPERATIONS_BACKUP} {stamp}")
    history_backup = None
    if everything:
        # Tout effacer : on garde la taille de l'onglet (les écritures suivantes visent des lignes existantes)
        ops.batch_clear([f"A2:P{len(rows)}"])
        history = _worksheet(sheet, "Historique")
        history_backup = sheet.duplicate_sheet(history.id, new_sheet_name=f"{HISTORY_BACKUP} {stamp}").title
        history.batch_clear(["A2:H"])
    else:
        sheet.batch_update({"requests": [
            {"deleteDimension": {"range": {"sheetId": ops.id, "dimension": "ROWS", "startIndex": start - 1, "endIndex": end}}}
            for start, end in _row_blocks(targets)]})
    return {"count": len(targets), "everything": everything, "backup": backup.title, "history_backup": history_backup}


def _restore(sheet, target_name: str, backup_name: str, columns: str) -> int:
    backup = _find_worksheet(sheet, backup_name)
    if backup is None:
        raise OperationError(f"Sauvegarde introuvable : {backup_name}")
    target = _worksheet(sheet, target_name)
    values = backup.get_values(value_render_option="FORMULA")[1:]
    target.batch_clear([f"A2:{columns}"])
    if values:
        if target.row_count < len(values) + 1:
            target.add_rows(len(values) + 1 - target.row_count)
        target.update(range_name="A2", values=values, value_input_option="USER_ENTERED")
    return len(values)


def restore_backup(sheet_id: str, backup: str, history_backup: str | None = None) -> dict:
    """Remet les opérations (et l'historique) tels qu'ils étaient avant « Repartir de zéro »."""
    if not str(backup or "").startswith(OPERATIONS_BACKUP):
        raise OperationError("Sauvegarde invalide")
    sheet = _open_sheet(sheet_id, write=True)
    restored = _restore(sheet, "Opérations", backup, "P")
    if history_backup:
        if not history_backup.startswith(HISTORY_BACKUP):
            raise OperationError("Sauvegarde invalide")
        _restore(sheet, "Historique", history_backup, "H")
    return {"restored": restored}
