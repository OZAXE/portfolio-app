"""
Briefs marchés hebdomadaires : fichiers HTML déposés par la tâche Claude Cowork
dans le dossier Google Drive "Briefs", partagé en lecture avec le compte de service.

Le nom de fichier porte la date (2026-09-26.html) : c'est lui qui sert de date
et d'ordre d'affichage.
"""

import re
import time

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

    briefs = []
    for f in files:
        match = DATE_IN_NAME.search(f["name"])
        if not f["name"].lower().endswith((".html", ".htm")) or not match:
            continue  # la référence de mise en page (DA_de_reference.html) et autres fichiers sont ignorés
        briefs.append({"id": f["id"], "date": match.group(1), "name": f["name"], "modified": f["modifiedTime"]})
    briefs.sort(key=lambda b: b["date"], reverse=True)
    _list_cache[folder_id] = (time.monotonic(), briefs)
    return briefs


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
