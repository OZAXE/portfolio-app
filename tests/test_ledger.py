"""Opérations lues une fois et partagées entre les calculs, relues après une écriture."""

from datetime import date

import pytest

from app import dividend_calendar, performance, realized, sheets
from app.sheets import SHEETS_EPOCH


def serial(d):
    return (d - SHEETS_EPOCH).days


TABS = {
    "Opérations": [["DATE"],
                   [serial(date(2025, 3, 1)), "PEA Bourso", "Achat", "AI.PA", 3, 160, "EUR", 1, 480, 2, 0, 482],
                   [serial(date(2025, 6, 1)), "CTO TR", "Achat", "NVDA", 2, 120, "USD", 0.9, 216, 1, 0, 217],
                   [serial(date(2025, 9, 1)), "CTO TR", "Vente", "NVDA", 1, 150, "USD", 0.9, 135, 1, 0, 134],
                   [serial(date(2025, 9, 2)), "CTO TR", "Dividende", "NVDA", 1, 0.01, "USD", 0.9, 0.01, 0, 0, 0.01]],
    "Comptes": [["Compte"], ["PEA Bourso", "PEA", "Boursorama"], ["CTO TR", "CTO", "Trade Republic"]],
    "Titres": [["TICKER"], ["AI.PA", "EPA:AI", "Air Liquide", "", "", "EUR"], ["NVDA", "NASDAQ:NVDA", "Nvidia", "", "", "USD"]],
}


class FakeWorksheet:
    def __init__(self, rows, reads):
        self.rows, self.reads = rows, reads

    def get_values(self, value_render_option=None):
        self.reads.append(1)
        return self.rows


@pytest.fixture
def reads(monkeypatch):
    counter = []
    monkeypatch.setattr(realized, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(realized, "_worksheet", lambda s, name: FakeWorksheet(TABS[name], counter))
    monkeypatch.setattr(realized, "_ledgers", {})
    return counter


def test_ledger_content(reads):
    ledger = realized.read_ledger("sheet")
    assert [op.kind for op in ledger.operations] == ["Achat", "Achat", "Vente", "Dividende"]
    assert ledger.envelopes == {"PEA Bourso": "PEA", "CTO TR": "CTO"}
    assert ledger.names["NVDA"] == "Nvidia" and ledger.currencies == {"AI.PA": "EUR", "NVDA": "USD"}


def test_read_once_then_again_after_write(reads):
    realized.read_operations("sheet")
    trades, currencies = performance.read_trades("sheet")
    assert len(reads) == 3  # Opérations, Comptes, Titres : une seule fois pour les deux calculs
    assert [(t.ticker, t.quantity, t.cash_eur) for t in trades] == [("AI.PA", 3, 482), ("NVDA", 2, 217), ("NVDA", -1, -134)]
    assert currencies["NVDA"] == "USD"
    sheets.clear_sheet_cache()  # une opération vient d'être enregistrée
    realized.read_operations("sheet")
    assert len(reads) == 6


def test_callers_cannot_alter_shared_ledger(reads):
    operations, envelopes, _ = realized.read_operations("sheet")
    operations.clear()
    envelopes.clear()
    assert len(realized.read_operations("sheet")[0]) == 4


def test_dividend_calendar_fetches_in_parallel(reads, monkeypatch):
    import app.data

    asked = []
    monkeypatch.setattr(dividend_calendar, "_open_sheet", lambda sheet_id: object())
    monkeypatch.setattr(dividend_calendar, "is_v2", lambda s: True)
    monkeypatch.setattr(dividend_calendar, "_history", lambda t, divisor: asked.append(t) or [])
    monkeypatch.setattr(app.data, "_fx_rate", lambda a, b: asked.append(a) or 0.9)
    result = dividend_calendar.dividend_calendar("sheet")
    assert sorted(asked) == ["AI.PA", "NVDA", "USD"]  # une devise demandée une seule fois
    assert result["annual_gross"] == 0
