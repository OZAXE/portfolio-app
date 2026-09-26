"""
Sheet "modèle" de l'appli (format v2) : des tableaux simples, une ligne par élément,
que l'appli lit et complète sans dépendre de positions de cellules.

Onglets :
- Opérations  : une ligne par achat / vente / dividende (seule source de vérité) ;
- Titres      : ticker Yahoo et ticker Google (pour GOOGLEFINANCE), nom, secteur, zone, devise ;
- Positions   : calculé par formules à partir des opérations (quantité, PRU frais inclus, valeur...) ;
- Historique  : un relevé par ligne (valeur et montant investi par enveloppe) ;
- Comptes / Frais : comptes (enveloppe, courtier) et barèmes de frais par courtier et type d'ordre ;
- Livret, Watchlist.

build_template() construit ces onglets dans un Google Sheet vide partagé en Éditeur avec
le compte de service ; migrate_from_v1() y recopie les données de l'ancien Sheet.
Les formules sont écrites avec des ";" : le Sheet est réglé en français (fr_FR).
"""

from dataclasses import dataclass
from datetime import date, timedelta

import gspread

from .sheets import SHEETS_EPOCH, WRITE_SCOPES, google_credentials, google_to_yahoo, _find_worksheet

OPERATIONS_HEADERS = [
    "Date", "Compte", "Type", "Ticker", "Quantité", "Prix unitaire", "Devise", "Taux de change",
    "Montant brut €", "Frais €", "Taxes €", "Montant net €", "Type d'ordre", "Pourquoi", "Terme", "Note",
]
OPERATION_TYPES = ["Achat", "Vente", "Dividende"]
ORDER_TYPES = ["Ordre", "Plan d'investissement"]
TITRES_HEADERS = ["Ticker", "Ticker Google", "Nom", "Secteur", "Zone", "Devise", "Type"]
COMPTES_HEADERS = ["Compte", "Enveloppe", "Courtier"]
FRAIS_HEADERS = ["Courtier", "Type d'ordre", "Fixe €", "Pourcentage", "Minimum €", "Frais de change", "Note"]
HISTORY_HEADERS = ["Date", "Valeur PEA", "Investi PEA", "Valeur CTO", "Investi CTO", "Valeur totale", "Investi total", "Performance"]
POSITIONS_HEADERS = [
    "Ticker", "Nom", "Compte", "Enveloppe", "Quantité", "PRU €", "Investi €", "Cours", "Devise",
    "Taux €", "Valeur €", "Plus-value €", "Plus-value %", "Secteur", "Zone",
]

# Barèmes indicatifs : à vérifier et ajuster dans l'onglet Frais selon l'offre de chacun
DEFAULT_ACCOUNTS = [["PEA Boursorama", "PEA", "Boursorama"], ["CTO Trade Republic", "CTO", "Trade Republic"]]
DEFAULT_FEES = [
    ["Boursorama", "Ordre", 0, 0.005, 1.99, 0, "À VÉRIFIER selon ton offre (Découverte, Classic, Ultimo...)"],
    ["Trade Republic", "Ordre", 1, 0, 0, 0, "1 € par ordre"],
    ["Trade Republic", "Plan d'investissement", 0, 0, 0, 0, "Plans d'investissement sans frais"],
]

# Positions : une formule par colonne sur toute la hauteur (MAP / LAMBDA), rien à recopier à la main
POSITION_FORMULAS = {
    "A2": '=SORT(UNIQUE(FILTER(Opérations!D2:D; Opérations!D2:D<>""; (Opérations!C2:C="Achat")+(Opérations!C2:C="Vente"))))',
    "B2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; IFERROR(VLOOKUP(t; Titres!A:C; 3; FALSE); t))))',
    "C2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; INDEX(FILTER(Opérations!B2:B; Opérations!D2:D=t); 1))))',
    "D2": '=MAP(C2:C; LAMBDA(c; IF(c=""; ""; IFERROR(VLOOKUP(c; Comptes!A:B; 2; FALSE); ""))))',
    "E2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; SUMIFS(Opérations!E2:E; Opérations!D2:D; t; Opérations!C2:C; "Achat")'
          ' - SUMIFS(Opérations!E2:E; Opérations!D2:D; t; Opérations!C2:C; "Vente"))))',
    # PRU = coût total des achats (frais et taxes compris) / quantité achetée (méthode du prix moyen pondéré)
    "F2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; IFERROR(SUMIFS(Opérations!L2:L; Opérations!D2:D; t; Opérations!C2:C; "Achat")'
          ' / SUMIFS(Opérations!E2:E; Opérations!D2:D; t; Opérations!C2:C; "Achat"); 0))))',
    "G2": '=MAP(E2:E; F2:F; LAMBDA(q; p; IF(q=""; ""; q*p)))',
    "H2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; IFERROR(GOOGLEFINANCE(VLOOKUP(t; Titres!A:B; 2; FALSE)); ""))))',
    "I2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; IFERROR(VLOOKUP(t; Titres!A:F; 6; FALSE); "EUR"))))',
    "J2": '=MAP(I2:I; LAMBDA(d; IF(d=""; ""; IF(d="EUR"; 1; IFERROR(GOOGLEFINANCE("CURRENCY:"&d&"EUR"); "")))))',
    "K2": '=MAP(E2:E; H2:H; J2:J; LAMBDA(q; c; x; IF(OR(q=""; c=""; x=""); ""; q*c*x)))',
    "L2": '=MAP(K2:K; G2:G; LAMBDA(v; i; IF(OR(v=""; i=""); ""; v-i)))',
    "M2": '=MAP(L2:L; G2:G; LAMBDA(p; i; IF(OR(p=""; i=""; i=0); ""; p/i)))',
    "N2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; IFERROR(VLOOKUP(t; Titres!A:D; 4; FALSE); ""))))',
    "O2": '=MAP(A2:A; LAMBDA(t; IF(t=""; ""; IFERROR(VLOOKUP(t; Titres!A:E; 5; FALSE); ""))))',
}

# Formats d'affichage par onglet : (colonnes, motif)
EUR = "#,##0.00 €"
NUMBER_FORMATS = {
    "Opérations": [("A", "dd/mm/yyyy"), ("E", "0.######"), ("F", "#,##0.00##"), ("H", "0.0000"), ("I:L", EUR)],
    "Positions": [("E", "0.######"), ("F:G", EUR), ("H", "#,##0.00##"), ("J", "0.0000"), ("K:L", EUR), ("M", "0.00%")],
    "Historique": [("A", "dd/mm/yyyy"), ("B:G", EUR), ("H", "0.00%")],
    "Frais": [("C", EUR), ("D", "0.00%"), ("E", EUR), ("F", "0.00%")],
    "Livret": [("B", EUR)],
}


@dataclass
class TabSpec:
    title: str
    headers: list[str]
    rows: int = 500
    widths: dict[str, int] | None = None


TABS = [
    TabSpec("Positions", POSITIONS_HEADERS, rows=200),
    TabSpec("Opérations", OPERATIONS_HEADERS, rows=2000),
    TabSpec("Historique", HISTORY_HEADERS, rows=1000),
    TabSpec("Titres", TITRES_HEADERS, rows=300),
    TabSpec("Comptes", COMPTES_HEADERS, rows=20),
    TabSpec("Frais", FRAIS_HEADERS, rows=30),
    TabSpec("Livret", ["Nom", "Montant"], rows=30),
    TabSpec("Watchlist", ["TICKER", "AJOUTÉ LE"], rows=300),
]


def open_for_write(sheet_id: str) -> gspread.Spreadsheet:
    return gspread.authorize(google_credentials(WRITE_SCOPES)).open_by_key(sheet_id)


def _col_index(letter: str) -> int:
    n = 0
    for ch in letter:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _format_requests(ws: gspread.Worksheet, tab: str) -> list[dict]:
    sheet_id = ws.id
    requests = [
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                       "backgroundColor": {"red": 0.9, "green": 0.93, "blue": 0.97}}},
                        "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
    ]
    for columns, pattern in NUMBER_FORMATS.get(tab, []):
        first, _, last = columns.partition(":")
        requests.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "startColumnIndex": _col_index(first), "endColumnIndex": _col_index(last or first) + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE" if "yyyy" in pattern else "NUMBER", "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat"}})
    requests.append({"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS"}}})
    return requests


def _validation_requests(sheet: gspread.Spreadsheet) -> list[dict]:
    """Listes déroulantes dans Opérations : compte, type d'opération, type d'ordre."""
    ops = sheet.worksheet("Opérations").id

    def rule(column: str, condition: dict) -> dict:
        index = _col_index(column)
        return {"setDataValidation": {
            "range": {"sheetId": ops, "startRowIndex": 1, "startColumnIndex": index, "endColumnIndex": index + 1},
            "rule": {"condition": condition, "strict": True, "showCustomUi": True}}}

    values = lambda items: {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in items]}
    return [
        rule("B", {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Comptes!A2:A"}]}),
        rule("C", values(OPERATION_TYPES)),
        rule("M", values(ORDER_TYPES)),
    ]


def build_template(sheet: gspread.Spreadsheet) -> None:
    """Crée les onglets du modèle dans un Sheet vide (les onglets existants de même nom sont gardés)."""
    sheet.batch_update({"requests": [{"updateSpreadsheetProperties": {"properties": {"locale": "fr_FR"}, "fields": "locale"}}]})
    existing = {ws.title for ws in sheet.worksheets()}
    for spec in TABS:
        if spec.title not in existing:
            sheet.add_worksheet(spec.title, rows=spec.rows, cols=max(len(spec.headers), 2))
        ws = sheet.worksheet(spec.title)
        ws.update(range_name="A1", values=[spec.headers])
    # L'onglet vide créé avec le fichier ("Feuille 1" / "Sheet1") ne sert plus
    for ws in sheet.worksheets():
        if ws.title not in {t.title for t in TABS} and not ws.get_all_values():
            sheet.del_worksheet(ws)

    sheet.worksheet("Comptes").update(range_name="A2", values=DEFAULT_ACCOUNTS)
    sheet.worksheet("Frais").update(range_name="A2", values=DEFAULT_FEES)
    positions = sheet.worksheet("Positions")
    positions.batch_update([{"range": cell, "values": [[formula]]} for cell, formula in POSITION_FORMULAS.items()],
                           value_input_option="USER_ENTERED")

    requests = _validation_requests(sheet)
    for spec in TABS:
        requests += _format_requests(sheet.worksheet(spec.title), spec.title)
    sheet.batch_update({"requests": requests})


# --- Migration depuis l'ancien Sheet (blocs Mouvement / Action / Courbe / Historique en colonnes) ---

UNDATED_DEFAULT = date(2026, 5, 5)
ENVELOPE_ACCOUNTS = {"PEA": ("PEA Boursorama", "Ordre"), "CTO": ("CTO Trade Republic", "Plan d'investissement")}


def _serial_to_date(value) -> date | None:
    if isinstance(value, (int, float)):
        return SHEETS_EPOCH + timedelta(days=int(value))
    return None


def _cell(rows, r, c):
    if r < 0 or r >= len(rows) or c >= len(rows[r]):
        return None
    value = rows[r][c]
    return None if value == "" else value


def parse_v1_movements(rows: list[list]) -> list[dict]:
    """Onglet Mouvement : un bloc par titre (ticker en colonne B, libellés en D, F, H...,
    valeurs en E, G, I...). La date d'une opération est sur la ligne au-dessus du bloc ;
    la première colonne ("Avant") n'a pas de date."""
    operations = []
    envelope = None
    for r in range(len(rows)):
        label_a = str(_cell(rows, r, 0) or "").strip().upper()
        if label_a in ENVELOPE_ACCOUNTS:
            envelope = label_a
        ticker = _cell(rows, r, 1)
        if not ticker or ":" not in str(ticker) or str(_cell(rows, r, 3) or "").strip() != "Achat/vente":
            continue
        # Lignes du bloc jusqu'à "Terme"
        block = {}
        for rr in range(r, min(r + 10, len(rows))):
            label = str(_cell(rows, rr, 3) or "").strip()
            if label:
                block[label] = rr
            if label == "Terme":
                break
        width = max(len(rows[rr]) for rr in block.values())
        for value_col in range(4, width, 2):
            kind = str(_cell(rows, r, value_col) or "").strip().capitalize()
            if kind not in ("Achat", "Vente"):
                continue
            get = lambda label: _cell(rows, block[label], value_col) if label in block else None
            quantity = get("Quantité")
            price = get("Prix") or get("Prix d'achat") or get("Prix de l'action")
            if not isinstance(quantity, (int, float)) or not isinstance(price, (int, float)):
                continue
            # "Combien €" = montant débité. S'il vaut quantité x prix, le prix était déjà en euros
            # (Trade Republic affiche les cours en euros) ; sinon on en déduit le taux de change
            amount_eur = get("Combien €")
            fx, currency = 1.0, None
            if isinstance(amount_eur, (int, float)) and quantity and price:
                fx = amount_eur / (quantity * price)
                if abs(fx - 1) < 0.01:
                    fx, currency = 1.0, "EUR"
            when = _serial_to_date(_cell(rows, r - 1, value_col - 1)) or _serial_to_date(_cell(rows, r - 1, value_col))
            account, order_type = ENVELOPE_ACCOUNTS.get(envelope, ("", "Ordre"))
            operations.append({
                "date": when or UNDATED_DEFAULT, "account": account, "type": kind,
                "google_ticker": str(ticker).strip(), "ticker": google_to_yahoo(str(ticker).strip()),
                "quantity": float(quantity), "price": float(price), "fx": fx, "currency": currency,
                "order_type": order_type, "why": get("Pourquoi") or "", "term": get("Terme") or "",
                "note": "" if when else "Date à préciser (achat antérieur au suivi)",
            })
    return operations


def operation_row(op: dict, row: int) -> list:
    """Ligne de l'onglet Opérations, avec les montants en formules pour rester modifiables à la main."""
    return [
        op["date"].isoformat(), op["account"], op["type"], op["ticker"], op["quantity"], op["price"],
        op.get("currency", "EUR"), op["fx"],
        f"=E{row}*F{row}*H{row}", op.get("fees", 0), op.get("taxes", 0),
        f'=IF(C{row}="Achat"; I{row}+J{row}+K{row}; I{row}-J{row}-K{row})',
        op["order_type"], op["why"], op["term"], op["note"],
    ]


def migrate_from_v1(old: gspread.Spreadsheet, new: gspread.Spreadsheet, describe) -> dict:
    """Recopie opérations, titres, historique et livrets.
    describe(ticker Yahoo) -> (nom lisible, "Action" ou "ETF"), fourni par l'appelant (Yahoo)."""
    unformatted = gspread.utils.ValueRenderOption.unformatted
    mouvement = _find_worksheet(old, "Mouvement").get_values(value_render_option=unformatted)
    courbe = _find_worksheet(old, "Courbe").get_values(value_render_option=unformatted)
    historique = _find_worksheet(old, "Historique").get_values(value_render_option=unformatted)
    action = _find_worksheet(old, "Action")
    action_rows = action.get_values(value_render_option=unformatted) if action else []

    operations = parse_v1_movements(mouvement)
    # Devise de cotation (celle de GOOGLEFINANCE : EUR à Paris, USD à New York et pour URNU à Londres),
    # distincte de la devise de l'opération quand le courtier a facturé en euros
    for op in operations:
        op["quote_currency"] = "EUR" if op["google_ticker"].startswith("EPA:") else "USD"
        op["currency"] = op["currency"] or op["quote_currency"]
    operations.sort(key=lambda op: op["date"])
    new.worksheet("Opérations").update(
        range_name="A2", values=[operation_row(op, i + 2) for i, op in enumerate(operations)],
        value_input_option="USER_ENTERED",
    )

    # Titres : secteur de l'onglet Courbe, zone de l'onglet Action
    sectors = {str(row[1]).strip(): row[6] for row in courbe[1:] if len(row) > 6 and row[1]}
    zones = {}
    for row in action_rows:
        if len(row) > 10 and row[1] and ":" in str(row[1]) and row[10]:
            zones[str(row[1]).strip()] = row[10]
    titres, seen = [], set()
    for op in operations:
        if op["ticker"] in seen:
            continue
        seen.add(op["ticker"])
        g = op["google_ticker"]
        name, kind = describe(op["ticker"])
        titres.append([op["ticker"], g, name or g, sectors.get(g, ""), zones.get(g, ""), op["quote_currency"], kind])
    new.worksheet("Titres").update(range_name="A2", values=titres)

    # Historique : colonnes -> lignes ; montant investi retrouvé à partir de la valeur et de la performance
    history_rows = []
    width = max((len(r) for r in historique), default=0)
    for c in range(1, width):
        when = _serial_to_date(_cell(historique, 0, c))
        if not when:
            continue
        values = {k: _cell(historique, r, c) for k, r in (("pea_pct", 2), ("pea", 4), ("cto_pct", 6), ("cto", 8))}
        if not all(isinstance(v, (int, float)) for v in values.values()):
            continue
        invested_pea = values["pea"] / (1 + values["pea_pct"])
        invested_cto = values["cto"] / (1 + values["cto_pct"])
        row = len(history_rows) + 2
        history_rows.append([when.isoformat(), values["pea"], invested_pea, values["cto"], invested_cto,
                             f"=B{row}+D{row}", f"=C{row}+E{row}", f"=F{row}/G{row}-1"])
    history_rows.sort(key=lambda r: r[0])
    for i, row in enumerate(history_rows):  # formules renumérotées après le tri
        n = i + 2
        row[5:8] = [f"=B{n}+D{n}", f"=C{n}+E{n}", f"=F{n}/G{n}-1"]
    new.worksheet("Historique").update(range_name="A2", values=history_rows, value_input_option="USER_ENTERED")

    livret = _find_worksheet(old, "Livret")
    savings = []
    if livret:
        for row in livret.get_values(value_render_option=unformatted):
            if len(row) > 1 and row[0] and isinstance(row[1], (int, float)):
                savings.append([str(row[0]).strip(), row[1]])
        new.worksheet("Livret").update(range_name="A2", values=savings)

    watch = _find_worksheet(old, "Watchlist")
    watch_rows = [r[:2] for r in watch.get_values()[1:] if r and r[0]] if watch else []
    if watch_rows:
        new.worksheet("Watchlist").update(range_name="A2", values=watch_rows)

    return {"operations": len(operations), "titres": len(titres), "historique": len(history_rows),
            "livrets": len(savings), "watchlist": len(watch_rows)}
