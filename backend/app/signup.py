"""
Inscription libre : n'importe qui peut relier sa copie du Sheet modèle à l'appli, sans passer par
le propriétaire. Les amis déclarés dans USERS_JSON (non administrateurs) sont recopiés dans le même
registre avec leur code actuel : ils sont traités exactement comme les inscrits.

1. La personne copie le Sheet modèle et le partage en Éditeur avec le compte de service.
2. POST /signup/start : l'appli vérifie l'accès et renvoie un code de vérification, à coller dans
   l'onglet Réglages de ce Sheet (ligne code_inscription). Seul quelqu'un qui peut modifier le Sheet
   peut le faire : impossible de relier le Sheet d'un autre dont on aurait vu l'identifiant.
3. POST /signup/finish : le code est vérifié, un code d'accès personnel est créé et renvoyé.
   Refaire l'inscription avec le même Sheet remplace le code d'accès (code perdu).

Les comptes sont rangés dans l'onglet « Utilisateurs » du Sheet du propriétaire (ou de REGISTRY_SHEET_ID) :
nom, empreinte SHA-256 du code d'accès (jamais le code lui-même), identifiant du Sheet, date.
Variables : SIGNUP_OPEN=0 ferme les inscriptions, MAX_SIGNUPS limite le nombre de comptes (50),
PUBLIC_BRIEFS_FOLDER donne aux inscrits les briefs publics (dossier Drive anonymisé).
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import date, timedelta

from .sheets import _find_worksheet, _open_sheet, is_v2
from .users import User

REGISTRY_TAB = "Utilisateurs"
REGISTRY_HEADERS = ["NOM", "EMPREINTE DU CODE", "SHEET", "CRÉÉ LE"]
SETTINGS_TAB = "Réglages"
CODE_KEY = "code_inscription"
TEMPLATE_SHEET_ID = "1Cw44TPxJkpfoXUKkg4eDuDeoHIIvI-UJmzkXi2MYeZU"
CACHE_SECONDS = 60
SHEET_ID_PATTERN = re.compile(r"/d/([A-Za-z0-9_-]{20,})|^([A-Za-z0-9_-]{20,})$")
NAME_PATTERN = re.compile(r"^[\w .'-]{2,30}$")


class SignupError(ValueError):
    """Message montré tel quel à la personne qui s'inscrit."""


def signup_open() -> bool:
    return os.environ.get("SIGNUP_OPEN", "1") != "0"


def max_signups() -> int:
    return int(os.environ.get("MAX_SIGNUPS", "50"))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_sheet_id(text: str) -> str:
    match = SHEET_ID_PATTERN.search((text or "").strip())
    if not match:
        raise SignupError("Lien de Sheet non reconnu : copie l'adresse complète de ton Google Sheet.")
    return match.group(1) or match.group(2)


def service_account_email() -> str | None:
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("client_email")
    except (OSError, TypeError, ValueError):
        return None


def _secret() -> bytes:
    """Clé des codes de vérification : SIGNUP_SECRET, ou à défaut la clé privée du compte de service."""
    secret = os.environ.get("SIGNUP_SECRET")
    if not secret:
        with open(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], encoding="utf-8") as f:
            secret = json.load(f)["private_key"]
    return secret.encode()


def verification_code(sheet_id: str, day: date, secret: bytes) -> str:
    """Code à 6 caractères propre au Sheet et au jour : rien à stocker entre les deux étapes."""
    digest = hmac.new(secret, f"{sheet_id}:{day.isoformat()}".encode(), hashlib.sha256).hexdigest()
    return "PI-" + digest[:6].upper()


def valid_codes(sheet_id: str, today: date, secret: bytes) -> set[str]:
    """Valable le jour même et le lendemain (inscription commencée avant minuit)."""
    return {verification_code(sheet_id, today - timedelta(days=d), secret) for d in (0, 1)}


# --- Registre des comptes, relu au plus toutes les minutes ---
_cache: dict = {"at": 0.0, "users": []}
_lock = threading.Lock()


def registry_sheet_id() -> str:
    from . import users

    return os.environ.get("REGISTRY_SHEET_ID") or next(u.sheet_id for u in users.USERS if u.admin)


def public_briefs_folder() -> str | None:
    """Briefs publics des utilisateurs : PUBLIC_BRIEFS_FOLDER, ou à défaut le dossier déjà donné
    à un ami dans USERS_JSON."""
    from . import users

    return os.environ.get("PUBLIC_BRIEFS_FOLDER") or next(
        (u.briefs_folder for u in users.USERS if not u.admin and u.briefs_folder), None)


def as_member(user: User) -> User:
    """Ami de USERS_JSON vu comme un inscrit : mêmes droits, mêmes briefs."""
    return User(name=user.name, token=None, sheet_id=user.sheet_id, token_hash=token_hash(user.token),
                briefs_folder=public_briefs_folder())


def parse_registry(rows: list[list]) -> list[User]:
    registered = []
    for row in rows[1:]:
        row = (row + [""] * 4)[:4]
        if row[0] and row[1] and row[2]:
            registered.append(User(name=str(row[0]).strip(), token=None, sheet_id=str(row[2]).strip(), token_hash=str(row[1]).strip(),
                                   briefs_folder=public_briefs_folder()))
    return registered


def _registry_worksheet(create: bool):
    sheet = _open_sheet(registry_sheet_id(), write=create)
    ws = _find_worksheet(sheet, REGISTRY_TAB)
    if ws is None and create:
        ws = sheet.add_worksheet(REGISTRY_TAB, rows=200, cols=len(REGISTRY_HEADERS))
        ws.update(range_name="A1", values=[REGISTRY_HEADERS])
    return ws


def missing_members(rows: list[list]) -> list[list]:
    """Lignes à ajouter au registre pour les amis de USERS_JSON qui n'y sont pas encore."""
    from . import users

    known = {str(r[2]).strip() for r in rows[1:] if len(r) > 2}
    return [[u.name, token_hash(u.token), u.sheet_id, date.today().isoformat()]
            for u in users.USERS if not u.admin and u.token and u.sheet_id not in known]


def registered_users(refresh: bool = False) -> list[User]:
    with _lock:
        if refresh or time.time() - _cache["at"] > CACHE_SECONDS:
            try:
                ws = _registry_worksheet(create=False)
                rows = ws.get_values() if ws is not None else [REGISTRY_HEADERS]
                missing = missing_members(rows)
                if missing:
                    ws = _registry_worksheet(create=True)  # lu en lecture seule : rouvert en écriture
                    for row in missing:
                        ws.append_row(row, value_input_option="RAW")
                    rows = rows + missing
                _cache["users"] = parse_registry(rows)
            except Exception:  # registre illisible : on garde la dernière version connue
                pass
            _cache["at"] = time.time()
        return list(_cache["users"])


# --- Étapes de l'inscription ---
def _check_sheet(sheet_id: str):
    from . import users

    if sheet_id == TEMPLATE_SHEET_ID:
        raise SignupError("C'est le Sheet modèle : fais-en d'abord une copie (Fichier > Créer une copie).")
    if any(u.sheet_id == sheet_id for u in users.admins()):
        raise SignupError("Ce Sheet est celui de l'administrateur de l'appli.")
    try:
        sheet = _open_sheet(sheet_id, write=True)
    except Exception:
        email = service_account_email() or "l'adresse du compte de service"
        raise SignupError(f"L'appli n'a pas accès à ce Sheet : partage-le avec {email} en Éditeur, puis réessaie.")
    if not is_v2(sheet):
        raise SignupError("Ce Sheet n'est pas une copie du modèle Portfolio Insights (onglet Opérations introuvable).")
    return sheet


def _settings_tab(sheet):
    ws = _find_worksheet(sheet, SETTINGS_TAB)
    if ws is None:
        ws = sheet.add_worksheet(SETTINGS_TAB, rows=50, cols=2)
        ws.update(range_name="A1", values=[["CLÉ", "VALEUR"]])
    return ws


def start(sheet_url: str, today: date | None = None) -> dict:
    if not signup_open():
        raise SignupError("Les inscriptions sont fermées pour le moment.")
    sheet_id = parse_sheet_id(sheet_url)
    sheet = _check_sheet(sheet_id)
    ws = _settings_tab(sheet)
    if CODE_KEY not in ws.col_values(1):
        ws.append_row([CODE_KEY, ""], value_input_option="RAW")
    existing = next((u for u in registered_users(refresh=True) if u.sheet_id == sheet_id), None)
    return {"sheet_id": sheet_id, "code": verification_code(sheet_id, today or date.today(), _secret()),
            "existing": existing.name if existing else None}


def finish(sheet_url: str, name: str, today: date | None = None) -> dict:
    if not signup_open():
        raise SignupError("Les inscriptions sont fermées pour le moment.")
    from . import users

    sheet_id = parse_sheet_id(sheet_url)
    name = " ".join((name or "").split())
    sheet = _check_sheet(sheet_id)
    ws = _settings_tab(sheet)
    keys = ws.col_values(1)
    row = keys.index(CODE_KEY) + 1 if CODE_KEY in keys else None
    typed = str(ws.cell(row, 2).value or "").strip().upper() if row else ""
    if typed not in valid_codes(sheet_id, today or date.today(), _secret()):
        raise SignupError("Code de vérification absent ou incorrect dans l'onglet Réglages de ton Sheet "
                          f"(case à droite de « {CODE_KEY} »).")

    registered = registered_users(refresh=True)
    existing = next((u for u in registered if u.sheet_id == sheet_id), None)
    if existing is None:
        if not NAME_PATTERN.match(name):
            raise SignupError("Prénom ou pseudo : 2 à 30 lettres, chiffres ou espaces.")
        taken = {u.name.lower() for u in users.admins() + registered}
        if name.lower() in taken:
            raise SignupError("Ce nom est déjà pris : ajoute une initiale par exemple.")
        if len(registered) >= max_signups():
            raise SignupError("L'appli a atteint son nombre maximum de comptes. Réessaie plus tard.")

    token = secrets.token_urlsafe(18)
    registry = _registry_worksheet(create=True)
    if existing is None:
        registry.append_row([name, token_hash(token), sheet_id, date.today().isoformat()], value_input_option="RAW")
    else:  # code perdu : nouveau code d'accès, l'ancien ne marche plus
        sheets_col = registry.col_values(3)
        registry.update_cell(sheets_col.index(sheet_id) + 1, 2, token_hash(token))
        name = existing.name
    ws.update_cell(row, 2, "")  # code utilisé : effacé
    registered_users(refresh=True)
    return {"name": name, "token": token, "recovered": existing is not None}
