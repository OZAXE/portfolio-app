"""
API principale. Lance en local avec :
    uvicorn app.main:app --reload

Endpoints prévus pour le MVP :
- GET /portfolio            -> positions lues depuis le Google Sheet
- GET /analysis/{ticker}    -> fondamentaux + score qualité + DCF pour un ticker
- GET /portfolio/analysis   -> l'analyse complète pour toutes les positions du portefeuille
"""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .data import INVALID_TICKER_ERROR, fetch_company_financials
from .valuation import evaluate_company
from .sheets import get_portfolio_positions

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


@app.get("/portfolio")
def get_portfolio():
    try:
        positions = get_portfolio_positions()
        return [p.__dict__ for p in positions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analysis/{ticker}")
def get_analysis(ticker: str):
    cf = fetch_company_financials(ticker)
    if cf.raw_error == INVALID_TICKER_ERROR:
        raise HTTPException(status_code=404, detail=f"{INVALID_TICKER_ERROR} : {ticker}")
    if cf.raw_error:
        raise HTTPException(status_code=502, detail=f"Erreur de récupération des données : {cf.raw_error}")
    result = evaluate_company(cf)
    return {
        "financials": cf.__dict__,
        "valuation": result.__dict__,
    }


@app.get("/portfolio/analysis")
def get_portfolio_analysis():
    positions = get_portfolio_positions()
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
