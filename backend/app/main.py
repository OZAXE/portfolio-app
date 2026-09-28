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
- GET /portfolio/returns    -> rendement annualisé (TRI) et gain total, dividendes compris
- GET /portfolio/dividends  -> dividendes à venir et revenus projetés sur 12 mois
- POST /operations/import/preview, /operations/import -> import des relevés Trade Republic et Boursorama
- GET / POST /price-alerts, DELETE /price-alerts/{id} -> alertes de prix (onglet Alertes prix du Sheet)
- GET / POST /notifications/settings, POST /notifications/test -> sujet ntfy de l'utilisateur
- GET /portfolio/costs      -> plafond du PEA, frais par année, frais courants des ETF
- POST /settings/accounts, /settings/fees, /allocation -> comptes, frais et allocation cible
- GET /portfolio/chart/{t}  -> cours d'une ligne avec ses achats, ventes et PRU
- POST /history/snapshot    -> relevé quotidien de l'onglet Historique (job nocturne, admin)
- GET /signup/info, POST /signup/start, /signup/finish -> inscription libre (signup.py)
- GET /briefs               -> liste des briefs hebdo (dossier Drive "Briefs")
- GET /briefs/{id}          -> contenu HTML d'un brief
"""

import copy
import logging
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import requests

from .data import INVALID_TICKER_ERROR, SOURCE_UNAVAILABLE_ERROR, fetch_company_financials
from .valuation import evaluate_company
from .briefs import BriefNotFoundError, DriveAccessError, get_brief_html, list_briefs
from .alerts import compute_alerts
from .sheets import add_to_watchlist, get_watchlist, remove_from_watchlist
from .sheets import HoldingLine, SheetNotConfiguredError, get_overview, get_portfolio_positions
from . import users as users_config
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


# Fondamentaux Yahoo gardés quelques heures : ils ne changent qu'aux publications trimestrielles,
# et chaque ouverture de l'appli interrogeait Yahoo pour chaque ligne. Les échecs ne sont pas gardés.
FINANCIALS_CACHE_SECONDS = 3 * 3600
ANALYSIS_WORKERS = 4  # requêtes Yahoo en parallèle (davantage déclenche leur limite de débit)
_financials_cache: dict[str, tuple[float, object]] = {}


def cached_financials(ticker: str):
    key = ticker.strip().upper()
    cached = _financials_cache.get(key)
    if cached and time.monotonic() - cached[0] < FINANCIALS_CACHE_SECONDS:
        return copy.deepcopy(cached[1])
    cf = fetch_company_financials(ticker)
    if not cf.raw_error:
        _financials_cache[key] = (time.monotonic(), copy.deepcopy(cf))
    return cf


@app.get("/analysis/{ticker}", dependencies=[Depends(require_access)])
def get_analysis(ticker: str):
    cf = cached_financials(ticker)
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
    # Une crypto n'a ni comptes ni cash-flows : pas de valeur intrinsèque ni de score
    positions = [p for p in _load_positions(user) if not re.fullmatch(r"[A-Z0-9]{2,10}-(EUR|USD)", p.ticker.upper())]
    with ThreadPoolExecutor(max_workers=ANALYSIS_WORKERS) as pool:
        financials = list(pool.map(cached_financials, [pos.ticker for pos in positions]))
    output = []
    for pos, cf in zip(positions, financials):
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
    for h in overview.holdings:
        by_envelope[h.envelope or "Autre"].append(h)
    total = _totals(overview.holdings)

    def breakdown(key) -> list[dict]:
        groups = defaultdict(float)
        for h in overview.holdings:
            groups[key(h) or "Non classé"] += h.value or 0
        return [{"label": label, "value": round(v, 2), "weight": v / total["value"] if total["value"] else None}
                for label, v in sorted(groups.items(), key=lambda kv: -kv[1])]

    # "États-Unis (indice S&P 500)" et "États-Unis" dans le même groupe
    zone_group = lambda h: str(h.zone).split("(")[0].strip() if h.zone else None
    sectors = [{"sector": b["label"], **b} for b in breakdown(lambda h: h.sector)]
    return {
        "total": total,
        "envelopes": {name: _totals(lines) for name, lines in by_envelope.items()},
        "holdings": [asdict(h) for h in overview.holdings],
        "sectors": sectors,
        "breakdowns": {
            "sector": breakdown(lambda h: h.sector),
            "zone": breakdown(zone_group),
            "currency": breakdown(lambda h: h.currency),
            "pocket": breakdown(lambda h: h.pocket),
        },
        "targets": overview.targets,
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


# Comptes, grilles de frais et allocation cible modifiables depuis l'appli (voir setup_edit.py)
@app.post("/settings/accounts")
def post_accounts(payload: dict = Body(...), user: User = Depends(require_access)):
    from .setup_edit import save_accounts

    return _operation_call(lambda: save_accounts(user.sheet_id, list(payload.get("accounts") or [])))


@app.post("/settings/fees")
def post_fees(payload: dict = Body(...), user: User = Depends(require_access)):
    from .setup_edit import save_fees

    return _operation_call(lambda: save_fees(user.sheet_id, list(payload.get("fees") or [])))


@app.post("/allocation")
def post_allocation(payload: dict = Body(...), user: User = Depends(require_access)):
    from .setup_edit import save_allocation

    return _operation_call(lambda: save_allocation(user.sheet_id, list(payload.get("targets") or []), dict(payload.get("pockets") or {})))


@app.post("/operations")
def post_operation(payload: dict = Body(...), user: User = Depends(require_access)):
    ticker = str(payload.get("ticker") or "").strip().upper()
    stock = next((s for s in (_screener_data("screener.json") or {}).get("stocks", []) if s["ticker"] == ticker), {})
    result = _operation_call(lambda: add_operation(user.sheet_id, payload, stock.get("sector", ""), stock.get("country", "")))
    _forget_operations(user.sheet_id)
    return result


def _forget_operations(sheet_id: str):
    """Caches calculés à partir des opérations, à refaire après une saisie ou un import."""
    for key in [k for k in _performance_cache if k[0] == sheet_id]:
        _performance_cache.pop(key)  # la courbe comparée doit intégrer la nouvelle opération
    _dividends_cache.pop(sheet_id, None)


@app.get("/fx/{currency}", dependencies=[Depends(require_access)])
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


# --- Rendement annualisé (TRI) : tient compte de la date de chaque apport ---
@app.get("/portfolio/returns")
def get_returns(user: User = Depends(require_access)):
    from .returns import returns_summary

    return _sheet_call(lambda: returns_summary(user.sheet_id))


# --- Dividendes à venir (historique Yahoo de chaque titre : une requête par titre, gardé 12 h) ---
DIVIDENDS_CACHE_SECONDS = 12 * 3600
_dividends_cache: dict[str, tuple[float, dict | None]] = {}


@app.get("/portfolio/dividends")
def get_dividend_calendar(user: User = Depends(require_access)):
    from .dividend_calendar import dividend_calendar

    cached = _dividends_cache.get(user.sheet_id)
    if cached and time.monotonic() - cached[0] < DIVIDENDS_CACHE_SECONDS:
        return cached[1]
    result = _sheet_call(lambda: dividend_calendar(user.sheet_id))
    _dividends_cache[user.sheet_id] = (time.monotonic(), result)
    return result


# --- Import des relevés de courtier : aperçu (rien n'est écrit), puis écriture des lignes validées ---
ISIN_TICKERS_URL = "https://raw.githubusercontent.com/OZAXE/portfolio-app/main/screener/isin_tickers.json"
_isin_cache: dict[str, str] = {}


def yahoo_symbol(bloomberg: str, suffix: str) -> str:
    """Code Bloomberg du fichier ISIN -> ticker Yahoo, comme screener/build_universe.py :
    « RR/ » (Rolls-Royce) -> RR.L, « BT/A » -> BT-A.L."""
    return bloomberg.rstrip("/").replace("/", "-").replace(" ", "-") + suffix


def _known_isins() -> dict[str, str]:
    """ISIN -> ticker Yahoo des actions européennes du screener (évite une recherche Yahoo par titre)."""
    if not _isin_cache:
        try:
            data = requests.get(ISIN_TICKERS_URL, timeout=30).json()
            _isin_cache.update({isin: yahoo_symbol(v[0], v[1]) for isin, v in data.items()})
        except Exception:
            pass
    return _isin_cache


@app.post("/operations/import/preview")
def preview_operations_import(payload: dict = Body(...), user: User = Depends(require_access)):
    from .imports import preview_import

    return _operation_call(lambda: preview_import(user.sheet_id, payload.get("account"), payload.get("files") or [], _known_isins()))


# Doublons déjà présents dans l'onglet Opérations (voir duplicates.py)
@app.get("/operations/duplicates")
def get_duplicates(user: User = Depends(require_access)):
    from .duplicates import list_duplicates

    return _operation_call(lambda: list_duplicates(user.sheet_id))


@app.post("/operations/delete")
def post_delete_operations(payload: dict = Body(...), user: User = Depends(require_access)):
    from .duplicates import delete_operations

    result = _operation_call(lambda: delete_operations(user.sheet_id, list(payload.get("rows") or [])))
    _forget_operations(user.sheet_id)
    return result


# Repartir de zéro (avec sauvegarde dans le Sheet) et annulation, voir reset.py
@app.post("/operations/reset")
def post_reset_operations(payload: dict = Body(...), user: User = Depends(require_access)):
    from .reset import reset_operations

    result = _operation_call(lambda: reset_operations(user.sheet_id, payload.get("account") or None,
                                                      bool(payload.get("imported_only")), bool(payload.get("dry_run"))))
    if not payload.get("dry_run"):
        _forget_operations(user.sheet_id)
    return result


@app.post("/operations/restore")
def post_restore_operations(payload: dict = Body(...), user: User = Depends(require_access)):
    from .reset import restore_backup

    result = _operation_call(lambda: restore_backup(user.sheet_id, payload.get("backup"), payload.get("history_backup")))
    _forget_operations(user.sheet_id)
    return result


@app.post("/operations/import")
def write_operations_import(payload: dict = Body(...), user: User = Depends(require_access)):
    from .imports import write_import

    result = _operation_call(lambda: write_import(user.sheet_id, payload.get("account"), payload.get("operations") or []))
    _forget_operations(user.sheet_id)
    return result


# --- Alertes de prix et notifications (onglets Alertes prix et Réglages du Sheet de chaque utilisateur) ---
APP_URL = "https://portfolio-front-8t6m.onrender.com/#portfolio"


@app.get("/price-alerts")
def get_price_alerts(user: User = Depends(require_access)):
    from .notifications import list_price_alerts

    return _sheet_call(lambda: list_price_alerts(user.sheet_id))


@app.post("/price-alerts")
def create_price_alert(payload: dict = Body(...), user: User = Depends(require_access)):
    from .notifications import add_price_alert

    ticker = _checked_ticker(str(payload.get("ticker") or ""))
    return _operation_call(lambda: add_price_alert(user.sheet_id, ticker, payload.get("direction"), payload.get("price"), payload.get("note", "")))


@app.delete("/price-alerts/{alert_id}")
def remove_price_alert(alert_id: str, user: User = Depends(require_access)):
    from .notifications import delete_price_alert

    return _operation_call(lambda: delete_price_alert(user.sheet_id, alert_id))


@app.post("/price-alerts/{alert_id}/rearm")
def rearm_price_alert(alert_id: str, user: User = Depends(require_access)):
    from .notifications import set_alert_triggered

    return _operation_call(lambda: set_alert_triggered(user.sheet_id, [alert_id], None))


@app.get("/notifications/settings")
def get_notification_settings(user: User = Depends(require_access)):
    from .notifications import get_topic

    return {"topic": _sheet_call(lambda: get_topic(user.sheet_id)), "admin": user.admin}


@app.post("/notifications/settings")
def save_notification_settings(payload: dict = Body(...), user: User = Depends(require_access)):
    from .notifications import set_topic

    return {"topic": _operation_call(lambda: set_topic(user.sheet_id, payload.get("topic")))}


@app.post("/notifications/test")
def test_notification(user: User = Depends(require_access)):
    from .notifications import get_topic, send_ntfy

    topic = _sheet_call(lambda: get_topic(user.sheet_id))
    if not topic:
        raise HTTPException(status_code=400, detail="Enregistre d'abord ton sujet ntfy")
    send_ntfy(topic, "Portfolio Insights", f"Notifications activées pour {user.name}. Tu recevras ici tes alertes de la nuit.", "white_check_mark", APP_URL)
    return {"sent": True}


# Réservé au job nocturne (code du propriétaire) : de quoi calculer les alertes de chaque utilisateur
@app.get("/notifications/users", dependencies=[Depends(require_admin)])
def notification_users():
    from .notifications import get_topic, list_price_alerts

    result = []
    for u in users_config.all_users():
        try:
            result.append({
                "name": u.name, "admin": u.admin, "topic": get_topic(u.sheet_id),
                "positions": sorted({p.ticker.upper() for p in get_portfolio_positions(u.sheet_id)}),
                "watchlist": get_watchlist(u.sheet_id),
                "price_alerts": [a for a in list_price_alerts(u.sheet_id) if not a["triggered"]],
            })
        except Exception as e:  # un Sheet inaccessible ne bloque pas les autres
            result.append({"name": u.name, "admin": u.admin, "error": str(e)})
    return result


# --- Inscription libre (voir signup.py) : sans code d'accès, limitée par adresse IP ---
_signup_hits: dict[str, list[float]] = defaultdict(list)
SIGNUP_LIMIT = 20  # tentatives par heure et par adresse


def _signup_call(request: Request, call):
    from .signup import SignupError

    # Render ajoute l'adresse réelle en dernier dans X-Forwarded-For (les premières peuvent être inventées)
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[-1].strip()
    now = time.time()
    _signup_hits[ip] = [t for t in _signup_hits[ip] if now - t < 3600] + [now]
    if len(_signup_hits[ip]) > SIGNUP_LIMIT:
        raise HTTPException(status_code=429, detail="Trop de tentatives : réessaie dans une heure.")
    try:
        return call()
    except SignupError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SheetNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=f"Compte de service non configuré : {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Écriture dans le Sheet impossible (partagé en Éditeur ?) : {e}")


@app.get("/signup/info")
def signup_info():
    from .signup import TEMPLATE_SHEET_ID, service_account_email, signup_open

    return {"open": signup_open(), "service_account": service_account_email(),
            "template_copy_url": f"https://docs.google.com/spreadsheets/d/{TEMPLATE_SHEET_ID}/copy"}


@app.post("/signup/start")
def signup_start(request: Request, payload: dict = Body(...)):
    from .signup import start

    return _signup_call(request, lambda: start(str(payload.get("sheet") or "")))


@app.post("/signup/finish")
def signup_finish(request: Request, payload: dict = Body(...)):
    from .signup import finish

    return _signup_call(request, lambda: finish(str(payload.get("sheet") or ""), str(payload.get("name") or "")))


# Frais courants des ETF détenus : état privé du job nocturne (screener/etf_fees.py), jamais publié
@app.get("/admin/etf-fees", dependencies=[Depends(require_admin)])
def get_etf_fees():
    from .etf_fees_store import read_fee_state

    return _sheet_call(read_fee_state)


@app.post("/admin/etf-fees", dependencies=[Depends(require_admin)])
def save_etf_fees(payload: dict = Body(...)):
    from .etf_fees_store import write_fee_state

    return _sheet_call(lambda: write_fee_state(payload))


# Historique reconstitué à partir des opérations (après un import ou une opération passée)
@app.post("/history/rebuild")
def post_history_rebuild(payload: dict = Body(default={}), user: User = Depends(require_access)):
    from datetime import date

    from .history import rebuild_history

    since = payload.get("since")
    try:
        since = date.fromisoformat(since) if since else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Date attendue au format AAAA-MM-JJ")
    return _operation_call(lambda: rebuild_history(user.sheet_id, since))


# Relevé quotidien de l'onglet Historique de chaque utilisateur (job nocturne, code du propriétaire)
@app.post("/history/snapshot", dependencies=[Depends(require_admin)])
def history_snapshot(day: str):
    from datetime import date

    from .history import record_snapshot
    from .notifications import get_topic

    try:
        when = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date attendue au format AAAA-MM-JJ")
    result = []
    for u in users_config.all_users():
        try:
            result.append({"name": u.name, "admin": u.admin, "topic": get_topic(u.sheet_id), **record_snapshot(u.sheet_id, when)})
        except Exception as e:  # un Sheet illisible ou un cours en erreur ne bloque pas les autres
            result.append({"name": u.name, "admin": u.admin, "error": str(e)})
    return result


@app.post("/notifications/triggered", dependencies=[Depends(require_admin)])
def mark_alerts_triggered(payload: dict = Body(...)):
    from datetime import date

    from .notifications import set_alert_triggered

    target = next((u for u in users_config.all_users() if u.name == payload.get("user")), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Utilisateur inconnu")
    return _operation_call(lambda: set_alert_triggered(target.sheet_id, payload.get("ids") or [], payload.get("date") or date.today().isoformat()))


# --- Plafond du PEA, frais payés et frais courants des ETF ---
@app.get("/portfolio/costs")
def get_costs(user: User = Depends(require_access)):
    from datetime import date

    from .costs import ensure_fee_column, etf_costs, fees_by_year, manual_fees, pea_ceiling
    from .realized import read_operations
    from .sheets import UNFORMATTED, _open_sheet, _worksheet

    def compute():
        operations, envelopes, _ = read_operations(user.sheet_id)
        titres_ws = _worksheet(_open_sheet(user.sheet_id, write=True), "Titres")
        try:
            ensure_fee_column(titres_ws)
        except Exception:
            pass  # compte de service en lecture seule : la colonne reste à ajouter à la main
        manual = manual_fees(titres_ws.get_values(value_render_option=UNFORMATTED))
        # Frais courants récupérés chaque nuit par screener/etf_fees.py (Yahoo est souvent bloqué ici)
        # et rangés dans le Sheet du propriétaire (onglet Frais ETF),
        # remplacés par ceux saisis dans l'onglet Titres
        from .etf_fees_store import read_fee_state

        fees_file = read_fee_state()
        ter = {t: v.get("ter") for t, v in fees_file.get("etfs", {}).items()} | manual
        holdings = [{"ticker": h.ticker.upper(), "name": h.name, "value": h.value, "manual": h.ticker.upper() in manual}
                    for h in get_overview(user.sheet_id).holdings if h.kind == "ETF"]
        return {"pea": pea_ceiling(operations, envelopes, date.today()),
                "years": fees_by_year(operations, envelopes), "etf": etf_costs(holdings, ter)}

    return _sheet_call(compute)


@app.get("/portfolio/chart/{ticker}")
def get_position_chart(ticker: str, user: User = Depends(require_access)):
    from .performance import position_chart

    ticker = _checked_ticker(ticker)
    def build():
        try:
            return position_chart(user.sheet_id, ticker)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    return _sheet_call(build)
