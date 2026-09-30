"""Divisions et actions gratuites : quantités ramenées sur la base d'aujourd'hui, coût inchangé."""

from datetime import date

import pandas as pd
import pytest

from app import history, realized
from app.imports import parse_trade_republic_csv
from app.operations import OperationError, _add_shares, held_quantities
from app.realized import Operation, apply_splits, compute_realized
from app.sheets import SHEETS_EPOCH
from app.workbook import POSITION_FORMULAS, is_old_quantity_formula


def op(day, kind, quantity, net=0.0, account="CTO TR", ticker="AAPL"):
    return Operation(day, account, kind, ticker, quantity, net, 0.0, 0.0, net)


def serial(d):
    return (d - SHEETS_EPOCH).days


def test_division_ramene_les_achats_passes_sur_la_base_actuelle():
    # Apple : 10 actions achetées 2 000 € en 2019, division 4 pour 1 en août 2020 (30 reçues),
    # 20 vendues 1 500 € en 2021 -> achat de 40 actions, vente de 20, division retirée
    ops = [op(date(2019, 5, 2), "Achat", 10, 2000), op(date(2020, 8, 31), "Division", 30),
           op(date(2021, 3, 1), "Vente", 20, 1500)]
    adjusted = apply_splits(ops)
    assert [(o.kind, o.quantity, o.net) for o in adjusted] == [("Achat", 40, 2000), ("Vente", 20, 1500)]
    assert ops[0].quantity == 10  # les opérations d'origine ne sont pas modifiées


def test_plus_value_identique_avec_ou_sans_division():
    # 40 actions pour 2 000 € -> PRU 50 € ; 20 vendues 1 500 € : 1 500 - 20 x 50 = 500 € de plus-value
    ops = [op(date(2019, 5, 2), "Achat", 10, 2000), op(date(2020, 8, 31), "Division", 30),
           op(date(2021, 3, 1), "Vente", 20, 1500)]
    sale = compute_realized(apply_splits(ops), {"CTO TR": "CTO"})["years"][0]["sales"][0]
    assert sale["unit_cost"] == 50 and sale["gain"] == 500


def test_actions_gratuites_air_liquide():
    # 20 actions pour 3 000 €, 2 gratuites (1 pour 10) -> rapport 1,1 : l'achat compte 22 actions,
    # PRU 3 000 / 22 = 136,36 € ; vente de 11 pour 2 000 € : 2 000 - 11 x 136,36 = 500 €
    ops = [op(date(2025, 1, 10), "Achat", 20, 3000, ticker="AI.PA"),
           op(date(2025, 6, 9), "Actions gratuites", 2, ticker="AI.PA"),
           op(date(2026, 2, 1), "Vente", 11, 2000, ticker="AI.PA")]
    adjusted = apply_splits(ops)
    assert adjusted[0].quantity == pytest.approx(22)
    sale = compute_realized(adjusted, {"CTO TR": "CTO"})["years"][0]["sales"][0]
    assert sale["gain"] == pytest.approx(500, abs=0.01)


def test_division_limitee_au_compte_et_ignoree_sans_actions():
    ops = [op(date(2020, 1, 2), "Achat", 10, 1000, account="PEA"),
           op(date(2020, 1, 2), "Achat", 5, 500, account="CTO"),
           op(date(2020, 8, 31), "Division", 30, account="PEA"),
           op(date(2020, 9, 1), "Division", 3, account="CTO", ticker="MSFT")]  # aucune MSFT détenue
    adjusted = apply_splits(ops)
    assert [(o.account, o.quantity) for o in adjusted] == [("PEA", 40), ("CTO", 5)]


def test_regroupement_divise_les_quantites():
    # Regroupement 1 pour 10 : 100 actions -> 10 (90 en moins), l'achat compte 10 actions
    adjusted = apply_splits([op(date(2024, 1, 2), "Achat", 100, 500), op(date(2024, 6, 3), "Division", -90)])
    assert adjusted[0].quantity == pytest.approx(10)


def test_historique_reconstitue_avec_cours_reels():
    # eur_closes donne les cours réels (non corrigés des divisions) : 200 € la veille de la division 4 pour 1,
    # 52 € le jour même. Quantités telles que saisies, division comprise : 10 x 200 = 2 000 € puis
    # 40 x 52 = 2 080 € (et pas 10 x 52 = 520 € si la division était ignorée)
    ops = [op(date(2020, 8, 28), "Achat", 10, 2000), op(date(2020, 8, 31), "Division", 30)]
    prices = pd.DataFrame({"AAPL": [200.0, 52.0]}, index=pd.to_datetime(["2020-08-28", "2020-08-31"]))
    rows = history.reconstruct(ops, {"CTO TR": "CTO"}, prices, date(2020, 8, 28), date(2020, 8, 31))
    values = {day: totals["CTO"]["value"] for day, totals in rows}
    assert values[date(2020, 8, 28)] == 2000 and values[date(2020, 8, 31)] == 2080
    assert rows[-1][1]["CTO"]["invested"] == 2000  # le coût ne change pas


def test_contribution_quantite_de_depart_avec_division():
    # Départ de la période le 1er juillet 2020 : 10 actions à 360 € (cours réel) = 3 600 € ; division le
    # 31 août, 40 actions valent 4 000 € aujourd'hui -> gain de 400 €, sans flux sur la période
    from app.stats import _Lookup, compute_attribution

    ops = [op(date(2020, 1, 2), "Achat", 10, 3000), op(date(2020, 8, 31), "Division", 30)]
    closes = {"AAPL": _Lookup([(date(2020, 7, 1), 360.0)])}
    result = compute_attribution(ops, {"CTO TR": "CTO"}, {("CTO", "AAPL"): 4000.0}, closes,
                                 date(2020, 7, 1), date(2020, 12, 31), {})
    assert [(r["start"], r["gain"]) for r in result["lines"]] == [(3600.0, 400.0)]


def test_ledger_garde_les_quantites_saisies(monkeypatch):
    tabs = {
        "Opérations": [["DATE"],
                       [serial(date(2019, 5, 2)), "CTO TR", "Achat", "AAPL", 10, 200, "EUR", 1, 2000, 0, 0, 2000],
                       [serial(date(2020, 8, 31)), "CTO TR", "Division", "AAPL", 30, 0, "EUR", 1, 0, 0, 0, 0]],
        "Comptes": [["Compte"], ["CTO TR", "CTO", "Trade Republic"]],
        "Titres": [["TICKER"], ["AAPL", "NASDAQ:AAPL", "Apple", "", "", "USD"]],
    }

    class Ws:
        def __init__(self, rows):
            self.rows = rows

        def get_values(self, value_render_option=None):
            return self.rows

    monkeypatch.setattr(realized, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(realized, "_worksheet", lambda s, name: Ws(tabs[name]))
    monkeypatch.setattr(realized, "_ledgers", {})
    ledger = realized.read_ledger("sheet")
    assert [(o.kind, o.quantity) for o in ledger.operations] == [("Achat", 40)]
    assert [(o.kind, o.quantity) for o in ledger.raw] == [("Achat", 10), ("Division", 30)]


def test_quantite_detenue_par_compte_et_a_une_date():
    rows = [[serial(date(2020, 1, 2)), "PEA", "Achat", "aapl", 10],
            [serial(date(2020, 8, 31)), "PEA", "Division", "AAPL", 30],
            [serial(date(2021, 1, 4)), "PEA", "Vente", "AAPL", 15],
            [serial(date(2021, 1, 4)), "CTO", "Achat", "AAPL", 2],
            [serial(date(2021, 1, 5)), "CTO", "Dividende", "AAPL", 2]]
    assert held_quantities(rows) == {("PEA", "AAPL"): 25, ("CTO", "AAPL"): 2}
    assert held_quantities(rows, until=date(2020, 12, 31)) == {("PEA", "AAPL"): 40}


class FakeOps:
    def __init__(self, rows):
        self.rows, self.written = rows, []

    def get_values(self, value_render_option=None):
        return [["Date"]] + self.rows

    def col_values(self, col):
        return [""] * (len(self.rows) + 1)

    def update(self, range_name, values, value_input_option=None):
        self.written += values


def test_saisie_division_controle_la_quantite(monkeypatch):
    tab = FakeOps([[serial(date(2020, 1, 2)), "PEA", "Achat", "AAPL", 10]])
    monkeypatch.setattr("app.operations._worksheet", lambda sheet, name: tab)
    monkeypatch.setattr("app.operations.ensure_operation_types", lambda sheet: None)
    result = _add_shares(object(), {"ticker": "aapl", "date": "2020-08-31", "quantity": 30}, "Division", "PEA")
    assert result["row"] == 3
    written = tab.written[0]
    assert written[2:6] == ["Division", "AAPL", 30.0, 0] and written[15] == "10 -> 40 actions"
    with pytest.raises(OperationError, match="Aucune action"):  # pas encore achetée à cette date
        _add_shares(object(), {"ticker": "AAPL", "date": "2019-12-31", "quantity": 30}, "Division", "PEA")
    with pytest.raises(OperationError, match="positif"):
        _add_shares(object(), {"ticker": "AAPL", "date": "2020-08-31", "quantity": -1}, "Actions gratuites", "PEA")
    with pytest.raises(OperationError, match="Regroupement impossible"):
        _add_shares(object(), {"ticker": "AAPL", "date": "2020-08-31", "quantity": -10}, "Division", "PEA")


def test_formules_positions_comptent_les_actions_recues():
    assert "Division" in POSITION_FORMULAS["E2"] and "Actions gratuites" in POSITION_FORMULAS["E2"]
    assert '(Opérations!C2:C="Division")' in POSITION_FORMULAS["F2"]
    assert is_old_quantity_formula('=MAP(A2:A; C2:C; LAMBDA(t; c; SUMIFS(x; "Achat") - SUMIFS(x; "Vente")))')
    assert not is_old_quantity_formula(POSITION_FORMULAS["E2"])


TR_CSV_BONUS = '''"datetime","date","account_type","category","type","asset_class","name","symbol","shares","price","amount","fee","tax","currency","original_amount","original_currency","fx_rate","description","transaction_id","counterparty_name","counterparty_iban","payment_reference","mcc_code"
"2026-06-08T10:00:00Z","2026-06-08","PEA","CORPORATE_ACTION","BONUS_ISSUE","STOCK","Air Liquide","FR0000120073","0.2000000000","","","","","","","","","BONUS_ISSUE FR0000120073","a3","","","",""
"2026-06-09T10:00:00Z","2026-06-09","PEA","CORPORATE_ACTION","SPLIT","STOCK","Nvidia","US67066G1040","9.0000000000","","","","","","","","","SPLIT US67066G1040","a4","","","",""
'''


def test_import_trade_republic_actions_gratuites():
    skipped = {}
    ops = parse_trade_republic_csv(TR_CSV_BONUS, "tr.csv", skipped)
    assert [(o.type, o.isin, o.quantity, o.price, o.envelope) for o in ops] == [
        ("Actions gratuites", "FR0000120073", 0.2, 0.0, "PEA")]
    assert skipped == {"corporate": 1}  # format de la division inconnu : signalée, à saisir à la main
