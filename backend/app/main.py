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
import os
import re
import secrets
import time
from collections import defaultdict
from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import requests

from .data import INVALID_TICKER_ERROR, SOURCE_UNAVAILABLE_ERROR, fetch_company_financials
from .valuation import evaluate_company
from .briefs import BriefNotFoundError, DriveAccessError, get_brief_html, list_briefs
from .alerts import compute_alerts
from .sheets import add_to_watchlist, get_watchlist, remove_from_watchlist
from .sheets import HoldingLine, SheetNotConfiguredError, get_overview, get_portfolio_positions

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

# Code d'accès aux données personnelles (positions, valeurs). Tant que la variable
# n'est pas définie sur Render, l'API reste ouverte, pour ne rien casser
ACCESS_TOKEN = os.environ.get("APP_ACCESS_TOKEN")


def require_access(x_access_token: str | None = Header(default=None)):
    if ACCESS_TOKEN and not (x_access_token and secrets.compare_digest(x_access_token, ACCESS_TOKEN)):
        raise HTTPException(status_code=401, detail="Code d'accès manquant ou invalide")


@app.get("/health")
def health():
    # Indique seulement si le code d'accès est configuré, jamais sa valeur
    return {"status": "ok", "access_protected": bool(ACCESS_TOKEN)}


def _load_positions():
    try:
        return get_portfolio_positions()
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=f"Google Sheet non configuré : {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture du Google Sheet : {e}")


@app.get("/portfolio", dependencies=[Depends(require_access)])
def get_portfolio():
    return [p.__dict__ for p in _load_positions()]


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


@app.get("/portfolio/analysis", dependencies=[Depends(require_access)])
def get_portfolio_analysis():
    positions = _load_positions()
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


@app.get("/portfolio/overview", dependencies=[Depends(require_access)])
def get_portfolio_overview():
    try:
        overview = get_overview()
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
@app.get("/briefs", dependencies=[Depends(require_access)])
def get_briefs():
    return _briefs_errors(list_briefs)


@app.get("/briefs/{brief_id}", dependencies=[Depends(require_access)], response_class=HTMLResponse)
def get_brief(brief_id: str):
    return HTMLResponse(_briefs_errors(lambda: get_brief_html(brief_id)))


# --- Watchlist et alertes ---
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,19}$")


def _sheet_call(call):
    try:
        return call()
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


@app.get("/watchlist", dependencies=[Depends(require_access)])
def read_watchlist():
    return _sheet_call(get_watchlist)


@app.post("/watchlist/{ticker}", dependencies=[Depends(require_access)])
def watch(ticker: str):
    ticker = _checked_ticker(ticker)
    return _sheet_call(lambda: add_to_watchlist(ticker))


@app.delete("/watchlist/{ticker}", dependencies=[Depends(require_access)])
def unwatch(ticker: str):
    ticker = _checked_ticker(ticker)
    return _sheet_call(lambda: remove_from_watchlist(ticker))


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


@app.get("/alerts", dependencies=[Depends(require_access)])
def get_alerts():
    positions = {p.ticker.upper() for p in _load_positions()}
    watchlist = set(_sheet_call(get_watchlist))
    screener = _screener_data("screener.json")
    if screener is None:
        raise HTTPException(status_code=503, detail="Résultats du screener indisponibles")
    result = compute_alerts(positions, watchlist, screener, _screener_data("superinvestors.json"))
    return {**result, "screener_date": screener.get("generated_at")}
