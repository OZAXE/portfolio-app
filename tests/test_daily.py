"""Variation du jour (depuis la clôture précédente) et effet de change des lignes cotées en devise."""

from datetime import date

import pandas as pd
import pytest

from app.daily import Quote, RateHistory, currency_effect, daily_summary, line_day_change, quote_change
from app.realized import Operation
from app.sheets import HoldingLine


def op(day, kind, quantity, net, account="CTO TR", ticker="AAPL"):
    return Operation(day, account, kind, ticker, quantity, net, 0.0, 0.0, net)


def test_variation_entre_les_deux_dernieres_clotures():
    closes = pd.Series([100.0, None, 98.0, 0.0, 99.96], index=pd.to_datetime(
        ["2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]))
    q = quote_change(closes)  # 99,96 / 98 - 1 = +2 %, jours vides et cours nuls écartés
    assert q.day == date(2026, 9, 30) and q.change == pytest.approx(0.02)
    assert quote_change(pd.Series([100.0], index=pd.to_datetime(["2026-09-30"]))) is None


def test_gain_du_jour_sans_et_avec_achat_dans_la_seance():
    # 10 actions valant 1 000 € après +2 % : cours de la veille 1 000 / 10 / 1,02 = 98,04 €, gain 19,61 €
    assert line_day_change(1000, 10, 0.02) == pytest.approx(19.61, abs=0.01)
    # 5 d'entre elles achetées 496 € dans la séance : 1 000 - 5 x 98,04 - 496 = 13,80 €
    assert line_day_change(1000, 10, 0.02, bought_qty=5, bought_net=496) == pytest.approx(13.80, abs=0.01)
    # 2 vendues 200 € dans la séance (il en reste 10) : 1 000 - 12 x 98,04 + 200 = 23,53 €
    assert line_day_change(1000, 10, 0.02, sold_qty=2, sold_net=200) == pytest.approx(23.53, abs=0.01)
    assert line_day_change(None, 10, 0.02) is None and line_day_change(1000, 10, None) is None


def test_effet_de_change_apple():
    # 10 Apple achetées 2 000 € quand 1 $ = 0,92 € (2 173,91 $) ; la ligne vaut 1 978 € à 0,86 € (2 300 $).
    # Au taux d'achat elle vaudrait 2 300 x 0,92 = 2 116 € : le change a coûté 1 978 x (1 - 0,92 / 0,86) = -138 €
    rates = RateHistory(pd.Series([0.92, 0.86], index=pd.to_datetime(["2025-03-03", "2026-09-30"])))
    split = currency_effect([op(date(2025, 3, 3), "Achat", 10, 2000)], rates.at, 1978, rates.last)
    assert split["effect"] == pytest.approx(-138.0, abs=0.01) and split["rate_paid"] == pytest.approx(0.92)


def test_effet_de_change_apres_une_vente():
    # Achat 1 000 € à 0,90 (1 111,11 $), achat 1 000 € à 1,00 (1 000 $), vente de la moitié : il reste
    # 1 000 € pour 1 055,56 $, taux payé 0,947 ; valeur 1 100 € à 0,95 -> 1 100 x (1 - 0,947 / 0,95) = 3,51 €
    rates = RateHistory(pd.Series([0.90, 1.00, 0.95], index=pd.to_datetime(["2025-01-02", "2025-06-02", "2026-09-30"])))
    ops = [op(date(2025, 1, 2), "Achat", 5, 1000), op(date(2025, 6, 2), "Achat", 5, 1000), op(date(2026, 1, 5), "Vente", 5, 1200)]
    split = currency_effect(ops, rates.at, 1100, rates.last)
    assert split["rate_paid"] == pytest.approx(1000 / 1055.5556, rel=1e-6)
    assert split["effect"] == pytest.approx(1100 * (1 - 0.947368 / 0.95), abs=0.01)


def test_resume_du_portefeuille():
    holdings = [
        HoldingLine("AI.PA", "AI.PA", "PEA", 1000.0, 900.0, 100.0, 0.11, None, currency="EUR", quantity=10),
        HoldingLine("AAPL", "AAPL", "CTO", 1978.0, 2000.0, -22.0, -0.01, None, currency="USD", quantity=10),
        HoldingLine("MC.PA", "MC.PA", "PEA", 500.0, 450.0, 50.0, 0.11, None, currency="EUR", quantity=1),
    ]
    ops = [op(date(2025, 3, 3), "Achat", 10, 2000)]
    quotes = {"AI.PA": Quote(date(2026, 9, 30), 0.02), "AAPL": Quote(date(2026, 9, 30), 0.01)}
    fx_quotes = {"USD": Quote(date(2026, 9, 30), -0.005)}
    rates = {"USD": RateHistory(pd.Series([0.92, 0.86], index=pd.to_datetime(["2025-03-03", "2026-09-30"])))}
    result = daily_summary(holdings, ops, {"CTO TR": "CTO"}, quotes, fx_quotes, rates)
    # Air Liquide : 1 000 x 0,02 / 1,02 = 19,61 € ; Apple : +1 % en dollars, -0,5 % pour le dollar -> +0,495 %,
    # 1 978 x 0,00495 / 1,00495 = 9,74 € ; LVMH sans cours Yahoo : signalée, pas comptée
    assert result["lines"]["PEA|AI.PA"]["change"] == pytest.approx(19.61, abs=0.01)
    assert result["lines"]["CTO|AAPL"]["change"] == pytest.approx(9.74, abs=0.01)
    assert result["total"]["change"] == pytest.approx(29.35, abs=0.01)
    assert result["total"]["missing"] == ["MC.PA"] and result["session"] == "2026-09-30"
    fx = result["currency"]
    assert fx["total"] == pytest.approx(-138.0, abs=0.01)
    # Plus-value latente -22 € = -138 € de change + 116 € venus de l'action
    assert fx["lines"]["CTO|AAPL"]["stock_effect"] == pytest.approx(116.0, abs=0.01)
    assert fx["by_currency"] == [{"currency": "USD", "effect": -138.0, "value": 1978.0}]
