"""Journal de trading : une thèse par titre, objectif et stop dans la devise de cotation."""

from datetime import date

import pytest

from app import journal
from app.operations import OperationError


def test_ligne_validee():
    row = journal.journal_row({"ticker": "ai.pa", "thesis": " Hydrogène et pricing power ", "target": "210,5",
                               "stop": 150, "horizon": "Long", "review": "2027-03-31"}, date(2026, 9, 30))
    assert row == ["AI.PA", "Hydrogène et pricing power", 210.5, 150.0, "Long", "2027-03-31", "", "2026-09-30"]


@pytest.mark.parametrize("payload, message", [
    ({"ticker": "AAPL", "target": 200, "stop": 250}, "sous l'objectif"),
    ({"ticker": "AAPL", "target": -5}, "positif"),
    ({"ticker": "AAPL", "thesis": "x", "horizon": "Toujours"}, "Horizon"),
    ({"ticker": "AAPL"}, "au moins"),
    ({"ticker": "AAPL", "thesis": "x", "review": "31/03/2027"}, "Date"),
])
def test_saisie_refusee(payload, message):
    with pytest.raises(OperationError, match=message):
        journal.journal_row(payload, date(2026, 9, 30))


def test_lecture_tolere_les_saisies_a_la_main():
    rows = [["AAPL", "Services", "250", "abc", "Moyen", "2027-01-15", "", "2026-09-01"], ["", "vide"]]
    assert journal.parse_journal(rows) == [{"ticker": "AAPL", "thesis": "Services", "target": 250.0, "stop": None,
                                            "horizon": "Moyen", "review": "2027-01-15", "outcome": "", "updated": "2026-09-01"}]


class FakeTab:
    def __init__(self, rows):
        self.rows = rows

    def get_values(self):
        return self.rows

    def col_values(self, n):
        return [r[n - 1] for r in self.rows]

    def update(self, range_name, values, value_input_option=None):
        self.rows[int(range_name[1:]) - 1] = values[0]

    def append_row(self, row, value_input_option=None):
        self.rows.append(row)

    def delete_rows(self, i):
        del self.rows[i - 1]


def test_une_these_par_titre(monkeypatch):
    tab = FakeTab([journal.JOURNAL_HEADERS])
    monkeypatch.setattr(journal, "_tab", lambda *a, **k: tab)
    journal.save_entry("s", {"ticker": "AAPL", "thesis": "Services"}, date(2026, 9, 1))
    entries = journal.save_entry("s", {"ticker": "aapl", "thesis": "Services + IA", "target": 260}, date(2026, 9, 30))
    assert [(e["ticker"], e["thesis"], e["target"]) for e in entries] == [("AAPL", "Services + IA", 260.0)]
    assert journal.delete_entry("s", "AAPL") == []
