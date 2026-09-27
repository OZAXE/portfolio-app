import base64
from datetime import date

import pytest

from app import imports
from app.imports import parse_boursorama_text, parse_trade_republic_csv, preview_import
from app.operations import OperationError
from app.realized import Operation

TR_CSV = '''"datetime","date","account_type","category","type","asset_class","name","symbol","shares","price","amount","fee","tax","currency","original_amount","original_currency","fx_rate","description","transaction_id","counterparty_name","counterparty_iban","payment_reference","mcc_code"
"2026-06-01T03:58:30Z","2026-06-01","DEFAULT","CASH","INTEREST_PAYMENT","","","","","","0.030000","","","EUR","","","","Interest payment","id1","","","",""
"2026-06-01T08:29:55Z","2026-06-01","DEFAULT","CASH","DIVIDEND","STOCK","Visa","US92826C8394","0.5000000000","","0.300000","","-0.12","EUR","0.35","USD","0.86","Cash Dividend for ISIN US92826C8394","id2","","","",""
"2026-08-18T13:57:56Z","2026-08-18","DEFAULT","CASH","CARD_TRANSACTION","","CAFE","","","","-4.000000","","","EUR","","","","CAFE","id3","","","","5813"
"2026-08-24T14:13:52Z","2026-08-24","DEFAULT","TRADING","BUY","STOCK","NVIDIA","US67066G1040","0.0055670000","179.6000000000","-1.00","","","EUR","","","","Savings plan execution US67066G1040 NVIDIA CORP., quantity: 0.005567","id4","","","",""
"2026-09-02T10:00:00Z","2026-09-02","DEFAULT","TRADING","SELL","STOCK","Visa","US92826C8394","0.2000000000","300.0000000000","59.00","-1.00","","EUR","","","","Market order","id5","","","",""
'''

BOURSO_BUY = """OPERATION DE BOURSE
le 12/05/2026
40618 80348 00000000000 Compte PEA
ACHAT COMPTANT
ACTION
12/05/2026
14:00:38
7 BNPP EASY S&P 500 UC.EUR ETF Référence : 010164951494
Code ISIN : FR0011550185 Cours exécuté : 31,7941 EUR
Lieu d'exécution : EURONEXT PARIS
222,56 EUR 1,11 EUR  223,67 EUR
"""

BOURSO_BUY_TTF = """ACHAT COMPTANT
01/10/2025
2 AIR LIQUIDE Référence : 010160000000
Code ISIN : FR0000120073 Cours exécuté : 176,02 EUR
352,04 EUR 1,76 EUR 1,41 EUR 355,21 EUR
"""

BOURSO_SELL = """VENTE COMPTANT
23/03/2026
5 TOTALENERGIES SE Référence : 010160000001
Code ISIN : FR0000120271 Cours exécuté : 76,48 EUR
382,40 EUR 1,91 EUR  380,49 EUR
"""


def test_trade_republic_csv_keeps_trades_and_dividends():
    ops = parse_trade_republic_csv(TR_CSV, "tr.csv")
    assert [(o.type, o.isin) for o in ops] == [("Dividende", "US92826C8394"), ("Achat", "US67066G1040"), ("Vente", "US92826C8394")]
    dividend, plan, sale = ops
    assert dividend.price == pytest.approx(0.6) and dividend.taxes == 0.12 and dividend.order_type == ""
    assert plan.order_type == "Plan d'investissement" and plan.quantity == 0.005567 and plan.price == 179.6
    assert sale.fees == 1.0 and sale.order_type == "Ordre"


def test_trade_republic_wrong_file():
    with pytest.raises(OperationError):
        parse_trade_republic_csv("a;b;c\n1;2;3\n", "autre.csv")


def test_boursorama_buy_without_and_with_ttf():
    op = parse_boursorama_text(BOURSO_BUY, "avis.pdf")
    assert (op.date, op.type, op.isin, op.quantity, op.price, op.fees, op.taxes) == ("2026-05-12", "Achat", "FR0011550185", 7, 31.7941, 1.11, 0)
    op = parse_boursorama_text(BOURSO_BUY_TTF, "avis.pdf")
    assert (op.quantity, op.fees, op.taxes, op.name) == (2, 1.76, 1.41, "AIR LIQUIDE")  # TTF dans les taxes


def test_boursorama_sell():
    op = parse_boursorama_text(BOURSO_SELL, "avis.pdf")
    assert (op.type, op.quantity, op.fees, op.date) == ("Vente", 5, 1.91, "2026-03-23")


def test_boursorama_inconsistent_amounts_rejected():
    with pytest.raises(OperationError):
        parse_boursorama_text(BOURSO_SELL.replace("380,49", "390,49"), "avis.pdf")


def test_preview_flags_duplicates_and_missing_tickers(monkeypatch):
    existing = [Operation(date(2026, 8, 24), "CTO Trade Republic", "Achat", "NVDA", 0.005567, 1.0, 0, 0, 1.0)]
    monkeypatch.setattr(imports, "read_operations", lambda sheet_id: (existing, {}, {}))
    monkeypatch.setattr(imports, "find_ticker", lambda isin, known: {"US67066G1040": "NVDA"}.get(isin))
    files = [{"name": "tr.csv", "content": base64.b64encode(TR_CSV.encode()).decode()}]
    result = preview_import("sheet", "CTO Trade Republic", files, {})
    statuses = {(o["type"], o["isin"]): o["status"] for o in result["operations"]}
    assert statuses[("Achat", "US67066G1040")] == "duplicate"  # déjà saisi à la main
    assert statuses[("Dividende", "US92826C8394")] == "no_ticker"
    assert result["counts"] == {"new": 0, "duplicate": 1, "no_ticker": 2}
