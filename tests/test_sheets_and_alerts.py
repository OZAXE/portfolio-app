from app.alerts import compute_alerts
from app.sectors import is_balance_sheet_business, normalize_sector
from app.sheets import google_to_yahoo, parse_history, parse_holdings, parse_savings


def test_google_to_yahoo_tickers():
    assert google_to_yahoo("EPA:AI") == "AI.PA"
    assert google_to_yahoo("NASDAQ:NVDA") == "NVDA"
    assert google_to_yahoo("LON:URNU") == "URNU.L"
    assert google_to_yahoo("XETRA:SAP") == "SAP.DE"
    assert google_to_yahoo("MARS:XYZ") is None


def test_holdings_envelope_merged_from_header():
    # "PEA" en A1 fusionné sur les lignes suivantes : seules les lignes CTO portent leur enveloppe
    rows = [
        ["PEA", "Action", "Total", "Total investi", "PV", "PV %", "Secteur"],
        ["", "EPA:AI", 1172.5, 1192.31, -19.81, -0.0166, "Industrie"],
        ["", "EPA:BN", 119.12, 136.9, -17.78, -0.13, "Consommation"],
        ["CTO", "NASDAQ:NVDA", 191.69, 153.43, 38.26, 0.25, "Technologie"],
        ["Total", "", "", ""],
    ]
    holdings = parse_holdings(rows)
    assert [(h.envelope, h.yahoo_ticker) for h in holdings] == [("PEA", "AI.PA"), ("PEA", "BN.PA"), ("CTO", "NVDA")]


def test_history_parsed_by_column_and_sorted():
    rows = [["Date", 46290, 46147], [], ["PEA", 0.0067, 0.0384], [], ["", 2038.85, 1698.4],
            [], ["CTO", 0.185, 0.1228], [], ["", 521.62, 479.48], [], ["Total", 0.0386, 0.0565], [], ["", 2560.47, 2178.0]]
    points = parse_history(rows)
    assert [p.date for p in points] == ["2026-05-05", "2026-09-25"]
    assert points[-1].total_value == 2560.47


def test_savings_ignore_header():
    assert parse_savings([["", "Somme"], ["Livret A", 3600.7]]) == [{"name": "Livret A", "amount": 3600.7}]


def test_sector_families():
    assert normalize_sector("Consumer Defensive") == "Consommation"
    assert normalize_sector("Utilities - Regulated Electric") == "Services publics"
    assert normalize_sector(None, "Banks - Regional") == "Finance"
    assert is_balance_sheet_business("Insurance - Life")
    assert not is_balance_sheet_business("Credit Services")


def stock(ticker, **fields):
    return {"ticker": ticker, "name": ticker, **fields}


def test_alerts_events_and_opportunities():
    screener = {"stocks": [
        stock("BN.PA", price=59, prev_price=60, margin_of_safety=36, dcf_reliable=True,
              prev_margin_of_safety=15, prev_dcf_reliable=True),
        stock("AI.PA", price=150, prev_price=167, quality_score=10, prev_quality_score=14),
        stock("SAP.DE", price=200, prev_price=201, margin_of_safety=25, dcf_reliable=True,
              prev_margin_of_safety=26, prev_dcf_reliable=True),
        stock("TTE.PA", price=60, prev_price=60, dividend_cut=True, prev_dividend_cut=False),
        stock("OTHER", price=10, prev_price=20),  # ni position ni watchlist
    ]}
    investors = {"funds": [
        {"manager": "Warren Buffett", "new_filing": True,
         "positions": [{"ticker": "V", "name": "Visa", "change": "renforcée", "change_pct": 0.12}], "sold": []},
        {"manager": "Terry Smith", "new_filing": False,
         "positions": [{"ticker": "V", "name": "Visa", "change": "nouvelle", "change_pct": None}], "sold": []},
    ]}
    result = compute_alerts({"BN.PA", "AI.PA", "TTE.PA", "V"}, {"SAP.DE"}, screener, investors)
    types = sorted((e["ticker"], e["type"]) for e in result["events"])
    assert types == [("AI.PA", "baisse"), ("AI.PA", "score"), ("BN.PA", "sous-évaluée"),
                     ("TTE.PA", "dividende"), ("V", "super investisseur")]
    assert [o["ticker"] for o in result["opportunities"]] == ["BN.PA", "SAP.DE"]


def test_no_alert_burst_on_first_night():
    # Sans valeurs de la veille (première nuit), pas d'événement de franchissement
    screener = {"stocks": [stock("BN.PA", margin_of_safety=36, dcf_reliable=True, dividend_cut=True)]}
    assert compute_alerts({"BN.PA"}, set(), screener, None)["events"] == []
