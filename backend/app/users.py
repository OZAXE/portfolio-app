"""
Utilisateurs de l'appli : chacun a son code d'accès et son propre Google Sheet
(une copie du modèle, partagée en Éditeur avec le compte de service).

Configuration sur Render, variable d'environnement USERS_JSON :
    [{"name": "Enzo", "token": "...", "sheet_id": "...", "admin": true, "briefs_folder": "..."},
     {"name": "Paul", "token": "...", "sheet_id": "..."}]

Sans USERS_JSON, un seul utilisateur : le propriétaire, avec APP_ACCESS_TOKEN et SHEET_ID
(ou le Sheet par défaut). Sans code d'accès du tout, l'API reste ouverte (installation en cours).
"""

import json
import os
import secrets
from dataclasses import dataclass

# Sheet du propriétaire si rien n'est configuré (format v2, voir workbook.py)
DEFAULT_SHEET_ID = "1d9wtW41Ncerh6O0mmYC5YpADIkNQCI0GNUp9Xo-OZT4"
DEFAULT_BRIEFS_FOLDER = "1hlL6XgoWhVdlNLzUKmy2s-C0Ipo1Uw52"


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
        sheet_id=os.environ.get("SHEET_ID", DEFAULT_SHEET_ID),
        admin=True,
        briefs_folder=DEFAULT_BRIEFS_FOLDER,
    )]


USERS = load_users()


def access_protected() -> bool:
    return any(u.token for u in USERS)


def resolve(token: str | None) -> User | None:
    """Utilisateur correspondant au code d'accès (comparaison à temps constant)."""
    if not access_protected():
        return USERS[0]
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
