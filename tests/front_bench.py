"""Banc de test du front : la vraie API FastAPI (TestClient) sur un faux Google Sheet en mémoire, le front servi
en local et piloté par Chromium (Playwright). Les appels de la page vers l'API Render sont redirigés vers le
TestClient ; Yahoo et le reste d'internet sont coupés (cours simulés), pour un test identique partout.

Utilisé par test_front.py. Réseau coupé côté Python : yfinance et requests lèvent une erreur de connexion, comme
quand Yahoo bloque Render ; les routes doivent alors répondre quand même (sans cours) au lieu d'une erreur 500."""

import json
import math
import os
import threading
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
SCREENER_SAMPLE = Path(__file__).parent / "fixtures" / "screener_sample.json"
API_HOST = "portfolio-app-blvx.onrender.com"
CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"  # celle de index.html

# Cours simulés (dernier cours, devise, taux en euros) des trois titres du faux portefeuille
PRICES = {"AI.PA": (180.0, "EUR", 1.0), "AAPL": (230.0, "USD", 0.86), "MC.PA": (600.0, "EUR", 1.0)}
NAMES = {"AI.PA": "Air Liquide", "AAPL": "Apple", "MC.PA": "LVMH"}


def serial(d: date) -> int:
    from app.sheets import SHEETS_EPOCH
    return (d - SHEETS_EPOCH).days


def op(d, account, kind, ticker, qty, price, cur="EUR", fx=1, fees=0, taxes=0, order="Ordre", why="", term="", note=""):
    return [serial(d), account, kind, ticker, qty, price, cur, fx, "=E*F*H", fees, taxes, "=L", order, why, term, note]


class FakeWorksheet:
    def __init__(self, sheet, title, rows):
        self.sheet, self.title, self.rows, self.id = sheet, title, rows, abs(hash(title)) % 10000
        self.row_count = 2000

    def _values(self):
        if self.title == "Positions":
            return self.sheet.positions()
        return [self.sheet.computed(r) if self.title == "Opérations" and i else r for i, r in enumerate(self.rows)]

    def get_values(self, range_name=None, value_render_option=None, **kw):
        values = self._values()
        if range_name:
            start = int("".join(c for c in range_name.split(":")[0] if c.isdigit()))
            return [values[start - 1]] if start - 1 < len(values) else []
        return values

    get_all_values = get_values

    def col_values(self, n):
        return [r[n - 1] if len(r) >= n else "" for r in self.rows]

    def update(self, range_name=None, values=None, value_input_option=None, **kw):
        from app import sheets
        start = int("".join(c for c in range_name if c.isdigit()))
        for i, v in enumerate(values):
            while len(self.rows) <= start - 1 + i:
                self.rows.append([])
            v = list(v)
            if self.title == "Opérations" and v and isinstance(v[0], str) and v[0][:2] == "20":
                v[0] = serial(date.fromisoformat(v[0]))  # USER_ENTERED : le Sheet lit la date
            self.rows[start - 1 + i] = v
        sheets.clear_sheet_cache()

    def delete_rows(self, i, end=None):
        from app import sheets
        del self.rows[i - 1]
        sheets.clear_sheet_cache()

    def acell(self, label, value_render_option=None):
        from app import workbook
        return type("Cell", (), {"value": workbook.POSITION_FORMULAS.get(label, "")})()

    def batch_update(self, *a, **k):
        pass

    def batch_clear(self, *a, **k):
        pass

    def add_rows(self, n):
        pass

    def clear(self):
        self.rows = []

    def resize(self, rows=None, cols=None):
        pass

    def append_row(self, row, **k):
        from app import sheets
        self.rows.append(list(row))
        sheets.clear_sheet_cache()


class FakeSheet:
    id = "s"

    def __init__(self, tabs):
        self.tabs = {name: FakeWorksheet(self, name, rows) for name, rows in tabs.items()}

    def worksheets(self):
        return list(self.tabs.values())

    def worksheet(self, name):
        return self.tabs[name]

    def add_worksheet(self, name, rows=100, cols=10):
        self.tabs[name] = FakeWorksheet(self, name, [])
        return self.tabs[name]

    def batch_update(self, *a, **k):
        pass

    @staticmethod
    def computed(r):
        """Colonnes calculées de l'onglet Opérations (montant brut et net), comme les formules du modèle."""
        r = (list(r) + [""] * 16)[:16]
        if r[2] and isinstance(r[4], (int, float)):
            gross = r[4] * (r[5] or 0) * (r[7] or 1)
            r[8] = gross
            fees, taxes = r[9] or 0, r[10] or 0
            r[11] = gross + fees + taxes if r[2] == "Achat" else gross - fees - taxes
        return r

    def positions(self):
        """Onglet Positions recalculé comme ses formules : quantité et PRU en rejouant les opérations."""
        from app import workbook
        ops = [self.computed(r) for r in self.tabs["Opérations"].rows[1:] if r and r[0] != ""]
        comptes = {r[0]: r[1] for r in self.tabs["Comptes"].rows[1:]}
        pos = {}
        for r in sorted(ops, key=lambda r: (r[0], r[2] == "Vente")):
            if r[2] not in ("Achat", "Vente", "Division", "Actions gratuites"):
                continue
            q, k = pos.get((r[3], r[1]), (0.0, 0.0))
            if r[2] == "Vente":
                q, k = (0.0, 0.0) if r[4] >= q else (q - r[4], k * (q - r[4]) / q)
            else:
                q, k = q + r[4], k + (r[11] if r[2] == "Achat" else 0)
            pos[(r[3], r[1])] = (q, k)
        rows = [workbook.POSITIONS_HEADERS]
        for (t, c), (q, k) in sorted(pos.items()):
            if q <= 1e-9:
                continue
            price, cur, fx = PRICES[t]
            value = q * price * fx
            rows.append([t, NAMES[t], c, comptes.get(c, ""), q, k / q, k, price, cur, fx, value, value - k, (value - k) / k, "", ""])
        return rows


def default_tabs(today: date) -> dict:
    """Portefeuille d'exemple : Air Liquide (PEA, avec actions gratuites), Apple (CTO, vente partielle et
    dividende), LVMH (PEA), un versement, une thèse à relire et un mois d'historique jusqu'à la veille."""
    from app import journal, workbook
    history_days = [today - timedelta(days=n) for n in range(40, 0, -1) if (today - timedelta(days=n)).weekday() < 5]
    return {
        "Opérations": [workbook.OPERATIONS_HEADERS,
                       op(date(2025, 1, 10), "PEA Bourso", "Achat", "AI.PA", 20, 150, fees=1.5, why="Qualité", term="Long"),
                       op(date(2025, 6, 9), "PEA Bourso", "Actions gratuites", "AI.PA", 2, 0, note="20 -> 22 actions"),
                       op(date(2025, 3, 3), "CTO TR", "Achat", "AAPL", 10, 200, "USD", 0.92, fees=1, why="Renforcement"),
                       op(date(2025, 9, 1), "CTO TR", "Vente", "AAPL", 4, 240, "USD", 0.88, fees=1),
                       op(date(2025, 11, 14), "CTO TR", "Dividende", "AAPL", 6, 0.26, "USD", 0.86, taxes=0.47),
                       op(date(2026, 2, 2), "CTO TR", "Versement", "", 1, 500, note="Virement"),
                       op(date(2026, 4, 20), "PEA Bourso", "Achat", "MC.PA", 2, 550, fees=2.75, term="Moyen")],
        "Comptes": [workbook.COMPTES_HEADERS, ["PEA Bourso", "PEA", "Boursorama"], ["CTO TR", "CTO", "Trade Republic"]],
        "Titres": [workbook.TITRES_HEADERS, ["AI.PA", "EPA:AI", "Air Liquide", "Matériaux", "France", "EUR", "Action"],
                   ["AAPL", "NASDAQ:AAPL", "Apple", "Technologie", "États-Unis", "USD", "Action"],
                   ["MC.PA", "EPA:MC", "LVMH", "Consommation", "France", "EUR", "Action"]],
        "Frais": [workbook.FRAIS_HEADERS] + workbook.DEFAULT_FEES,
        "Historique": [workbook.HISTORY_HEADERS] + [
            [serial(d), 4400 + i * 5, 4152, 1300 + i * 3, 1200, None, None, None] for i, d in enumerate(history_days)],
        "Positions": [],
        "Épargne": [workbook.SAVINGS_HEADERS],
        "Watchlist": [["TICKER", "AJOUTÉ LE"]],
        "Allocation": [workbook.ALLOCATION_HEADERS],
        "Journal": [journal.JOURNAL_HEADERS,
                    ["AI.PA", "Leader des gaz industriels", 200, 150, "Long", (today - timedelta(days=15)).isoformat(), "", ""]],
        "Budget": budget_rows(today),
    }


def budget_rows(today: date) -> list[list]:
    """Onglet Budget (Plus > Budget) : deux mois complets avant celui-ci, puis le mois en cours relevé jusqu'au 1er
    avec une opération à catégoriser. Chaque mois complet : 1 500 € de revenus, 540 + 180 + 60 = 780 € de dépenses,
    solde +720 € (48 % mis de côté), 100 € investis, 500 € de virements internes. Libellés inventés."""
    from app import budget
    first = today.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    before = (previous - timedelta(days=1)).replace(day=1)
    rows = [budget.BUDGET_HEADERS]
    for month in (before, previous):
        day = lambda d: month.replace(day=d).isoformat()  # noqa: E731
        rows += [[day(1), "VIR INST vers Agence Immo", 540, "Logement", "Loyer", "depense", today.isoformat()],
                 [day(5), "CB SUPERMARCHE CENTRE", 120, "Courses", "Supermarché", "depense", today.isoformat()],
                 [day(19), "CB EPICERIE DU COIN", 60, "Courses", "Épicerie", "depense", today.isoformat()],
                 [day(12), "CB TRATTORIA", 60, "Restaurant/Bar", "Restaurant", "depense", today.isoformat()],
                 [day(27), "VIR Gratification de stage", 1200, "Salaire", "", "revenu", today.isoformat()],
                 [day(3), "VIR Famille", 300, "Virement reçu", "", "revenu", today.isoformat()],
                 [day(8), "VIR INST vers Trade Republic", 100, "Investissement", "Bourse/Épargne", "investissement", today.isoformat()],
                 [day(15), "VIR vers Livret A", 500, "Virements internes", "Livret A", "interne", today.isoformat()]]
    rows += [[first.isoformat(), "VIR INST vers Agence Immo", 540, "Logement", "Loyer", "depense", today.isoformat()],
             [first.isoformat(), "CB NOUVEAU COMMERCE", 23.4, "À catégoriser", "", "a_categoriser", today.isoformat()]]
    return rows


class Offline(ConnectionError):
    """Internet coupé par le banc de test (Yahoo, Google Actualités, OpenFIGI...)."""


class OfflineTicker:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        raise Offline(f"yfinance hors ligne ({name})")


def cut_network(monkeypatch):
    """Coupe yfinance et requests : aucun appel réel, même sur la CI qui, elle, a internet."""
    import requests
    import yfinance

    def offline(*a, **k):
        raise requests.ConnectionError("hors ligne (banc de test)")

    monkeypatch.setattr(yfinance, "Ticker", OfflineTicker)
    monkeypatch.setattr(yfinance, "download", offline)
    monkeypatch.setattr(yfinance, "Search", OfflineTicker)
    monkeypatch.setattr(requests.Session, "request", offline)


def fake_download_closes(tickers, start, adjusted=True):
    """Yahoo simulé : cours qui montent doucement, dernière séance +1,5 % ; dollar de 0,92 à 0,86 €."""
    import pandas as pd
    days = pd.bdate_range(start, date.today())
    data = {}
    for t in tickers:
        n = len(days)
        if t.endswith("EUR=X"):
            data[t] = [0.92 + (0.86 - 0.92) * i / max(n - 1, 1) for i in range(n)]
        else:
            last = PRICES.get(t, (100.0,))[0]
            data[t] = [last / 1.015 * (0.8 + 0.2 * i / max(n - 2, 1)) for i in range(n - 1)] + [last]
    return pd.DataFrame(data, index=days)


def fake_price_history(ticker):
    import pandas as pd
    days = pd.bdate_range(end=date.today(), periods=520)
    last = PRICES.get(ticker, (100.0,))[0]
    points = [[d.date().isoformat(), round(last * (0.75 + 0.25 * i / 519) * (1 + 0.06 * math.sin(i / 17)), 2)]
              for i, d in enumerate(days)]
    return {"ticker": ticker, "currency": PRICES.get(ticker, (0, "EUR"))[1], "points": points}


def dividend_history(ticker, since):
    """Versements passés : Air Liquide annuel, Apple trimestriel, LVMH semestriel (projetés sur 12 mois)."""
    today = date.today()
    ago = lambda days: today - timedelta(days=days)  # noqa: E731
    return {"AI.PA": [(ago(135), 3.3)],
            "AAPL": [(ago(325), 0.26), (ago(234), 0.26), (ago(142), 0.26), (ago(50), 0.26)],
            "MC.PA": [(ago(300), 5.5), (ago(155), 7.5)]}.get(ticker, [])


def make_client(monkeypatch, tabs=None):
    """API réelle sur le faux Sheet, un seul utilisateur (Enzo, administrateur)."""
    from fastapi.testclient import TestClient

    from app import dividend_calendar, data, main, performance, prices, sheets, workbook
    from app.users import User

    cut_network(monkeypatch)
    monkeypatch.setattr(performance, "download_closes", fake_download_closes)
    monkeypatch.setattr(prices, "fetch_price_history", fake_price_history)
    monkeypatch.setattr(dividend_calendar, "_history", dividend_history)
    monkeypatch.setattr(data, "_fx_rate", lambda a, b: 0.86)
    # Fichiers de la branche screener-data lus par l'API (alertes) : l'échantillon figé, rien d'autre
    sample = json.loads(SCREENER_SAMPLE.read_text(encoding="utf-8"))
    monkeypatch.setattr(main, "_screener_data", lambda name: sample if name == "screener.json" else None)
    sheet = FakeSheet(tabs or default_tabs(date.today()))
    client = type("Client", (), {"open_by_key": lambda self, key: sheet})()
    monkeypatch.setattr(sheets, "sheets_client", lambda write=False: client)
    monkeypatch.setattr(workbook, "sheets_client", sheets.sheets_client)
    user = User("Enzo", None, "s", admin=True)
    monkeypatch.setattr(main, "resolve", lambda token: user)
    sheets.clear_sheet_cache()
    return TestClient(main.app), sheet


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve_front() -> tuple[str, ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(FRONT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/index.html", server


def chart_js() -> bytes | None:
    """Chart.js pour la page : fichier local si CHART_JS_PATH est défini (conteneur de dev sans jsDelivr), sinon
    téléchargé une fois ici, avant la coupure du réseau ; None si injoignable."""
    import urllib.request
    path = os.environ.get("CHART_JS_PATH")
    if path:
        return Path(path).read_bytes()
    try:
        with urllib.request.urlopen(CHART_JS_URL, timeout=20) as response:
            return response.read()
    except OSError:
        return None


def route_all(page, client, api_calls: list, chart: bytes):
    """Aiguillage des requêtes de la page : API -> TestClient, screener -> échantillon figé, Chart.js -> fichier
    fourni ; tout le reste (logos, Yahoo, GitHub) est coupé."""
    screener = SCREENER_SAMPLE.read_bytes()

    def handle(route):
        url = route.request.url
        if API_HOST in url:
            method = route.request.method
            if method == "OPTIONS":
                return route.fulfill(status=204, headers={"access-control-allow-origin": "*", "access-control-allow-headers": "*",
                                                          "access-control-allow-methods": "*"})
            path = url.split(API_HOST, 1)[1]
            body = route.request.post_data
            r = client.request(method, path, content=body, headers={"content-type": "application/json"} if body else {})
            api_calls.append((method, path, r.status_code))
            return route.fulfill(status=r.status_code, body=r.content,
                                 headers={"content-type": r.headers.get("content-type", "application/json"),
                                          "access-control-allow-origin": "*"})
        if "chart.umd" in url:
            return route.fulfill(body=chart, content_type="application/javascript")
        if url.endswith("screener-data/screener.json"):
            return route.fulfill(body=screener, content_type="application/json", headers={"access-control-allow-origin": "*"})
        if url.startswith("http://127.0.0.1"):
            return route.continue_()
        return route.abort()

    page.route("**/*", handle)


def screener_tickers() -> list[str]:
    return [s["ticker"] for s in json.loads(SCREENER_SAMPLE.read_text(encoding="utf-8"))["stocks"]]
