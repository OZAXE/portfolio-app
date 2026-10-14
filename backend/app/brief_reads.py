"""
Briefs lus (octobre 2026, demande d'Enzo) : la case « Lu » de chaque brief hebdo, rangée dans le Sheet de
l'utilisateur pour le suivre d'un appareil à l'autre (coché sur le téléphone, lu aussi sur le PC).

Onglet « Briefs lus » créé au premier brief coché (comme le Journal) : une ligne par brief lu, décocher
la supprime. L'identifiant est celui du fichier Drive ; la date du brief est là pour qui ouvre le Sheet.
Les amis ont chacun leur Sheet : même dossier de briefs publics, mais chacun son suivi.
"""

from datetime import date

from .notifications import _tab

READS_TAB = "Briefs lus"
READS_HEADERS = ["Brief", "Date du brief", "Lu le"]


def parse_reads(rows: list[list]) -> dict[str, str]:
    """Lignes de l'onglet (sans l'en-tête) -> {identifiant: date de lecture}. Ligne sans identifiant ignorée."""
    reads = {}
    for row in rows:
        row = (list(row) + [""] * 3)[:3]
        brief_id = str(row[0]).strip()
        if brief_id:
            reads[brief_id] = str(row[2]).strip()[:10]
    return reads


def list_reads(sheet_id: str) -> dict[str, str]:
    ws = _tab(sheet_id, READS_TAB, READS_HEADERS, create=False)
    return parse_reads(ws.get_values()[1:]) if ws is not None else {}


def set_read(sheet_id: str, brief: dict, read: bool, today: date | None = None) -> dict[str, str]:
    """Coche (ligne ajoutée si absente) ou décoche (lignes du brief supprimées). `brief` vient de la liste
    du dossier Drive, jamais du navigateur : on n'écrit pas un identifiant inventé dans le Sheet."""
    ws = _tab(sheet_id, READS_TAB, READS_HEADERS, create=read)
    if ws is None:
        return {}
    ids = [str(v).strip() for v in ws.col_values(1)]
    if read:
        if brief["id"] not in ids[1:]:
            # RAW : identifiant et dates restent du texte, rien n'est interprété comme une formule
            ws.append_row([brief["id"], brief["date"], (today or date.today()).isoformat()], value_input_option="RAW")
    else:
        for row in range(len(ids), 1, -1):  # de bas en haut : les numéros restent valables
            if ids[row - 1] == brief["id"]:
                ws.delete_rows(row)
    return list_reads(sheet_id)
