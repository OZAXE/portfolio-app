"""
Frais courants des ETF détenus, rangés dans l'onglet « Frais ETF » du Sheet du propriétaire
(le même que le registre des utilisateurs, voir signup.py).

Ils étaient publiés dans etf_fees.json sur la branche publique screener-data, ce qui révélait
la liste des titres détenus par les utilisateurs. Le job nocturne (screener/etf_fees.py) les lit et
les écrit maintenant par l'API, avec le code administrateur.
"""

from .sheets import _find_worksheet, _open_sheet

FEES_TAB = "Frais ETF"
FEES_HEADERS = ["TICKER", "TYPE", "FRAIS COURANTS %", "NOM", "MIS À JOUR"]


def parse_fee_rows(rows: list[list]) -> dict:
    state = {"etfs": {}, "not_etf": {}}
    for row in rows[1:]:
        row = (list(row) + [""] * 5)[:5]
        ticker, kind, ter, name, updated = row
        if not ticker or not updated:
            continue
        if kind == "ETF":
            state["etfs"][str(ticker)] = {"ter": float(ter) if isinstance(ter, (int, float)) else None,
                                          "name": name or None, "updated": str(updated)}
        else:
            state["not_etf"][str(ticker)] = {"updated": str(updated)}
    return state


def fee_rows(state: dict) -> list[list]:
    rows = [FEES_HEADERS]
    for ticker, e in sorted(state.get("etfs", {}).items()):
        rows.append([ticker, "ETF", e.get("ter") if e.get("ter") is not None else "", e.get("name") or "", e["updated"]])
    for ticker, e in sorted(state.get("not_etf", {}).items()):
        rows.append([ticker, "Action", "", "", e["updated"]])
    return rows


def read_fee_state() -> dict:
    from .signup import registry_sheet_id

    ws = _find_worksheet(_open_sheet(registry_sheet_id()), FEES_TAB)
    return parse_fee_rows(ws.get_values(value_render_option="UNFORMATTED_VALUE")) if ws is not None else {"etfs": {}, "not_etf": {}}


def write_fee_state(state: dict) -> dict:
    from .signup import registry_sheet_id

    sheet = _open_sheet(registry_sheet_id(), write=True)
    ws = _find_worksheet(sheet, FEES_TAB)
    rows = fee_rows(state)
    if ws is None:
        ws = sheet.add_worksheet(FEES_TAB, rows=max(len(rows) + 50, 200), cols=len(FEES_HEADERS))
    ws.clear()
    ws.update(range_name="A1", values=rows, value_input_option="RAW")
    return {"etfs": len(state.get("etfs", {})), "not_etf": len(state.get("not_etf", {}))}
