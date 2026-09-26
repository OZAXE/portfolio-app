from datetime import datetime, timezone

import pandas as pd
import pytest

from app import data
from app.data import CompanyFinancials, _fill_dividends, _normalize_minor_currency, _number


@pytest.mark.parametrize("raw,expected", [
    ("Infinity", None), ("N/A", None), (None, None), (float("nan"), None), (True, None),
    (12, 12.0), ("3.5", 3.5),
])
def test_number_filters_yahoo_text(raw, expected):
    assert _number(raw) == expected


def test_london_pence_converted_to_pounds():
    cf = CompanyFinancials(ticker="ULVR.L", currency="GBp", current_price=4664.5)
    _normalize_minor_currency(cf)
    assert cf.currency == "GBP"
    assert cf.current_price == pytest.approx(46.645)
    assert cf.price_divisor == 100


def test_major_currency_untouched():
    cf = CompanyFinancials(ticker="MC.PA", currency="EUR", current_price=396.85)
    _normalize_minor_currency(cf)
    assert cf.current_price == 396.85 and cf.price_divisor == 1.0


def test_financials_converted_to_quote_currency(monkeypatch):
    monkeypatch.setattr(data, "_fx_rate", lambda a, b: 0.8)
    cf = CompanyFinancials(ticker="SHEL.L", currency="GBP", financial_currency="USD",
                           fcf_history=[10.0, 20.0], total_debt=100.0, total_cash=50.0)
    data._convert_financials_to_quote_currency(cf)
    assert cf.fcf_history == [8.0, 16.0]
    assert cf.total_debt == 80.0 and cf.total_cash == 40.0
    assert cf.financial_currency == "GBP" and cf.converted_from_currency == "USD"


class FakeTicker:
    def __init__(self, dividends):
        self.dividends = dividends


def dividend_series(per_year: dict[int, list[float]]) -> pd.Series:
    rows = {}
    for year, amounts in per_year.items():
        for i, amount in enumerate(amounts):
            rows[pd.Timestamp(year=year, month=3 + 3 * i, day=15, tz="UTC")] = amount
    return pd.Series(rows).sort_index()


def test_dividend_growth_and_streak():
    this_year = datetime.now(timezone.utc).year
    years = {this_year - 7 + i: [0.25 * (1.05 ** i)] * 4 for i in range(7)}  # hausse de 5 % par an
    cf = CompanyFinancials(ticker="KO", currency="USD", current_price=50.0)
    _fill_dividends(cf, FakeTicker(dividend_series(years)))
    assert cf.dividend_streak == 6
    assert cf.dividend_growth_5y == pytest.approx(0.05, abs=1e-6)
    assert cf.dividend_cut is False
    assert all(y < this_year for y, _ in cf.dividend_history)  # année en cours exclue


def test_dividend_cut_detected():
    this_year = datetime.now(timezone.utc).year
    cf = CompanyFinancials(ticker="X", currency="EUR", current_price=10.0)
    _fill_dividends(cf, FakeTicker(dividend_series({this_year - 2: [1.0], this_year - 1: [0.5]})))
    assert cf.dividend_cut is True and cf.dividend_streak == 0


def test_dividends_in_pence_divided():
    this_year = datetime.now(timezone.utc).year
    cf = CompanyFinancials(ticker="ULVR.L", currency="GBP", current_price=46.0, price_divisor=100)
    _fill_dividends(cf, FakeTicker(dividend_series({this_year - 1: [40.0, 40.0]})))
    assert cf.dividend_history[-1][1] == pytest.approx(0.8)


def test_no_dividend_means_zero_yield():
    cf = CompanyFinancials(ticker="AMZN", quote_type="EQUITY", currency="USD", current_price=250.0)
    _fill_dividends(cf, FakeTicker(pd.Series(dtype=float)))
    assert cf.dividend_yield == 0.0
