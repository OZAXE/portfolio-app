"""
API principale. Lance en local avec :
    uvicorn app.main:app --reload

Endpoints prévus pour le MVP :
- GET /portfolio            -> positions lues depuis le Google Sheet
- GET /analysis/{ticker}    -> fondamentaux + score qualité + DCF pour un ticker
- GET /portfolio/analysis   -> l'analyse complète pour toutes les positions du portefeuille
- GET /portfolio/overview   -> valeurs, historique et répartition lus dans le Sheet (rapide, sans Yahoo)
- GET /watchlist            -> actions surveillées (onglet Watchlist du Sheet) ; POST / DELETE /watchlist/{ticker}
- GET /alerts               -> alertes du jour et opportunités sur les positions et la watchlist
- GET /briefs               -> liste des briefs hebdo (dossier Drive "Briefs")
- GET /briefs/{id}          -> contenu HTML d'un brief
"""

import logging
import re
import time
from collections import defaultdict
from dataclasses import asdict

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import requests

from .data import INVALID_TICKER_ERROR, SOURCE_UNAVAILABLE_ERROR, fetch_company_financials
from .valuation import evaluate_company
from .briefs import BriefNotFoundError, DriveAccessError, get_brief_html, list_briefs
from .alerts import compute_alerts
from .sheets import add_to_watchlist, get_watchlist, remove_from_watchlist
from .sheets import HoldingLine, SheetNotConfiguredError, get_overview, get_portfolio_positions
from .users import User, access_protected, resolve
from .operations import OperationError, add_operation, read_settings

# uvicorn ne configure que ses propres loggers : sans ça, les logs de app.data n'apparaissent pas
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

app = FastAPI(title="Portfolio Insights API")

# Seul le frontend peut appeler l'API depuis un navigateur. Ce n'est pas une protection
# des données (un script n'envoie pas d'Origin) : c'est le rôle du code d'accès ci-dessous
FRONTEND_ORIGINS = ["https://portfolio-front-8t6m.onrender.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # tests en local
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-Access-Token"],
)

# Chaque code d'accès correspond à un utilisateur et à son propre Google Sheet (voir users.py)
def require_access(x_access_token: str | None = Header(default=None)) -> User:
    user = resolve(x_access_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Code d'accès manquant ou invalide")
    return user


def require_admin(user: User = Depends(require_access)) -> User:
    if not user.admin:
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur de l'appli")
    return user


@app.get("/health")
def health():
    # Indique seulement si le code d'accès est configuré, jamais sa valeur
    return {"status": "ok", "access_protected": access_protected()}


@app.get("/me")
def me(user: User = Depends(require_access)):
    return {"name": user.name, "admin": user.admin, "briefs": bool(user.briefs_folder)}


def _load_positions(user: User):
    try:
        return get_portfolio_positions(user.sheet_id)
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=f"Google Sheet non configuré : {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture du Google Sheet : {e}")


@app.get("/portfolio")
def get_portfolio(user: User = Depends(require_access)):
    return [p.__dict__ for p in _load_positions(user)]


@app.get("/analysis/{ticker}")
def get_analysis(ticker: str):
    cf = fetch_company_financials(ticker)
    if cf.raw_error == INVALID_TICKER_ERROR:
        raise HTTPException(status_code=404, detail=f"{INVALID_TICKER_ERROR} : {ticker}")
    if cf.raw_error == SOURCE_UNAVAILABLE_ERROR:
        raise HTTPException(status_code=503, detail=SOURCE_UNAVAILABLE_ERROR)
    if cf.raw_error:
        raise HTTPException(status_code=502, detail=f"Erreur de récupération des données : {cf.raw_error}")
    result = evaluate_company(cf)
    return {
        "financials": cf.__dict__,
        "valuation": result.__dict__,
    }


@app.get("/portfolio/analysis")
def get_portfolio_analysis(user: User = Depends(require_access)):
    positions = _load_positions(user)
    output = []
    for pos in positions:
        cf = fetch_company_financials(pos.ticker)
        result = evaluate_company(cf)
        output.append(
            {
                "ticker": pos.ticker,
                "quantity": pos.quantity,
                "envelope": pos.envelope,
                "financials": cf.__dict__,
                "valuation": result.__dict__,
            }
        )
    return output


def _totals(lines: list[HoldingLine]) -> dict:
    value = sum(h.value or 0 for h in lines)
    invested = sum(h.invested or 0 for h in lines)
    gain = value - invested
    return {
        "value": round(value, 2),
        "invested": round(invested, 2),
        "gain": round(gain, 2),
        "gain_pct": gain / invested if invested else None,
    }


@app.get("/portfolio/overview")
def get_portfolio_overview(user: User = Depends(require_access)):
    try:
        overview = get_overview(user.sheet_id)
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=f"Google Sheet non configuré : {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture du Google Sheet : {e}")

    by_envelope = defaultdict(list)
    by_sector = defaultdict(float)
    for h in overview.holdings:
        by_envelope[h.envelope or "Autre"].append(h)
        by_sector[h.sector or "Non classé"] += h.value or 0

    total = _totals(overview.holdings)
    sectors = [
        {"sector": s, "value": round(v, 2), "weight": v / total["value"] if total["value"] else None}
        for s, v in sorted(by_sector.items(), key=lambda kv: -kv[1])
    ]
    return {
        "total": total,
        "envelopes": {name: _totals(lines) for name, lines in by_envelope.items()},
        "holdings": [asdict(h) for h in overview.holdings],
        "sectors": sectors,
        "history": [asdict(p) for p in overview.history],
        "savings": overview.savings,
    }


def _briefs_errors(call):
    try:
        return call()
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=f"Compte de service non configuré : {e}")
    except DriveAccessError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except BriefNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur de lecture du dossier Briefs : {e}")


# Les briefs parlent de ton portefeuille : même code d'accès que les positions
@app.get("/briefs")
def get_briefs(user: User = Depends(require_access)):
    if not user.briefs_folder:
        return []
    return _briefs_errors(lambda: list_briefs(user.briefs_folder))


@app.get("/briefs/{brief_id}", response_class=HTMLResponse)
def get_brief(brief_id: str, user: User = Depends(require_access)):
    if not user.briefs_folder:
        raise HTTPException(status_code=404, detail="Pas de dossier de briefs pour cet utilisateur")
    return HTMLResponse(_briefs_errors(lambda: get_brief_html(user.briefs_folder, brief_id)))


# --- Watchlist et alertes ---
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,19}$")


def _sheet_call(call):
    try:
        return call()
    except HTTPException:
        raise
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=f"Google Sheet non configuré : {e}")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Le compte de service doit être Éditeur du Google Sheet")
    except Exception as e:
        if "PERMISSION_DENIED" in str(e) or "403" in str(e):
            raise HTTPException(status_code=403, detail="Le compte de service doit être Éditeur du Google Sheet pour modifier la watchlist")
        raise HTTPException(status_code=500, detail=f"Erreur Google Sheet : {e}")


def _checked_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not TICKER_PATTERN.match(ticker):
        raise HTTPException(status_code=400, detail="Ticker invalide")
    return ticker


@app.get("/watchlist")
def read_watchlist(user: User = Depends(require_access)):
    return _sheet_call(lambda: get_watchlist(user.sheet_id))


@app.post("/watchlist/{ticker}")
def watch(ticker: str, user: User = Depends(require_access)):
    ticker = _checked_ticker(ticker)
    return _sheet_call(lambda: add_to_watchlist(user.sheet_id, ticker))


@app.delete("/watchlist/{ticker}")
def unwatch(ticker: str, user: User = Depends(require_access)):
    ticker = _checked_ticker(ticker)
    return _sheet_call(lambda: remove_from_watchlist(user.sheet_id, ticker))


# Résultats du screener nocturne, publiés sur la branche screener-data du repo
SCREENER_DATA_URL = "https://raw.githubusercontent.com/OZAXE/portfolio-app/screener-data/{}"
DATA_CACHE_SECONDS = 1800
_data_cache: dict[str, tuple[float, dict]] = {}


def _screener_data(name: str) -> dict | None:
    cached = _data_cache.get(name)
    if cached and time.monotonic() - cached[0] < DATA_CACHE_SECONDS:
        return cached[1]
    try:
        response = requests.get(SCREENER_DATA_URL.format(name), timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return cached[1] if cached else None
    _data_cache[name] = (time.monotonic(), data)
    return data


@app.get("/alerts")
def get_alerts(user: User = Depends(require_access)):
    positions = {p.ticker.upper() for p in _load_positions(user)}
    watchlist = set(_sheet_call(lambda: get_watchlist(user.sheet_id)))
    screener = _screener_data("screener.json")
    if screener is None:
        raise HTTPException(status_code=503, detail="Résultats du screener indisponibles")
    result = compute_alerts(positions, watchlist, screener, _screener_data("superinvestors.json"))
    return {**result, "screener_date": screener.get("generated_at")}


# --- Administration : construction du Sheet modèle (format v2) et migration de l'ancien ---
SHEET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,80}$")


def _describe_ticker(ticker: str) -> tuple[str | None, str]:
    """Nom lisible et type (Action / ETF) d'un titre, via l'API chart de Yahoo (répond même sur Render)."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        t.history(period="5d")
        meta = t.history_metadata or {}
        return meta.get("longName") or meta.get("shortName"), "ETF" if meta.get("instrumentType") == "ETF" else "Action"
    except Exception:
        return None, "Action"


@app.post("/admin/sheet/setup", dependencies=[Depends(require_admin)])
def setup_sheet(target: str, migrate_from: str | None = None):
    """Construit les onglets du modèle dans le Sheet `target` (vide, partagé en Éditeur avec le compte
    de service), puis y recopie les données de l'ancien Sheet `migrate_from` s'il est donné."""
    from .workbook import build_template, migrate_from_v1, open_for_write

    for sheet_id in filter(None, (target, migrate_from)):
        if not SHEET_ID_PATTERN.match(sheet_id):
            raise HTTPException(status_code=400, detail=f"Identifiant de Sheet invalide : {sheet_id}")
    try:
        new = open_for_write(target)
        build_template(new)
        result = {"template": "ok", "url": f"https://docs.google.com/spreadsheets/d/{target}"}
        if migrate_from:
            result["migration"] = migrate_from_v1(open_for_write(migrate_from), new, _describe_ticker)
        return result
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__} : {e}")


# --- Saisie d'opérations (Sheet modèle v2) ---
def _operation_call(call):
    """Erreur de saisie -> 400 avec le message ; problème d'accès au Sheet -> comme la watchlist."""
    def guarded():
        try:
            return call()
        except OperationError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return _sheet_call(guarded)


@app.get("/settings")
def get_settings(user: User = Depends(require_access)):
    """Comptes, barèmes de frais et titres du Sheet, pour pré-remplir le formulaire d'opération."""
    return _operation_call(lambda: read_settings(user.sheet_id))


@app.post("/operations")
def post_operation(payload: dict = Body(...), user: User = Depends(require_access)):
    ticker = str(payload.get("ticker") or "").strip().upper()
    stock = next((s for s in (_screener_data("screener.json") or {}).get("stocks", []) if s["ticker"] == ticker), {})
    result = _operation_call(lambda: add_operation(user.sheet_id, payload, stock.get("sector", ""), stock.get("country", "")))
    for key in [k for k in _performance_cache if k[0] == user.sheet_id]:
        _performance_cache.pop(key)  # la courbe comparée doit intégrer la nouvelle opération
    return result


@app.get("/fx/{currency}")
def get_fx(currency: str):
    """Taux de conversion vers l'euro (1 USD = x EUR), pour une opération en devise étrangère."""
    import yfinance as yf

    currency = currency.strip()
    if currency == "EUR":
        return {"currency": "EUR", "rate": 1.0}
    divisor = 100 if currency == "GBp" else 1
    base = "GBP" if currency == "GBp" else currency.upper()
    if not re.fullmatch(r"[A-Z]{3}", base):
        raise HTTPException(status_code=400, detail="Devise invalide")
    history = yf.Ticker(f"{base}EUR=X").history(period="5d")
    if history.empty:
        raise HTTPException(status_code=404, detail=f"Taux {base}/EUR indisponible")
    return {"currency": currency, "rate": float(history["Close"].iloc[-1]) / divisor}


# --- Performance comparée à un indice (reconstituée à partir des opérations datées) ---
PERFORMANCE_CACHE_SECONDS = 6 * 3600
_performance_cache: dict[tuple[str, str], tuple[float, dict]] = {}


@app.get("/portfolio/performance")
def get_performance(benchmark: str = "world", user: User = Depends(require_access)):
    from .performance import BENCHMARKS, portfolio_performance

    if benchmark not in BENCHMARKS:
        raise HTTPException(status_code=400, detail=f"Indice inconnu (choix : {', '.join(BENCHMARKS)})")
    key = (user.sheet_id, benchmark)
    cached = _performance_cache.get(key)
    if cached and time.monotonic() - cached[0] < PERFORMANCE_CACHE_SECONDS:
        return cached[1]
    result = _sheet_call(lambda: portfolio_performance(user.sheet_id, benchmark))
    _performance_cache[key] = (time.monotonic(), result)
    return result


# --- Plus-values réalisées et dividendes perçus (onglet Opérations) ---
@app.get("/portfolio/realized")
def get_realized(user: User = Depends(require_access)):
    from .realized import realized_summary

    return _sheet_call(lambda: realized_summary(user.sheet_id))
