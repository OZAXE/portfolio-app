from app.etf_fees_store import FEES_HEADERS, fee_rows, parse_fee_rows

STATE = {
    "etfs": {"ESE.PA": {"ter": None, "name": "BNP Paribas Easy S&P 500", "updated": "2026-09-28"},
             "URNU.L": {"ter": 0.65, "name": "Global X Uranium", "updated": "2026-09-28"}},
    "not_etf": {"AI.PA": {"updated": "2026-09-28"}},
}


def test_round_trip_through_the_sheet():
    rows = fee_rows(STATE)
    assert rows[0] == FEES_HEADERS
    assert rows[1] == ["ESE.PA", "ETF", "", "BNP Paribas Easy S&P 500", "2026-09-28"]
    assert parse_fee_rows(rows) == STATE


def test_empty_tab():
    assert parse_fee_rows([FEES_HEADERS]) == {"etfs": {}, "not_etf": {}}
