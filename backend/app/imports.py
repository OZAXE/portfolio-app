"""
Import des relevés de courtier dans l'onglet Opérations, en deux temps : aperçu (lecture des
fichiers, tickers retrouvés, doublons signalés), puis écriture des lignes validées par l'utilisateur.

Formats reconnus :
- Trade Republic : export CSV des transactions. Achats, ventes,
  plans d'investissement, dividendes et actions gratuites, crypto comprise (ticker Yahoo BTC-EUR, ETH-EUR...) ; le reste
  (carte, intérêts, virements, Saveback et Stockperk versés en espèces) est ignoré. La colonne
  account_type (PEA ou DEFAULT pour le compte-titres) range chaque opération dans la bonne enveloppe ;
- Trade Republic : relevé de compte PDF (Profil > Documents). Une section par compte (« Compte
  courant » pour le CTO, « Compte PEA ») : chaque opération est rangée dans le compte de la même
  enveloppe. Le relevé ne donne qu'un montant par ligne : les frais d'un ordre sont comptés 1 €
  (tarif Trade Republic, 0 € pour un plan d'investissement) et un dividende est enregistré net
  de la retenue à la source, pour la quantité détenue d'après les achats du relevé ;
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
from .realized import read_cash, read_operations
from .sheets import _open_sheet, _worksheet
from .workbook import CASH_TYPES, SHARE_TYPES, cash_row, ensure_operation_types, operation_row

MAX_FILES = 60
MAX_FILE_BYTES = 2_000_000


@dataclass
class ParsedOperation:
    date: str  # ISO
    type: str  # Achat / Vente / Dividende / Actions gratuites / Versement...
    isin: str
    name: str
    quantity: float
    price: float  # euros par action (dividende : brut par action)
    fees: float
    taxes: float
    order_type: str
    source: str  # fichier d'origine
    ticker: str | None = None
    status: str = "new"  # new / duplicate / no_ticker / no_account
    envelope: str | None = None  # PEA / CTO quand le fichier l'indique (relevé Trade Republic)
    account: str | None = None  # compte où l'opération sera écrite


# Crypto chez Trade Republic : pseudo-ISIN XF000BTC0017 (relevé PDF) ou symbole BTC (export CSV)
CRYPTO_ISIN = re.compile(r"XF000([A-Z]{2,6}?)\d+")


def crypto_ticker(code: str) -> str | None:
    """Ticker Yahoo en euros d'une crypto : XF000BTC0017 ou BTC -> BTC-EUR."""
    code = str(code or "").strip().upper()
    match = CRYPTO_ISIN.fullmatch(code)
    symbol = match.group(1) if match else code if re.fullmatch(r"[A-Z]{2,6}", code) else None
    return f"{symbol}-EUR" if symbol else None


def _num(text) -> float:
    """« 1 172,50 » (Boursorama) ou « -1.00 » (Trade Republic) -> float ; vide -> 0."""
    text = str(text or "").strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)


# Colonne account_type de l'export : PEA, ou DEFAULT pour le compte-titres ordinaire (CTO)
TR_CSV_ENVELOPES = {"PEA": "PEA", "DEFAULT": "CTO"}


def parse_trade_republic_csv(text: str, source: str, skipped: dict | None = None) -> list[ParsedOperation]:
    skipped = skipped if skipped is not None else {}
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"category", "type", "symbol", "shares", "amount"} <= set(reader.fieldnames):
        raise OperationError(f"{source} : colonnes de l'export Trade Republic introuvables")
    operations = []
    cash: dict[tuple[str, str | None, str], list[float]] = {}  # (jour, enveloppe, type) -> [montant, nombre, taxes]
    for row in reader:
        if row["category"] == "CORPORATE_ACTION":
            # Actions gratuites (Air Liquide 1 pour 10 en juin 2025 : shares = actions reçues, 0,2 pour 2
            # détenues) importées ; le reste (divisions, rompus...) au format inconnu, à saisir à la main
            shares = _num(row["shares"])
            if row["type"] == "BONUS_ISSUE" and shares > 0 and row["symbol"]:
                operations.append(ParsedOperation(
                    date=row["date"], type="Actions gratuites", isin=row["symbol"].strip().upper(),
                    name=row.get("name") or row["symbol"], quantity=shares, price=0.0, fees=0.0, taxes=0.0,
                    order_type="", source=source, envelope=TR_CSV_ENVELOPES.get((row.get("account_type") or "").strip().upper())))
            else:
                skipped["corporate"] = skipped.get("corporate", 0) + 1
            continue
        if row["category"] == "CASH" and row["type"] != "DIVIDEND":
            _add_cash_row(cash, row)
            continue
        kind = {"BUY": "Achat", "SELL": "Vente", "DIVIDEND": "Dividende"}.get(row["type"])
        shares = abs(_num(row["shares"]))  # négatif sur les ventes
        if not kind or not row["symbol"] or not shares:
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
            ticker=crypto_ticker(row["symbol"]) if row.get("asset_class") == "CRYPTO" else None,
            # Sans cette colonne (ancien export), l'opération va dans le compte choisi
            envelope=TR_CSV_ENVELOPES.get((row.get("account_type") or "").strip().upper()),
        ))
    for (day, envelope, kind), (amount, count, taxes) in sorted(cash.items(), key=lambda kv: kv[0][0]):
        if round(amount, 2) > 0:
            operations.append(ParsedOperation(
                date=day, type=kind, isin="", name=f"Espèces ({count} mouvement{'s' if count > 1 else ''})",
                quantity=1, price=round(amount, 2), fees=0, taxes=round(taxes, 2), order_type="", source=source,
                envelope=envelope))
    return operations


def _add_cash_row(cash: dict, row: dict) -> None:
    """Mouvement d'espèces du compte Trade Republic, regroupé par jour, enveloppe et sens : le compte titres
    est aussi un compte courant (paiements par carte, virements), une ligne par café remplirait l'onglet.
    Une réimportation de la même période redonne les mêmes totaux quotidiens, reconnus comme doublons."""
    amount, tax = _num(row["amount"]), 0.0
    if row["type"] == "INTEREST_PAYMENT":
        # Brut gardé, prélèvements à part (colonne Taxes) : l'estimation d'impôt en a besoin
        kind, tax = "Intérêts", abs(_num(row.get("tax")))
    elif amount > 0:
        kind = "Versement"
    elif amount < 0:
        kind = "Retrait"
    else:
        return
    key = (row["date"], TR_CSV_ENVELOPES.get((row.get("account_type") or "").strip().upper()), kind)
    total = cash.setdefault(key, [0.0, 0, 0.0])
    total[0] += abs(amount)
    total[1] += 1
    total[2] += tax


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


# --- Relevé de compte PDF de Trade Republic ---
TR_MONTHS = {"janv": 1, "févr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6, "juil": 7, "août": 8,
             "sept": 9, "oct": 10, "nov": 11, "déc": 12}
TR_DATE = re.compile(r"\b(\d{2}) (janv|févr|mars|avr|mai|juin|juil|août|sept|oct|nov|déc)\.? (\d{4})\b")
TR_ISIN = r"([A-Z]{2}[A-Z0-9]{9}\d)"
TR_TRADE = re.compile(r"(Buy trade|Sell trade|Savings plan execution) " + TR_ISIN + r" (.+?), quantity: ([\d.]+)")
TR_DIVIDEND = re.compile(r"Cash Dividend for ISIN " + TR_ISIN)
TR_AMOUNT = re.compile(r"(-?\d{1,3}(?:\.\d{3})+,\d{2}|-?\d+,\d{2}) ?€")  # 11705,27 ou 1.242,21, jamais d'espace
TR_PAGE_HEADER = re.compile(r"TRADE REPUBLIC BANK GMBH.*?Page\s+\d+\s+de\s+\d+", re.DOTALL | re.IGNORECASE)
TR_ORDER_FEE = 1.0  # frais d'un ordre Trade Republic ; plans d'investissement sans frais


def parse_trade_republic_statement(text: str, source: str, skipped: dict | None = None) -> list[ParsedOperation]:
    skipped = skipped if skipped is not None else {}
    flat = re.sub(r"\s+", " ", TR_PAGE_HEADER.sub(" ", text))
    flat = re.sub(r"DATE TYPE DESCRIPTION ENTRÉE D'ARGENT SORTIE D'ARGENT SOLDE", " ", flat)
    operations = []
    for section in flat.split("SYNTHÈSE DU RELEVÉ DE COMPTE")[1:]:
        product = re.search(r"SOLDE FIN DE PÉRIODE (.+?) -?\d", section)
        envelope = "PEA" if product and "PEA" in product.group(1).upper() else "CTO"
        body = section.split("TRANSACTIONS", 1)[-1].split("REMARQUES SUR LE RELEVÉ", 1)[0]
        dates = list(TR_DATE.finditer(body))
        held: dict[str, float] = {}  # quantité détenue, pour répartir un dividende par action
        for i, d in enumerate(dates):
            chunk = body[d.end(): dates[i + 1].start() if i + 1 < len(dates) else len(body)]
            amounts = TR_AMOUNT.findall(chunk)
            if len(amounts) < 2:
                continue
            amount = abs(_num(amounts[-2]))  # avant-dernier : montant ; dernier : solde
            day = f"{d.group(3)}-{TR_MONTHS[d.group(2)]:02d}-{d.group(1)}"
            trade, dividend = TR_TRADE.search(chunk), TR_DIVIDEND.search(chunk)
            if trade:
                label, isin, name, quantity = trade.group(1), trade.group(2), trade.group(3).strip(), float(trade.group(4))
                if not quantity:
                    continue
                kind = "Vente" if label == "Sell trade" else "Achat"
                plan = label == "Savings plan execution"
                fee = 0.0 if plan else TR_ORDER_FEE
                price = (amount - fee if kind == "Achat" else amount + fee) / quantity
                held[isin] = held.get(isin, 0.0) + (quantity if kind == "Achat" else -quantity)
                operations.append(ParsedOperation(
                    date=day, type=kind, isin=isin, name=name, quantity=quantity, price=round(price, 6),
                    fees=fee, taxes=0.0, order_type="Plan d'investissement" if plan else "Ordre",
                    source=source, envelope=envelope, ticker=crypto_ticker(isin) if isin.startswith("XF000") else None))
            elif dividend:
                isin = dividend.group(1)
                quantity = round(held.get(isin, 0.0), 6)
                quantity = quantity if quantity > 0 else 1.0  # titre acheté avant la période du relevé
                operations.append(ParsedOperation(
                    date=day, type="Dividende", isin=isin, name=isin, quantity=quantity,
                    price=round(amount / quantity, 6), fees=0.0, taxes=0.0, order_type="",
                    source=source, envelope=envelope))
            elif "Corporate action" in chunk:
                skipped["corporate"] = skipped.get("corporate", 0) + 1
    if not operations and not skipped:
        raise OperationError(f"{source} : aucune opération trouvée dans le relevé Trade Republic")
    names = {op.isin: op.name for op in operations if op.type != "Dividende"}
    for op in operations:  # un dividende porte le nom du titre quand le relevé contient ses achats
        if op.type == "Dividende":
            op.name = names.get(op.isin, op.isin)
    return operations


def parse_file(name: str, content: bytes, skipped: dict | None = None) -> list[ParsedOperation]:
    if len(content) > MAX_FILE_BYTES:
        raise OperationError(f"{name} : fichier trop gros")
    if content[:4] == b"%PDF":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
        if "TRADE REPUBLIC" in text.upper():
            return parse_trade_republic_statement(text, name, skipped)
        if "BOURSORAMA" in text.upper() or "Code ISIN" in text:
            return [parse_boursorama_text(text, name)]
        raise OperationError(f"{name} : PDF non reconnu (relevé de compte Trade Republic ou avis d'opéré Boursorama attendus)")
    return parse_trade_republic_csv(content.decode("utf-8-sig", errors="replace"), name, skipped)


def route_accounts(operations: list[ParsedOperation], chosen: str, accounts: list[dict]) -> None:
    """Compte de chaque opération : celui choisi, sauf quand le fichier indique une autre enveloppe
    (relevé Trade Republic avec PEA et CTO) : on prend alors un compte de cette enveloppe, de préférence
    chez le même courtier que le compte choisi."""
    by_name = {a["name"]: a for a in accounts}
    chosen_account = by_name.get(chosen, {})
    for op in operations:
        if not op.envelope or chosen_account.get("envelope") == op.envelope:
            op.account = chosen
            continue
        same = [a for a in accounts if a["envelope"] == op.envelope]
        same.sort(key=lambda a: a.get("broker") != chosen_account.get("broker"))
        op.account = same[0]["name"] if same else None


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

    from .operations import read_settings

    from .duplicates import Entry, mark_duplicates

    accounts = read_settings(sheet_id)["accounts"]
    route_accounts(parsed, account, accounts)
    envelopes = {a["name"]: a["envelope"] for a in accounts}
    existing, _, _ = read_operations(sheet_id, raw=True)  # quantités telles que saisies, comme dans les relevés
    tickers: dict[str, str | None] = {}
    for op in sorted(parsed, key=lambda o: o.date):
        if op.ticker or op.type in CASH_TYPES:  # crypto : ticker déjà connu ; espèces : pas de titre
            continue
        if op.isin not in tickers:
            tickers[op.isin] = find_ticker(op.isin, known_isins)
        op.ticker = tickers[op.isin]
    # Déjà dans le Sheet (ou dans un autre fichier du même import) : même opération à quelques jours près
    ordered = sorted(parsed, key=lambda o: o.date)
    known = [Entry(op.day, envelopes.get(op.account, "CTO"), op.kind, op.ticker, op.quantity, op.gross) for op in existing]
    known += [Entry(m.day, envelopes.get(m.account, "CTO"), m.kind, "", 1, m.gross or m.amount, net=m.amount)
              for m in read_cash(sheet_id)]
    new = [Entry(date.fromisoformat(op.date), envelopes.get(op.account or "", op.envelope or "CTO"), op.type,
                 op.ticker or "", op.quantity, op.quantity * op.price, source=op.source,
                 net=op.price - op.taxes if op.type in CASH_TYPES else None) for op in ordered]
    for op, duplicate in zip(ordered, mark_duplicates(new, known)):
        op.status = ("no_account" if not op.account else "duplicate" if duplicate
                     else "new" if op.ticker or op.type in CASH_TYPES else "no_ticker")
    operations = [asdict(op) for op in sorted(parsed, key=lambda o: o.date)]
    if skipped.get("corporate"):
        errors.append(f"{skipped['corporate']} opérations sur titres ignorées (division, rompus...) : ajoute à la "
                      "main les actions reçues (type Division dans « Ajouter une opération »)")
    return {"operations": operations, "errors": errors,
            "counts": {s: sum(o["status"] == s for o in operations) for s in ("new", "duplicate", "no_ticker", "no_account")}}


def write_import(sheet_id: str, account: str, operations: list[dict], titres_info=describe_for_titres,
                 profiles: dict[str, dict] | None = None) -> dict:
    """Écrit d'un coup les opérations validées (et les nouveaux titres dans l'onglet Titres).
    profiles : secteur et pays de chaque action du screener, comme pour une saisie manuelle."""
    profiles = profiles or {}
    from .operations import read_settings

    settings = read_settings(sheet_id)
    known_accounts = {a["name"] for a in settings["accounts"]}
    clean, cash = [], []
    for op in operations:
        if op.get("type") in CASH_TYPES:
            op_account = op.get("account") or account
            if op_account not in known_accounts:
                raise OperationError(f"Compte inconnu : {op_account}. Ajoute-le dans Réglages > Mes comptes et courtiers")
            cash.append((date.fromisoformat(op["date"]), op_account, op["type"], float(op["price"]),
                         f"Import {op.get('source', '')}".strip(), float(op.get("taxes") or 0)))
            continue
        ticker = str(op.get("ticker") or "").strip().upper()
        if not ticker or op.get("type") not in ("Achat", "Vente", "Dividende", *SHARE_TYPES):
            raise OperationError("Chaque opération doit avoir un ticker et un type")
        op_account = op.get("account") or account
        if op_account not in known_accounts:
            raise OperationError(f"Compte inconnu : {op_account}. Ajoute-le dans Réglages > Mes comptes et courtiers")
        clean.append({
            "date": date.fromisoformat(op["date"]), "account": op_account, "type": op["type"], "ticker": ticker,
            "quantity": float(op["quantity"]), "price": float(op["price"]), "currency": "EUR", "fx": 1,
            "fees": float(op.get("fees") or 0), "taxes": float(op.get("taxes") or 0),
            "order_type": op.get("order_type") or ("" if op["type"] in ("Dividende", *SHARE_TYPES) else "Ordre"),
            "why": "", "term": "", "note": f"Import {op.get('source', '')}".strip(),
        })
    if not clean and not cash:
        return {"written": 0, "new_tickers": []}
    clean.sort(key=lambda o: o["date"])

    sheet = _open_sheet(sheet_id, write=True)
    if cash or any(op["type"] in SHARE_TYPES for op in clean):
        ensure_operation_types(sheet)
    known = {t["ticker"].upper() for t in settings["titres"]}
    new_tickers = sorted({op["ticker"] for op in clean} - known)
    if new_tickers:
        titres = _worksheet(sheet, "Titres")
        start = len(titres.col_values(1)) + 1
        rows = []
        for ticker in new_tickers:
            try:
                info = titres_info(ticker)
                crypto = info.kind == "Crypto"
                profile = profiles.get(ticker, {})
                rows.append([ticker, info.google, info.name, "Crypto" if crypto else profile.get("sector", ""),
                             "Monde" if crypto else profile.get("country", ""), info.currency, info.kind])
            except OperationError:
                rows.append([ticker, "", ticker, "", "", "EUR", "Action"])  # à compléter à la main
        titres.update(range_name=f"A{start}", values=rows)

    ops = _worksheet(sheet, "Opérations")
    start = len(ops.col_values(1)) + 1
    rows = [operation_row(op, start + i) for i, op in enumerate(clean)]
    rows += [cash_row(day, acct, kind, amount, note, start + len(rows) + i, taxes)
             for i, (day, acct, kind, amount, note, taxes) in enumerate(sorted(cash))]
    ops.update(range_name=f"A{start}", values=rows, value_input_option="USER_ENTERED")
    return {"written": len(rows), "new_tickers": new_tickers}
