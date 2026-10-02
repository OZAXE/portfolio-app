"""
Utilisateurs de l'appli : chacun a son code d'accès et son propre Google Sheet
(une copie du modèle, partagée en Éditeur avec le compte de service).

Configuration sur Render, variable d'environnement USERS_JSON :
    [{"name": "Enzo", "token": "...", "sheet_id": "...", "admin": true, "briefs_folder": "..."},
     {"name": "Paul", "token": "...", "sheet_id": "..."}]

Sans USERS_JSON, un seul utilisateur : le propriétaire, avec APP_ACCESS_TOKEN, SHEET_ID et
BRIEFS_FOLDER. Sans code d'accès du tout, l'API refuse tout, sauf ALLOW_OPEN_API=1 (installation,
essai en local) : une variable effacée par erreur sur Render ne doit pas ouvrir les portefeuilles.
Aucun identifiant de Sheet ou de dossier dans le code : le repo est public.
"""

import json
import os
import secrets
from dataclasses import dataclass

@dataclass(frozen=True)
class User:
    name: str
    token: str | None
    sheet_id: str
    admin: bool = False
    briefs_folder: str | None = None
    token_hash: str | None = None  # comptes créés par inscription libre (signup.py) : empreinte seulement


def load_users() -> list[User]:
    raw = os.environ.get("USERS_JSON")
    if raw:
        return [
            User(name=u["name"], token=u["token"], sheet_id=u["sheet_id"], admin=bool(u.get("admin")),
                 briefs_folder=u.get("briefs_folder"))
            for u in json.loads(raw)
        ]
    return [User(
        name="Propriétaire",
        token=os.environ.get("APP_ACCESS_TOKEN"),
        sheet_id=os.environ.get("SHEET_ID", ""),
        admin=True,
        briefs_folder=os.environ.get("BRIEFS_FOLDER"),
    )]


USERS = load_users()


def access_protected() -> bool:
    return any(u.token for u in USERS)


def open_api_allowed() -> bool:
    """API sans code d'accès seulement sur demande explicite. Avant, elle s'ouvrait dès qu'aucun code
    n'était configuré : supprimer APP_ACCESS_TOKEN sur Render donnait l'accès administrateur à tous."""
    return os.environ.get("ALLOW_OPEN_API") == "1"


def resolve(token: str | None) -> User | None:
    """Utilisateur correspondant au code d'accès (comparaison à temps constant)."""
    if not access_protected():
        return USERS[0] if open_api_allowed() else None
    if not token:
        return None
    for user in admins():
        if user.token and secrets.compare_digest(token, user.token):
            return user
    from .signup import token_hash

    digest = token_hash(token)
    return next((u for u in members() if secrets.compare_digest(digest, u.token_hash)), None)


def admins() -> list[User]:
    return [u for u in USERS if u.admin]


def members(refresh: bool = False) -> list[User]:
    """Tous les utilisateurs non administrateurs, traités de la même façon qu'ils viennent de
    l'inscription libre ou de USERS_JSON (recopiés dans le registre, voir signup.py)."""
    from .signup import as_member, registered_users

    registered = registered_users(refresh=refresh)
    known = {u.sheet_id for u in registered}
    # Registre illisible ou pas encore à jour : l'ami de USERS_JSON garde l'accès, avec les mêmes droits
    return registered + [as_member(u) for u in USERS if not u.admin and u.token and u.sheet_id not in known]


def all_users() -> list[User]:
    """Administrateurs puis tous les autres utilisateurs (job nocturne)."""
    return admins() + members(refresh=True)
