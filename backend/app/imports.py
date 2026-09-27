"""
Import des relevés de courtier dans l'onglet Opérations, en deux temps : aperçu (lecture des
fichiers, tickers retrouvés, doublons signalés), puis écriture des lignes validées par l'utilisateur.

Formats reconnus :
- Trade Republic : export CSV des transactions. Achats, ventes,
  plans d'investissement et dividendes ; le reste (carte, intérêts, virements, Saveback et Stockperk
  versés en espèces) est ignoré, ainsi que la crypto, que l'appli ne suit pas ;
- Boursorama : avis d'opéré PDF, un par ordre (Espace client > Documents > Avis d'opéré).

Les montants sont en euros tels que facturés par le courtier : taux de change 1, même pour une
action américaine (Trade Republic facture en euros, comme la saisie manuelle).
"""

import base64
import csv
import io
import re
from dataclasses import asdict, dataclass
from datetime import date

from .operations import OperationError, describe_for_titres
from .realized import read_operations
from .sheets import _open_sheet, _worksheet
from .workbook import operation_row

MAX_FILES = 60
MAX_FILE_BYTES = 2_000_000


@dataclass
class ParsedOperation:
    date: str  # ISO
    type: str  # Achat / Vente / Dividende
    isin: str
    name: str
    quantity: float
    price: float  # euros par action (dividende : brut par action)
    fees: float
    taxes: float
    order_type: str
    source: str  # fichier d'origine
    ticker: str | None = None
    status: str = "new"  # new / duplicate / no_ticker


def _num(text) -> float:
    """« 1 172,50 » (Boursorama) ou « -1.00 » (Trade Republic) -> float ; vide -> 0."""
    text = str(text or "").strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)


def parse_trade_republic_csv(text: str, source: str, skipped: dict | None = None) -> list[ParsedOperation]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"category", "type", "symbol", "shares", "amount"} <= set(reader.fieldnames):
        raise OperationError(f"{source} : colonnes de l'export Trade Republic introuvables")
    operations = []
    for row in reader:
        kind = {"BUY": "Achat", "SELL": "Vente", "DIVIDEND": "Dividende"}.get(row["type"])
        shares = abs(_num(row["shares"]))  # négatif sur les ventes
        if not kind or not row["symbol"] or not shares:
            continue
        if row.get("asset_class") == "CRYPTO":
            if skipped is not None:
                skipped["crypto"] = skipped.get("crypto", 0) + 1
            continue
        amount, fee, tax = _num(row["amount"]), abs(_num(row.get("fee"))), abs(_num(row.get("tax")))
        if kind == "Dividende":
            price = amount / shares  # brut en euros par action, retenues dans les taxes
        else:
            price = _num(row["price"]) or (abs(amount) - fee) / shares
        plan = "savings plan" in (row.get("description") or "").lower()
        operations.append(ParsedOperation(
            date=row["date"], type=kind, isin=row["symbol"].strip().upper(), name=row.get("name") or row["symbol"],
            quantity=shares, price=round(price, 6), fees=fee, taxes=tax,
            order_type="" if kind == "Dividende" else "Plan d'investissement" if plan else "Ordre", source=source,
        ))
    return operations


BOURSO_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
BOURSO_ISIN = re.compile(r"Code ISIN\s*:\s*([A-Z]{2}[A-Z0-9]{9}\d)")
BOURSO_PRICE = re.compile(r"Cours ex[ée]cut[ée]\s*:\s*([\d\s.,]+)\s*EUR")
BOURSO_AMOUNTS = re.compile(r"^((?:[\d\s]+,\d{2} EUR\s*){2,4})$", re.MULTILINE)


def parse_boursorama_text(text: str, source: str) -> ParsedOperation:
    """Texte d'un avis d'opéré : sens, date d'exécution, ISIN, cours, puis la ligne des montants
    (brut, commission, frais TTF éventuels, net)."""
    if "ACHAT" in text:
        kind = "Achat"
    elif "VENTE" in text:
        kind = "Vente"
    else:
        raise OperationError(f"{source} : ni achat ni vente (avis d'opéré Boursorama attendu)")
    isin, price, amounts = BOURSO_ISIN.search(text), BOURSO_PRICE.search(text), BOURSO_AMOUNTS.findall(text)
    after_title = text[text.find("COMPTANT"):] if "COMPTANT" in text else text
    day = BOURSO_DATE.search(after_title) or BOURSO_DATE.search(text)
    if not (isin and price and amounts and day):
        raise OperationError(f"{source} : avis d'opéré illisible (ISIN, cours ou montants introuvables)")
    values = [_num(v) for v in re.findall(r"([\d\s]+,\d{2}) EUR", amounts[-1])]
    gross, commission, net = values[0], values[1], values[-1]
    ttf = values[2] if len(values) == 4 else 0.0
    if abs(gross + (commission + ttf if kind == "Achat" else -commission - ttf) - net) > 0.05:
        raise OperationError(f"{source} : montants incohérents (brut, frais et net ne concordent pas)")
    unit = _num(price.group(1))
    # Quantité lue sur l'avis ; à défaut, brut / cours (le cours affiché est arrondi : 9,99989 -> 10)
    line = re.search(r"^\s*(\d+(?:,\d+)?)\s+(.+?)\s+R[ée]f[ée]rence", text, re.MULTILINE)
    quantity = _num(line.group(1)) if line else round(gross / unit, 6) if unit else 0
    if not line and abs(quantity - round(quantity)) < 0.01:
        quantity = float(round(quantity))
    return ParsedOperation(
        date=f"{day.group(3)}-{day.group(2)}-{day.group(1)}", type=kind, isin=isin.group(1),
        name=line.group(2).strip() if line else isin.group(1),
        quantity=quantity, price=unit, fees=commission, taxes=ttf,
        order_type="Ordre", source=source,
    )


def parse_file(name: str, content: bytes, skipped: dict | None = None) -> list[ParsedOperation]:
    if len(content) > MAX_FILE_BYTES:
        raise OperationError(f"{name} : fichier trop gros")
    if content[:4] == b"%PDF":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
        return [parse_boursorama_text(text, name)]
    return parse_trade_republic_csv(content.decode("utf-8-sig", errors="replace"), name, skipped)


# Codes de place OpenFIGI -> suffixe Yahoo, par ordre de préférence
FIGI_EXCHANGES = {"US": "", "FP": ".PA", "NA": ".AS", "GY": ".DE", "BB": ".BR", "IM": ".MI", "SM": ".MC", "SW": ".SW", "LN": ".L"}


def _figi_ticker(isin: str) -> str | None:
    """Repli quand Yahoo ne connaît pas l'ISIN (Alphabet classe A) : API publique OpenFIGI."""
    import requests

    try:
        response = requests.post("https://api.openfigi.com/v3/mapping", json=[{"idType": "ID_ISIN", "idValue": isin}], timeout=20)
        data = response.json()[0].get("data", [])
    except Exception:
        return None
    listings = [d for d in data if d.get("exchCode") in FIGI_EXCHANGES and d.get("ticker")]
    listings.sort(key=lambda d: list(FIGI_EXCHANGES).index(d["exchCode"]))
    return listings[0]["ticker"].replace("/", "-") + FIGI_EXCHANGES[listings[0]["exchCode"]] if listings else None


def find_ticker(isin: str, known: dict[str, str]) -> str | None:
    """Ticker Yahoo d'un ISIN : déjà vu (fichier ISIN du screener), sinon recherche Yahoo en
    préférant Paris puis les places européennes (cotation en euros), sinon OpenFIGI."""
    if isin in known:
        return known[isin]
    import yfinance as yf

    try:
        quotes = yf.Search(isin, max_results=8, news_count=0).quotes
    except Exception:
        quotes = []
    quotes = [q for q in quotes if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF")]
    preference = ["PAR", "AMS", "GER", "BRU", "MIL", "NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "LSE"]
    quotes.sort(key=lambda q: preference.index(q.get("exchange")) if q.get("exchange") in preference else len(preference))
    return quotes[0]["symbol"] if quotes else _figi_ticker(isin)


def _duplicate_key(day: str, account: str, kind: str, quantity: float) -> tuple:
    # Sans le ticker : une ligne saisie à la main sous un autre ticker (TNO.PA / TNOW.MI) reste un doublon
    return (day, account, kind, round(quantity, 4))


def preview_import(sheet_id: str, account: str, files: list[dict], known_isins: dict[str, str]) -> dict:
    """files : [{name, content (base64)}]. Rien n'est écrit."""
    if not files or len(files) > MAX_FILES:
        raise OperationError(f"Entre 1 et {MAX_FILES} fichiers")
    parsed, errors, skipped = [], [], {}
    for f in files:
        try:
            parsed += parse_file(f["name"], base64.b64decode(f["content"]), skipped)
        except OperationError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"{f.get('name')} : lecture impossible ({e})")

    existing, _, _ = read_operations(sheet_id)
    seen = {_duplicate_key(op.day.isoformat(), op.account, op.kind, op.quantity) for op in existing}
    tickers: dict[str, str | None] = {}
    for op in sorted(parsed, key=lambda o: o.date):
        if op.isin not in tickers:
            tickers[op.isin] = find_ticker(op.isin, known_isins)
        op.ticker = tickers[op.isin]
        key = _duplicate_key(op.date, account, op.type, op.quantity)
        op.status = "duplicate" if key in seen else "new" if op.ticker else "no_ticker"
        seen.add(key)  # le même ordre présent dans deux fichiers
    operations = [asdict(op) for op in sorted(parsed, key=lambda o: o.date)]
    if skipped.get("crypto"):
        errors.append(f"{skipped['crypto']} opérations crypto ignorées (l'appli ne suit pas la crypto)")
    return {"operations": operations, "errors": errors,
            "counts": {s: sum(o["status"] == s for o in operations) for s in ("new", "duplicate", "no_ticker")}}


def write_import(sheet_id: str, account: str, operations: list[dict], titres_info=describe_for_titres) -> dict:
    """Écrit d'un coup les opérations validées (et les nouveaux titres dans l'onglet Titres)."""
    from .operations import read_settings

    settings = read_settings(sheet_id)
    if account not in {a["name"] for a in settings["accounts"]}:
        raise OperationError("Compte inconnu : ajoute-le d'abord dans l'onglet Comptes du Sheet")
    clean = []
    for op in operations:
        ticker = str(op.get("ticker") or "").strip().upper()
        if not ticker or op.get("type") not in ("Achat", "Vente", "Dividende"):
            raise OperationError("Chaque opération doit avoir un ticker et un type")
        clean.append({
            "date": date.fromisoformat(op["date"]), "account": account, "type": op["type"], "ticker": ticker,
            "quantity": float(op["quantity"]), "price": float(op["price"]), "currency": "EUR", "fx": 1,
            "fees": float(op.get("fees") or 0), "taxes": float(op.get("taxes") or 0),
            "order_type": op.get("order_type") or ("" if op["type"] == "Dividende" else "Ordre"), "why": "", "term": "", "note": f"Import {op.get('source', '')}".strip(),
        })
    if not clean:
        return {"written": 0, "new_tickers": []}
    clean.sort(key=lambda o: o["date"])

    sheet = _open_sheet(sheet_id, write=True)
    known = {t["ticker"].upper() for t in settings["titres"]}
    new_tickers = sorted({op["ticker"] for op in clean} - known)
    if new_tickers:
        titres = _worksheet(sheet, "Titres")
        start = len(titres.col_values(1)) + 1
        rows = []
        for ticker in new_tickers:
            try:
                info = titres_info(ticker)
                rows.append([ticker, info.google, info.name, "", "", info.currency, info.kind])
            except OperationError:
                rows.append([ticker, "", ticker, "", "", "EUR", "Action"])  # à compléter à la main
        titres.update(range_name=f"A{start}", values=rows)

    ops = _worksheet(sheet, "Opérations")
    start = len(ops.col_values(1)) + 1
    ops.update(range_name=f"A{start}", values=[operation_row(op, start + i) for i, op in enumerate(clean)],
               value_input_option="USER_ENTERED")
    return {"written": len(clean), "new_tickers": new_tickers}
