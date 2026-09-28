from datetime import date

import pytest

from app import duplicates
from app.duplicates import Entry, find_duplicate_pairs, mark_duplicates, same_operation
from app.operations import OperationError
from app.sheets import SHEETS_EPOCH


def e(day, ticker, quantity, amount, kind="Achat", envelope="PEA", row=None, note=""):
    return Entry(date(2025, 12, day), envelope, kind, ticker, quantity, amount, row=row, note=note)


def test_two_different_stocks_same_day_same_quantity_are_not_duplicates():
    assert not same_operation(e(10, "RR.L", 1, 12.96), e(10, "BRBY.L", 1, 13.93))
    assert mark_duplicates([e(10, "RR.L", 1, 12.96), e(10, "BRBY.L", 1, 13.93)], []) == [False, False]


def test_manual_entry_a_few_days_off_is_recognised():
    manual = e(8, "AI.PA", 1, 159.0)  # saisie à la date de l'ordre
    assert mark_duplicates([e(10, "AI.PA", 1, 159.28)], [manual]) == [True]
    assert mark_duplicates([e(20, "AI.PA", 1, 159.28)], [manual]) == [False]  # dix jours plus tard : autre achat


def test_other_ticker_same_amount_and_rounded_quantity():
    assert same_operation(e(10, "TNO.PA", 0.005567, 40.0), e(10, "TNOW.MI", 0.0056, 40.2))
    assert not same_operation(e(10, "AI.PA", 1, 159.0), e(10, "AI.PA", 1, 159.0, envelope="CTO"))  # autre enveloppe
    assert not same_operation(e(10, "AI.PA", 2, 318.0), e(10, "AI.PA", 1, 159.0))


def test_dividends_match_on_ticker_even_gross_versus_net():
    assert same_operation(e(10, "NVDA", 1.25, 0.02, "Dividende"), e(11, "NVDA", 1, 0.03, "Dividende"))
    assert not same_operation(e(10, "NVDA", 1, 0.02, "Dividende"), e(10, "TSM", 1, 0.02, "Dividende"))


def test_identical_purchases_the_same_day_count_twice():
    existing = [e(10, "AI.PA", 1, 159.0)]
    same_file = [Entry(date(2025, 12, 10), "PEA", "Achat", "AI.PA", 1, 159.0, source="releve.pdf") for _ in range(3)]
    assert mark_duplicates(same_file, existing) == [True, False, False]


def test_same_order_in_two_files_is_imported_once():
    a = Entry(date(2025, 12, 10), "PEA", "Achat", "AI.PA", 1, 159.0, source="releve.pdf")
    b = Entry(date(2025, 12, 10), "PEA", "Achat", "AI.PA", 1, 159.28, source="avis.pdf")
    assert mark_duplicates([a, b], []) == [False, True]


def test_duplicate_pairs_remove_the_imported_copy():
    rows = [e(10, "AI.PA", 1, 159.0, row=2, note="Import avis.pdf"), e(9, "AI.PA", 1, 159.0, row=5),
            e(10, "NVDA", 1, 160.0, envelope="CTO", row=6), e(10, "NVDA", 1, 160.0, envelope="CTO", row=9)]
    pairs = find_duplicate_pairs(rows)
    assert [(k.row, x.row) for k, x in pairs] == [(5, 2), (6, 9)]


class FakeWorksheet:
    def __init__(self, rows):
        self.rows, self.deleted = rows, []

    def get_values(self, value_render_option=None):
        return self.rows

    def delete_rows(self, index):
        self.deleted.append(index)


def serial(d):
    return (d - SHEETS_EPOCH).days


def test_delete_checks_rows_and_goes_bottom_up(monkeypatch):
    ops = [["Date"]] + [[serial(date(2025, 12, 10)), "PEA Bourso", "Achat", "AI.PA", 1, 159, "EUR", 1, 159, 0, 0, 159, "Ordre", "", "", ""]] * 3
    tabs = {"Opérations": FakeWorksheet(ops), "Comptes": FakeWorksheet([["Compte"], ["PEA Bourso", "PEA", "Boursorama"]])}
    monkeypatch.setattr(duplicates, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(duplicates, "_worksheet", lambda sheet, name: tabs[name])
    row = lambda r: {"row": r, "date": "2025-12-10", "ticker": "AI.PA", "quantity": 1}
    assert duplicates.delete_operations("sheet", [row(2), row(4)]) == {"deleted": 2, "earliest": "2025-12-10"}
    assert tabs["Opérations"].deleted == [4, 2]
    with pytest.raises(OperationError, match="a changé"):
        duplicates.delete_operations("sheet", [{**row(3), "ticker": "NVDA"}])


def test_undated_purchase_replaced_by_dated_imports():
    from app.duplicates import find_undated_replacements

    placeholder = Entry(date(2026, 5, 5), "PEA", "Achat", "AI.PA", 3, 480.0, row=4, note="Date à préciser (achat antérieur au suivi)")
    imports = [Entry(date(2024, 3, day), "PEA", "Achat", "AI.PA", 1, 160.0, row=20 + day, note="Import avis.pdf") for day in (1, 2, 3)]
    other = Entry(date(2024, 3, 1), "PEA", "Achat", "DG.PA", 5, 500.0, row=40, note="Import avis.pdf")
    [result] = find_undated_replacements([placeholder, *imports, other], extra_rows=set())
    assert result["placeholder"]["row"] == 4 and result["covered"] == 3 and result["complete"]
    [partial] = find_undated_replacements([placeholder, *imports[:2]], extra_rows=set())
    assert partial["covered"] == 2 and not partial["complete"]  # un achat ancien manque dans les relevés
    [ignored] = find_undated_replacements([placeholder, *imports], extra_rows={21})  # doublon déjà proposé
    assert ignored["covered"] == 2


def test_approximate_dates_are_proposed_separately(monkeypatch):
    entries = [Entry(date(2025, 3, 1), "PEA", "Achat", "AI.PA", 2, 300.0, row=2, note=""),  # saisi « début mars »
               Entry(date(2025, 3, 18), "PEA", "Achat", "AI.PA", 2, 312.0, row=9, note="Import avis.pdf"),
               Entry(date(2025, 3, 18), "PEA", "Achat", "MC.PA", 2, 1380.0, row=10, note="Import avis.pdf")]
    monkeypatch.setattr(duplicates, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(duplicates, "read_entries", lambda sheet: entries)
    found = duplicates.list_duplicates("sheet")
    assert found["pairs"] == [] and found["undated"] == []
    [loose] = found["loose"]
    assert (loose["keep"]["row"], loose["extra"]["row"], loose["days"]) == (2, 9, 17)  # pas MC.PA : autre titre
