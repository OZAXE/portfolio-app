import pytest

from app import reset
from app.operations import OperationError
from app.reset import _row_blocks, rows_to_delete

HEADER = ["Date", "Compte", "Type", "Ticker", "Quantité"] + [""] * 11


def op(account, note=""):
    return [46000, account, "Achat", "AI.PA", 1, 160, "EUR", 1, "=E2*F2*H2", 0, 0, "=I2", "Ordre", "", "", note]


ROWS = [HEADER, op("PEA Bourso"), op("CTO TR", "Import tr.csv"), op("CTO TR"), op("CTO TR", "Import releve.pdf"), [""] * 16]


def test_rows_to_delete_by_scope():
    assert rows_to_delete(ROWS, None, False) == [2, 3, 4, 5]  # ligne vide ignorée
    assert rows_to_delete(ROWS, "CTO TR", False) == [3, 4, 5]
    assert rows_to_delete(ROWS, None, True) == [3, 5]  # saisies à la main gardées
    assert rows_to_delete(ROWS, "PEA Bourso", True) == []


def test_row_blocks_bottom_up():
    assert _row_blocks([3, 4, 5, 9, 11, 12]) == [(11, 12), (9, 9), (3, 5)]


class FakeWorksheet:
    def __init__(self, title, rows, sheet_id=0):
        self.title, self.rows, self.id, self.row_count = title, rows, sheet_id, 2000
        self.cleared, self.written = [], None

    def get_values(self, value_render_option=None):
        return self.rows

    def batch_clear(self, ranges):
        self.cleared += ranges

    def update(self, range_name, values, value_input_option=None):
        self.written = values

    def add_rows(self, n):
        self.row_count += n


class FakeSheet:
    def __init__(self):
        self.tabs = {"Opérations": FakeWorksheet("Opérations", ROWS, 1), "Historique": FakeWorksheet("Historique", [["Date"], [46000]], 2)}
        self.requests = []

    def duplicate_sheet(self, source_sheet_id, new_sheet_name=None):
        source = next(t for t in self.tabs.values() if t.id == source_sheet_id)
        self.tabs[new_sheet_name] = FakeWorksheet(new_sheet_name, [list(r) for r in source.rows], 99)
        return self.tabs[new_sheet_name]

    def batch_update(self, body):
        self.requests += body["requests"]


@pytest.fixture
def sheet(monkeypatch):
    fake = FakeSheet()
    monkeypatch.setattr(reset, "_open_sheet", lambda sheet_id, write=False: fake)
    monkeypatch.setattr(reset, "_worksheet", lambda s, name: fake.tabs[name])
    monkeypatch.setattr(reset, "_find_worksheet", lambda s, name: fake.tabs.get(name))
    return fake


def test_dry_run_changes_nothing(sheet):
    assert reset.reset_operations("s", "CTO TR", False, dry_run=True) == {"count": 3, "everything": False}
    assert len(sheet.tabs) == 2 and not sheet.requests


def test_partial_reset_backs_up_then_deletes_rows(sheet):
    result = reset.reset_operations("s", "CTO TR", True)
    assert result["count"] == 2 and result["backup"].startswith("Sauvegarde opérations") and result["history_backup"] is None
    assert sheet.tabs[result["backup"]].rows == ROWS  # copie complète avant effacement
    ranges = [r["deleteDimension"]["range"] for r in sheet.requests]
    assert [(r["startIndex"], r["endIndex"]) for r in ranges] == [(4, 5), (2, 3)]  # lignes 5 puis 3


def test_full_reset_clears_operations_and_history_then_restore(sheet):
    result = reset.reset_operations("s", None, False)
    assert result["everything"] and result["history_backup"].startswith("Sauvegarde historique")
    assert sheet.tabs["Opérations"].cleared == ["A2:P6"] and sheet.tabs["Historique"].cleared == ["A2:H"]
    restored = reset.restore_backup("s", result["backup"], result["history_backup"])
    assert restored == {"restored": 5} and sheet.tabs["Opérations"].written == ROWS[1:]
    with pytest.raises(OperationError):
        reset.restore_backup("s", "Positions")  # seulement une sauvegarde
