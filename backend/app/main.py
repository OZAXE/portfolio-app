"""
API principale. Lance en local avec :
    uvicorn app.main:app --reload

Endpoints prévus pour le MVP :
- GET /portfolio            -> positions lues depuis le Google Sheet
- GET /analysis/{ticker}    -> fondamentaux + score qualité + DCF pour un ticker
- GET /portfolio/analysis   -> l'analyse complète pour toutes les positions du portefeuille
- GET /portfolio/overview   -> valeurs, historique et répartition lus dans le Sheet (rapide, sans Yahoo)
"""

import logging
from collections import defaultdict
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .data import INVALID_TICKER_ERROR, SOURCE_UNAVAILABLE_ERROR, fetch_company_financials
from .valuation import evaluate_company
from .sheets import HoldingLine, SheetNotConfiguredError, get_overview, get_portfolio_positions

# uvicorn ne configure que ses propres loggers : sans ça, les logs de app.data n'apparaissent pas
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

app = FastAPI(title="Portfolio Insights API")

# CORS ouvert pour l'instant : à restreindre au domaine du frontend une fois déployé
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


def _load_positions():
    try:
        return get_portfolio_positions()
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=f"Google Sheet non configuré : {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture du Google Sheet : {e}")


@app.get("/portfolio")
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


@app.get("/portfolio/analysis")
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


@app.get("/portfolio/overview")
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
