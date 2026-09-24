"""
Lecture des positions depuis ton Google Sheet "Investissement".

Pour que ça marche, il faut un compte de service Google (fichier JSON de
credentials) partagé en lecture sur ta feuille. C'est la méthode standard
pour qu'un script accède à un Google Sheet sans passer par ton compte perso.
Doc rapide pour le créer : console.cloud.google.com > IAM & Admin >
Service Accounts > créer une clé JSON, puis partager le Sheet avec l'email
du compte de service (ça ressemble à un email, genre xxx@xxx.iam.gserviceaccount.com).

Le nom de l'onglet et les colonnes ci-dessous (TICKER, QUANTITE) sont à
adapter à la structure réelle de ton Sheet "Investissement" une fois qu'on
regarde ensemble sa mise en page exacte.
"""

import os
import gspread
from google.oauth2.service_account import Credentials
from dataclasses import dataclass

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SHEET_ID = "1XMLtJmBYTvngn9weClVpc9RS2pSqshBJv2MwDvtVcRw"  # fileId de ton Sheet "Investissement"


@dataclass
class Position:
    ticker: str
    quantity: float
    envelope: str | None = None  # PEA / CTO


def get_portfolio_positions(worksheet_name: str = "Portefeuille") -> list[Position]:
    creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path:
        raise RuntimeError(
            "Variable d'environnement GOOGLE_SERVICE_ACCOUNT_JSON manquante "
            "(chemin vers le fichier de credentials du compte de service)."
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SHEET_ID)
    ws = sheet.worksheet(worksheet_name)
    rows = ws.get_all_records()  # liste de dicts, clés = en-têtes de colonnes

    positions = []
    for row in rows:
        ticker = row.get("TICKER") or row.get("Ticker")
        quantity = row.get("QUANTITE") or row.get("Quantité")
        envelope = row.get("ENVELOPPE") or row.get("Enveloppe")
        if ticker and quantity:
            positions.append(
                Position(ticker=str(ticker).strip(), quantity=float(quantity), envelope=envelope)
            )
    return positions
