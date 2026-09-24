"""
TEMPORAIRE : diagnostic des services Yahoo accessibles depuis le serveur.

Sur Render, Yahoo refuse le crumb (HTTP 429 puis 401) et bloque donc
quoteSummary, la source de t.info. Cet endpoint teste séparément chaque
service utilisé par yfinance pour savoir lesquels restent accessibles
(historique des cours, comptes annuels via fundamentals-timeseries...).
À supprimer une fois la source de données de production choisie.
"""

import time

import yfinance as yf
from fastapi import APIRouter

from .data import capture_yfinance_errors

router = APIRouter(prefix="/debug", tags=["debug"])


def _row(df, label):
    """Dernière valeur connue d'une ligne des états financiers (colonnes : plus récent en premier)."""
    if df is None or df.empty or label not in df.index:
        return None
    values = df.loc[label].dropna()
    return float(values.iloc[0]) if not values.empty else None


def _summarize_info(t):
    info = t.info or {}
    return {"nb_cles": len(info), "symbol": info.get("symbol"), "totalDebt": info.get("totalDebt")}


def _summarize_fast_info(t):
    fi = t.fast_info
    return {"last_price": fi.last_price, "currency": fi.currency, "shares": fi.shares}


def _summarize_history(t):
    h = t.history(period="5d")
    return {"nb_lignes": len(h), "dernier_close": float(h["Close"].iloc[-1]) if not h.empty else None}


def _summarize_balance_sheet(t):
    bs = t.balance_sheet
    return {
        "colonnes": [str(c.date()) for c in bs.columns] if not bs.empty else [],
        "Total Debt": _row(bs, "Total Debt"),
        "Cash And Cash Equivalents": _row(bs, "Cash And Cash Equivalents"),
        "Ordinary Shares Number": _row(bs, "Ordinary Shares Number"),
        "Stockholders Equity": _row(bs, "Stockholders Equity"),
    }


def _summarize_cashflow(t):
    cf = t.cashflow
    return {
        "colonnes": [str(c.date()) for c in cf.columns] if not cf.empty else [],
        "Free Cash Flow": _row(cf, "Free Cash Flow"),
    }


def _summarize_income_stmt(t):
    inc = t.income_stmt
    return {
        "colonnes": [str(c.date()) for c in inc.columns] if not inc.empty else [],
        "Total Revenue": _row(inc, "Total Revenue"),
        "Operating Income": _row(inc, "Operating Income"),
        "Net Income": _row(inc, "Net Income"),
    }


PROBES = {
    "info (quoteSummary)": _summarize_info,
    "fast_info": _summarize_fast_info,
    "history (chart v8)": _summarize_history,
    "balance_sheet (timeseries)": _summarize_balance_sheet,
    "cashflow (timeseries)": _summarize_cashflow,
    "income_stmt (timeseries)": _summarize_income_stmt,
}


@router.get("/yahoo/{ticker}")
def probe_yahoo(ticker: str):
    results = {}
    for name, summarize in PROBES.items():
        t = yf.Ticker(ticker)  # objet neuf par service, pour qu'un échec n'en contamine pas un autre
        start = time.time()
        with capture_yfinance_errors() as yahoo_errors:
            try:
                data, exception = summarize(t), None
            except Exception as e:
                data, exception = None, f"{type(e).__name__}: {e}"
        results[name] = {
            "duree_s": round(time.time() - start, 2),
            "donnees": data,
            "exception": exception,
            "erreurs_yfinance": yahoo_errors,
        }
    return {"ticker": ticker, "services": results}
