from datetime import date

import pandas as pd
import pytest

from app.performance import Trade, _eur_prices, compute_performance

DAYS = pd.to_datetime(["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07"])


def test_portfolio_and_ghost_benchmark():
    prices = pd.DataFrame({"AAA": [10.0, 10.0, 12.0, 11.0]}, index=DAYS)
    bench = pd.Series([100.0, 100.0, 105.0, 110.0], index=DAYS)
    trades = [Trade(date(2026, 5, 5), "AAA", 10, 100.0)]  # 100 € investis le 05/05
    points = compute_performance(trades, prices, bench)
    assert points[0] == {"date": "2026-05-05", "value": 100.0, "invested": 100.0, "benchmark": 100.0}
    assert points[-1] == {"date": "2026-05-07", "value": 110.0, "invested": 100.0, "benchmark": 110.0}


def test_weekend_trade_counted_next_trading_day():
    prices = pd.DataFrame({"AAA": [10.0, 10.0]}, index=pd.to_datetime(["2026-05-08", "2026-05-11"]))
    bench = pd.Series([50.0, 50.0], index=prices.index)
    points = compute_performance([Trade(date(2026, 5, 9), "AAA", 1, 10.0)], prices, bench)
    assert [p["date"] for p in points] == ["2026-05-11"]


def test_sale_reduces_holdings_and_invested():
    prices = pd.DataFrame({"AAA": [10.0, 10.0, 10.0, 10.0]}, index=DAYS)
    bench = pd.Series([10.0] * 4, index=DAYS)
    trades = [Trade(date(2026, 5, 4), "AAA", 10, 100.0), Trade(date(2026, 5, 6), "AAA", -4, -40.0)]
    last = compute_performance(trades, prices, bench)[-1]
    assert last["value"] == 60.0 and last["invested"] == 60.0 and last["benchmark"] == 60.0


def test_prices_converted_to_euros():
    closes = pd.DataFrame({"US": [100.0], "UK": [2500.0], "FR": [50.0]}, index=DAYS[:1])
    fx = pd.DataFrame({"USD": [0.9], "GBP": [1.2]}, index=DAYS[:1])
    eur = _eur_prices(closes, fx, {"US": "USD", "UK": "GBp", "FR": "EUR"})
    assert eur.iloc[0].tolist() == pytest.approx([90.0, 30.0, 50.0])
