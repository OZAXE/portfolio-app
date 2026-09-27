import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "screener"))
from etf_lookthrough import name_key, nasdaq_rows, parse_spdr, screener_index_rows, summarize  # noqa: E402


def test_name_key_matches_across_sources():
    assert name_key("NVIDIA Corporation") == name_key("Nvidia Corp") == "nvidia"
    assert name_key("Alphabet Inc. Class A") == name_key("Alphabet Inc. Class C") == "alphabet"
    assert name_key("LVMH Moët Hennessy - Louis Vuitton, Société Européenne") == name_key("LVMH Moet Hennessy Louis Vuitton SE")
    assert name_key("Siemens Aktiengesellschaft") == "siemens"


def test_summarize_weights_countries_and_sectors():
    rows = [
        {"name": "Apple Inc.", "weight": 6.0, "country": "United States", "sector": "Information Technology"},
        {"name": "Alphabet Inc. Class A", "weight": 2.0, "country": "United States", "sector": "Communication Services"},
        {"name": "Alphabet Inc. Class C", "weight": 1.0, "country": "United States", "sector": "Communication Services"},
        {"name": "Nestle SA", "weight": 1.0, "country": "Switzerland", "sector": "Consumer Staples"},
        {"name": "Cash", "weight": 0, "country": "United States", "sector": None},
    ]
    result = summarize(rows)
    assert result["countries"] == {"États-Unis": 0.9, "Suisse": 0.1}
    assert result["sectors"] == {"Technologie": 0.6, "Communication": 0.3, "Consommation": 0.1}
    assert result["holdings"][1] == ["Alphabet Inc.", "alphabet", 0.3]  # deux classes regroupées
    assert result["count"] == 4


def test_parse_spdr_file():
    header = [["Fund Name:", "SPDR MSCI World"], ["ISIN:", "IE00BFY0GT14"], ["Ticker Symbol:", "SPPW GY"],
              ["Holdings As Of:", "24-Sep-2026"], [None, None]]
    columns = ["ISIN", "SEDOL", "Security Name", "Currency", "Number of Shares", "Percent of Fund",
               "Trade Country Name", "Local Price", "Sector Classification", "Industry Classification", "Base Market Value"]
    lines = [["US67066G1040", "2379504", "NVIDIA Corporation", "USD", 10, 5.68, "United States", 224.5, "Information Technology", "Semis", 1],
             ["", "", "US Dollar", "USD", 1, 0.12, None, 1, None, None, 1],  # liquidités : écartées
             ["Holdings are subject to change", None, None, None, None, "n/a", None, None, None, None, None]]
    frame = pd.DataFrame([row + [None] * (11 - len(row)) for row in header] + [columns] + lines)
    buffer = io.BytesIO()
    frame.to_excel(buffer, header=False, index=False)
    rows, as_of = parse_spdr(buffer.getvalue())
    assert as_of == "24-Sep-2026"
    assert rows == [{"name": "NVIDIA Corporation", "weight": 5.68, "country": "United States", "sector": "Information Technology"}]


def test_index_from_screener_members():
    stocks = [
        {"name": "TotalEnergies SE", "indices": ["CAC 40"], "market_cap_eur": 3e11, "country": "France", "sector": "Énergie"},
        {"name": "Air Liquide", "indices": ["CAC 40", "EURO STOXX 50"], "market_cap_eur": 1e11, "country": "France", "sector": "Matériaux"},
        {"name": "Siemens", "indices": ["DAX"], "market_cap_eur": 2e11, "country": "Allemagne", "sector": "Industrie"},
    ]
    result = summarize(screener_index_rows(stocks, "CAC 40"))
    assert result["sectors"] == {"Énergie": 0.75, "Matériaux": 0.25} and result["countries"] == {"France": 1.0}


def test_nasdaq_share_classes_counted_once():
    payload = {"data": {"data": {"rows": [
        {"companyName": "Alphabet Inc. Class A Common Stock", "marketCap": "3,000"},
        {"companyName": "Alphabet Inc. Class C Capital Stock", "marketCap": "3,000"},
        {"companyName": "ASML Holding N.V. New York Registry Shares", "marketCap": "1,000"},
    ]}}}
    rows = nasdaq_rows(payload, {"asml": {"country": "Netherlands", "sector": "Information Technology"}})
    assert [r["weight"] for r in rows] == [3000.0, 1000.0]
    assert rows[1]["country"] == "Netherlands"
    assert summarize(rows)["countries"] == pytest.approx({"États-Unis": 0.75, "Pays-Bas": 0.25})
