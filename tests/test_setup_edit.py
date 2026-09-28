import pytest

from app import setup_edit
from app.operations import OperationError
from app.setup_edit import validate_accounts, validate_allocation, validate_fees


def test_accounts_any_bank():
    rows = validate_accounts([{"name": "PEA Fortuneo", "envelope": "pea", "broker": "Fortuneo"},
                              {"name": " CTO  Degiro ", "envelope": "CTO", "broker": "Degiro"}], used=set())
    assert rows == [["PEA Fortuneo", "PEA", "Fortuneo"], ["CTO Degiro", "CTO", "Degiro"]]


@pytest.mark.parametrize("accounts, used, message", [
    ([{"name": "Livret", "envelope": "LEP", "broker": "Banque"}], set(), "PEA ou CTO"),
    ([{"name": "A", "envelope": "PEA", "broker": "X"}, {"name": "a", "envelope": "CTO", "broker": "X"}], set(), "Deux comptes"),
    ([{"name": "PEA Fortuneo", "envelope": "PEA", "broker": "Fortuneo"}], {"PEA Boursorama"}, "a des opérations"),
    ([{"name": "=IMPORTXML()", "envelope": "PEA", "broker": "X"}], set(), "invalide"),
    ([], set(), "au moins un compte"),
])
def test_accounts_refused(accounts, used, message):
    with pytest.raises(OperationError, match=message):
        validate_accounts(accounts, used)


def test_fees():
    rows = validate_fees([{"broker": "Degiro", "order_type": "Ordre", "fixed": "2", "percent": 0, "minimum": "", "fx_percent": 0.0025, "note": "Euronext"}])
    assert rows == [["Degiro", "Ordre", 2.0, 0.0, 0.0, 0.0025, "Euronext"]]
    with pytest.raises(OperationError, match="pourcentage"):
        validate_fees([{"broker": "X", "order_type": "Ordre", "percent": 0.5}])  # 50 % : erreur de saisie
    with pytest.raises(OperationError, match="deux grilles"):
        validate_fees([{"broker": "X", "order_type": "Ordre"}, {"broker": "x", "order_type": "Ordre"}])


def test_allocation():
    rows, assigned = validate_allocation([{"pocket": "ETF Monde", "target": 0.6}, {"pocket": "Actions", "target": 0.4}],
                                         {"cw8.pa": "ETF Monde", "AI.PA": "Actions", "NVDA": ""})
    assert rows == [["ETF Monde", 0.6], ["Actions", 0.4]]
    assert assigned == {"CW8.PA": "ETF Monde", "AI.PA": "Actions", "NVDA": ""}
    with pytest.raises(OperationError, match="100 %"):
        validate_allocation([{"pocket": "ETF", "target": 0.5}], {})
    with pytest.raises(OperationError, match="sans cible"):
        validate_allocation([{"pocket": "ETF", "target": 1}], {"AI.PA": "Actions"})
    assert validate_allocation([], {}) == ([], {})  # plus aucune cible


class FakeWorksheet:
    def __init__(self, rows):
        self.rows, self.cleared, self.written, self.batch = rows, [], [], []

    def get_values(self, value_render_option=None):
        return self.rows

    def col_values(self, col):
        return [r[col - 1] if len(r) >= col else "" for r in self.rows]

    def batch_clear(self, ranges):
        self.cleared += ranges

    def update(self, range_name, values, value_input_option=None):
        self.written.append((range_name, values))

    def batch_update(self, updates, value_input_option=None):
        self.batch += updates


def test_save_allocation_writes_targets_and_pockets(monkeypatch):
    tabs = {"Allocation": FakeWorksheet([["Poche", "Cible %"]]),
            "Titres": FakeWorksheet([["Ticker"], ["AI.PA"], ["CW8.PA"]])}
    monkeypatch.setattr(setup_edit, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(setup_edit, "_find_worksheet", lambda s, name: tabs.get(name))
    monkeypatch.setattr(setup_edit, "_worksheet", lambda s, name: tabs[name])
    setup_edit.save_allocation("sheet", [{"pocket": "ETF Monde", "target": 1}], {"CW8.PA": "ETF Monde", "INCONNU": "ETF Monde"})
    assert tabs["Allocation"].cleared == ["A2:B"] and tabs["Allocation"].written == [("A2", [["ETF Monde", 1.0]])]
    assert tabs["Titres"].batch == [{"range": "H3", "values": [["ETF Monde"]]}]
