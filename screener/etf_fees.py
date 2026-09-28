"""
Frais courants (TER) des ETF détenus par les utilisateurs de l'appli.

Lancé avec le screener nocturne :
    python screener/etf_fees.py --data-dir data

Yahoo répond depuis GitHub Actions mais souvent pas depuis le serveur Render : ce script les
récupère et les enregistre par l'API (onglet « Frais ETF » du Sheet du propriétaire), avec le code
du propriétaire (secret APP_ACCESS_TOKEN). Rien n'est publié ni écrit dans les journaux : le repo
et ses journaux sont publics, et la liste des titres révélerait les portefeuilles.
Chaque titre est revérifié tous les 30 jours.
"""

import argparse
import logging
import os
from datetime import date, timedelta
from pathlib import Path

from notify import api_get, api_post

REFRESH_DAYS = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("etf_fees")


def fetch_fee(ticker: str) -> dict:
    """{etf, ter (en %, 0,38 = 0,38 %), name} d'après Yahoo ; ter None si Yahoo ne le donne pas."""
    import yfinance as yf

    info = yf.Ticker(ticker).info or {}
    ter = info.get("netExpenseRatio") or info.get("annualReportExpenseRatio")
    return {"etf": info.get("quoteType") == "ETF", "ter": float(ter) if ter is not None else None,
            "name": info.get("longName") or info.get("shortName")}


def stale(entry: dict | None, today: date) -> bool:
    return entry is None or date.fromisoformat(entry["updated"]) < today - timedelta(days=REFRESH_DAYS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    token = os.environ.get("APP_ACCESS_TOKEN")
    if not token:
        log.info("secret APP_ACCESS_TOKEN absent : frais des ETF non mis à jour")
        return

    # Ancien fichier public : supprimé de la branche screener-data
    (Path(args.data_dir) / "etf_fees.json").unlink(missing_ok=True)
    known = api_get("/admin/etf-fees", token)
    etfs, others = known.get("etfs", {}), known.get("not_etf", {})
    today = date.today()
    checked = failed = 0

    tickers = sorted({t for u in api_get("/notifications/users", token) for t in u.get("positions", [])})
    for ticker in tickers:
        if not stale(etfs.get(ticker) or others.get(ticker), today):
            continue
        try:
            fee = fetch_fee(ticker)
        except Exception:
            failed += 1
            continue
        checked += 1
        if fee["etf"]:
            etfs[ticker] = {"ter": fee["ter"], "name": fee["name"], "updated": today.isoformat()}
            others.pop(ticker, None)
        else:  # action : mémorisée pour ne pas redemander chaque nuit
            others[ticker] = {"updated": today.isoformat()}

    api_post("/admin/etf-fees", token, {"etfs": etfs, "not_etf": others})
    log.info("frais courants : %d titres vérifiés, %d échecs Yahoo", checked, failed)


if __name__ == "__main__":
    main()
