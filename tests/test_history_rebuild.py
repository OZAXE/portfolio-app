"""Historique reconstitué à partir des opérations et des cours de clôture."""

from datetime import date

import pandas as pd
import pytest

from app import history
from app.history import reconstruct
from app.realized import Ledger, Operation
from app.sheets import SHEETS_EPOCH

ENVELOPES = {"PEA Bourso": "PEA", "CTO TR": "CTO"}


def buy(day, account, ticker, quantity, net):
    return Operation(day, account, "Achat", ticker, quantity, net, 0, 0, net)


def sell(day, account, ticker, quantity, net):
    return Operation(day, account, "Vente", ticker, quantity, net, 0, 0, net)


PRICES = pd.DataFrame({"AI.PA": [100.0, 110.0, 120.0], "BTC-EUR": [60000.0, 61000.0, 62000.0]},
                      index=pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04"]))


def test_values_and_invested_by_envelope():
    trades = [buy(date(2026, 3, 2), "PEA Bourso", "AI.PA", 2, 201), buy(date(2026, 3, 3), "CTO TR", "BTC-EUR", 0.01, 600)]
    rows = reconstruct(trades, ENVELOPES, PRICES, date(2026, 3, 2), date(2026, 3, 4))
    assert [d.isoformat() for d, _ in rows] == ["2026-03-02", "2026-03-03", "2026-03-04"]
    first, _, last = (t for _, t in rows)
    assert first == {"PEA": {"value": 200.0, "invested": 201.0}, "CTO": {"value": 0.0, "invested": 0.0}}
    assert last["PEA"]["value"] == 240.0 and last["CTO"] == {"value": pytest.approx(620.0), "invested": 600.0}


def test_sale_keeps_average_cost_and_weekends_skipped():
    trades = [buy(date(2026, 3, 2), "PEA Bourso", "AI.PA", 4, 400), sell(date(2026, 3, 4), "PEA Bourso", "AI.PA", 1, 119)]
    rows = reconstruct(trades, ENVELOPES, PRICES, date(2026, 3, 4), date(2026, 3, 8))  # mercredi -> dimanche
    assert [d.isoformat() for d, _ in rows] == ["2026-03-04", "2026-03-05", "2026-03-06"]
    assert rows[0][1]["PEA"] == {"value": 360.0, "invested": 300.0}  # 3 x 120 ; 3 x PRU de 100
    assert rows[-1][1]["PEA"]["value"] == 360.0  # cours du dernier jour connu


def test_unknown_price_uses_last_purchase_price():
    rows = reconstruct([buy(date(2026, 3, 2), "CTO TR", "INCONNU", 5, 50)], ENVELOPES, PRICES, date(2026, 3, 2), date(2026, 3, 2))
    assert rows[0][1]["CTO"] == {"value": 50.0, "invested": 50.0}


class FakeWorksheet:
    def __init__(self, rows):
        self.rows, self.row_count, self.cleared, self.written = rows, 1000, [], None

    def get_values(self, value_render_option=None):
        return self.rows

    def batch_clear(self, ranges):
        self.cleared += ranges

    def add_rows(self, n):
        self.row_count += n

    def update(self, range_name, values, value_input_option=None):
        self.written = values


def test_rebuild_replaces_only_the_recalculated_period(monkeypatch):
    serial = lambda d: (d - SHEETS_EPOCH).days
    ws = FakeWorksheet([["Date"], [serial(date(2026, 2, 27)), 1, 1, 1, 1], [serial(date(2026, 3, 3)), 9, 9, 9, 9]])
    ledger = Ledger([buy(date(2026, 3, 2), "PEA Bourso", "AI.PA", 2, 200)], ENVELOPES, {}, {"AI.PA": "EUR"})
    monkeypatch.setattr("app.realized.read_ledger", lambda sheet_id: ledger)
    monkeypatch.setattr("app.performance.eur_closes", lambda tickers, currencies, start: PRICES)
    monkeypatch.setattr(history, "_open_sheet", lambda sheet_id, write=False: object())
    monkeypatch.setattr(history, "_worksheet", lambda sheet, name: ws)
    result = history.rebuild_history("sheet", since=date(2026, 3, 3), today=date(2026, 3, 5))
    assert result == {"rows": 2, "from": "2026-03-03", "total": 3}
    assert [r[0] for r in ws.written] == [serial(date(2026, 2, 27)), serial(date(2026, 3, 3)), serial(date(2026, 3, 4))]
    assert ws.written[0][1:5] == [1, 1, 1, 1]  # relevé d'avant la période : gardé tel quel
    assert ws.written[1][1:3] == [220.0, 200.0] and ws.written[1][5] == "=B3+D3"  # 3 mars recalculé


def test_unsplit_restores_real_prices_before_a_free_share_attribution():
    from app.performance import unsplit

    closes = pd.Series([150.0, 152.0, 165.0], index=pd.to_datetime(["2026-06-04", "2026-06-05", "2026-06-08"]))
    splits = pd.Series([1.1], index=[pd.Timestamp("2026-06-08 09:00", tz="Europe/Paris")])
    assert unsplit(closes, splits).round(2).tolist() == [165.0, 167.2, 165.0]
