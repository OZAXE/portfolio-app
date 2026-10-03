"""
Briefs marchés hebdomadaires : fichiers HTML déposés par la tâche Claude Cowork
dans le dossier Google Drive "Briefs", partagé en lecture avec le compte de service.

Le nom de fichier porte la date de publication (2026-09-26.html, un samedi) : c'est
lui qui sert de date et d'ordre d'affichage ; le front en déduit le lundi de la semaine.
Un seul brief par date : le 26/09/2026, « Briefs » contenait deux copies de
2026-09-26.html (import en bloc puis nouveau dépôt), affichées en double.
"""

import re
import time
from datetime import date

from google.auth.transport.requests import AuthorizedSession

from .sheets import google_credentials

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_API = "https://www.googleapis.com/drive/v3/files"

LIST_CACHE_SECONDS = 600
DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")

_session: AuthorizedSession | None = None
_list_cache: dict[str, tuple[float, list[dict]]] = {}  # dossier -> (instant, briefs)
_content_cache: dict[tuple[str, str], str] = {}  # (id, modifiedTime) -> HTML


class BriefNotFoundError(LookupError):
    pass


class DriveAccessError(RuntimeError):
    pass


def _drive() -> AuthorizedSession:
    global _session
    if _session is None:
        _session = AuthorizedSession(google_credentials(DRIVE_SCOPES))
    return _session


def _get(url: str, **params):
    response = _drive().get(url, params=params, timeout=30)
    if response.status_code == 403 and "accessNotConfigured" in response.text:
        raise DriveAccessError(
            "API Google Drive non activée dans le projet Google Cloud du compte de service "
            "(console.cloud.google.com > API et services > Bibliothèque > Google Drive API > Activer)"
        )
    if response.status_code == 404:
        raise BriefNotFoundError("brief introuvable (ou dossier non partagé avec le compte de service)")
    response.raise_for_status()
    return response


def list_briefs(folder_id: str) -> list[dict]:
    """Briefs du dossier Drive, du plus récent au plus ancien : id, date (ISO) et titre."""
    cached = _list_cache.get(folder_id)
    if cached and time.monotonic() - cached[0] < LIST_CACHE_SECONDS:
        return cached[1]

    files, page_token = [], None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)",
            "pageSize": 200,
        }
        if page_token:
            params["pageToken"] = page_token
        data = _get(DRIVE_API, **params).json()
        files += data.get("files", [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    by_date: dict[str, dict] = {}
    for f in files:
        day = _brief_date(f["name"])
        if day is None:
            continue
        brief = {"id": f["id"], "date": day, "name": f["name"], "modified": f["modifiedTime"]}
        # Deux fichiers à la même date : le dernier modifié est la version à jour
        if day not in by_date or brief["modified"] > by_date[day]["modified"]:
            by_date[day] = brief
    briefs = sorted(by_date.values(), key=lambda b: b["date"], reverse=True)
    _list_cache[folder_id] = (time.monotonic(), briefs)
    return briefs


def _brief_date(name: str) -> str | None:
    """Date ISO d'un nom de brief, None si ce n'est pas un brief : la référence de mise en page
    (DA_de_reference.html), un fichier non HTML ou une date impossible (2026-13-45.html)."""
    match = DATE_IN_NAME.search(name)
    if not name.lower().endswith((".html", ".htm")) or not match:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


def get_brief_html(folder_id: str, brief_id: str) -> str:
    # Seuls les fichiers du dossier de l'utilisateur sont servis (pas n'importe quel fichier Drive)
    brief = next((b for b in list_briefs(folder_id) if b["id"] == brief_id), None)
    if brief is None:
        raise BriefNotFoundError("brief introuvable dans le dossier Briefs")
    key = (brief_id, brief["modified"])
    if key not in _content_cache:
        response = _get(f"{DRIVE_API}/{brief_id}", alt="media")
        _content_cache[key] = response.content.decode("utf-8", errors="replace")
    return _content_cache[key]
