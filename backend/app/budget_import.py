"""
Relevés du compte courant lus sur Google Drive (novembre 2026, demande d'Enzo : ne plus passer par son PC).

Avant : update_suivi.py catégorisait sur le PC, puis envoyer_budget.py envoyait outputs.xlsx (tâche Windows de 21 h).
Le budget n'avançait que si le PC était allumé (rien entre le 06/10 et le 05/11/2026). Maintenant :
1. Enzo dépose l'export Excel du Crédit Agricole (CA<date>_<heure>.xlsx) dans un dossier Drive, depuis son téléphone ;
2. ce dossier est partagé en lecture avec le compte de service (comme celui des briefs), son adresse est rangée dans
   l'onglet Réglages (clé budget_folder, saisie dans Plus > Budget) ;
3. chaque matin (notify.py) et au bouton « Chercher les nouveaux relevés », sync() lit les fichiers pas encore traités,
   catégorise avec l'onglet « Règles budget » (budget_rules.py) et ajoute les opérations nouvelles à l'onglet Budget,
   qui devient la référence (outputs.xlsx n'est plus mis à jour) ;
4. les opérations qu'aucune règle ne reconnaît arrivent « À catégoriser » et se classent dans l'appli
   (categorize_operation), avec la possibilité d'en faire une règle pour les fois suivantes.

Lecture seule sur Drive : les fichiers ne sont pas déplacés dans « traités » comme avant, leurs identifiants (et date de
modification) sont gardés dans Réglages (clé budget_files). Un fichier remplacé par une version plus récente est relu ;
le dédoublonnage (budget_rules.new_lines) évite alors les doublons.
"""

import json
import re
from collections import Counter
from datetime import date

from .briefs import DRIVE_API, DRIVE_SCOPES, BriefNotFoundError
from .briefs import _get as _drive_get
from .budget import BUDGET_HEADERS, BUDGET_TAB, parse_budget
from .budget_rules import (RULE_KINDS, RULES_HEADERS, RULES_TAB, UNCATEGORIZED, Rule, budget_kind, budget_operation,
                           categorize, compile_rules, extract_key, new_lines, op_key, read_export_file)
from .notifications import _tab, get_setting, set_setting
from .operations import OperationError

FOLDER_KEY = "budget_folder"
FILES_KEY = "budget_files"
SEED_FILE = "regles_budget.json"  # règles de départ (migration depuis le PC), lues une fois si l'onglet n'existe pas
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"  # export converti par Drive à l'envoi depuis le téléphone
MAX_FILES_PER_SYNC = 20
MAX_REMEMBERED = 300
FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,100}$")


# --- Dossier Drive ---

def service_account_email() -> str | None:
    """Adresse avec laquelle partager le dossier (affichée dans Plus > Budget)."""
    try:
        from .sheets import google_credentials

        return google_credentials(DRIVE_SCOPES).service_account_email
    except Exception:
        return None


def _get(url: str, **params):
    try:
        return _drive_get(url, **params)
    except BriefNotFoundError:
        email = service_account_email()
        raise OperationError("Dossier ou fichier Drive introuvable : vérifie le lien et que le dossier est partagé"
                             + (f" avec {email}" if email else " avec le compte de service de l'appli"))


def folder_id_of(text: str) -> str:
    """Identifiant d'un dossier depuis son lien Drive (« https://drive.google.com/drive/folders/1wjG...?usp=sharing »)
    ou l'identifiant seul."""
    text = (text or "").strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", text) or re.search(r"[?&]id=([A-Za-z0-9_-]+)", text)
    folder = match.group(1) if match else text
    if not FOLDER_ID.match(folder):
        raise OperationError("Lien de dossier Drive invalide : copie le lien du dossier (Partager > Copier le lien)")
    return folder


def set_folder(sheet_id: str, text: str | None) -> str | None:
    folder = folder_id_of(text) if (text or "").strip() else None
    set_setting(sheet_id, FOLDER_KEY, folder)
    return folder


def drive_files(folder: str) -> list[dict]:
    """Fichiers du dossier (pas des sous-dossiers : « traités » de l'ancien script est ignoré), plus anciens d'abord."""
    files, token = [], None
    while True:
        params = {"q": f"'{folder}' in parents and trashed = false",
                  "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)", "pageSize": 200, "orderBy": "createdTime"}
        if token:
            params["pageToken"] = token
        data = _get(DRIVE_API, **params).json()
        files += data.get("files", [])
        token = data.get("nextPageToken")
        if not token:
            return files


def is_export(f: dict) -> bool:
    return f.get("mimeType") == GOOGLE_SHEET or (f.get("mimeType") == XLSX or f["name"].lower().endswith(".xlsx"))


def download(f: dict) -> bytes:
    if f.get("mimeType") == GOOGLE_SHEET:
        return _get(f"{DRIVE_API}/{f['id']}/export", mimeType=XLSX).content
    return _get(f"{DRIVE_API}/{f['id']}", alt="media").content


# --- Règles (onglet « Règles budget ») ---

def parse_rules(rows: list[list]) -> list[Rule]:
    rules = []
    for row in rows:
        row = (list(row) + [""] * 4)[:4]
        kind, pattern, category, sub = (str(v).strip() for v in row)
        if kind in RULE_KINDS and pattern and category:
            rules.append(Rule(kind, pattern, category, sub))
    return rules


def read_rules(sheet_id: str, folder: str | None = None) -> list[Rule]:
    ws = _tab(sheet_id, RULES_TAB, RULES_HEADERS, create=False)
    if ws is None:
        return seed_rules(sheet_id, folder) if folder else []
    return parse_rules(ws.get_values()[1:])


def seed_rules(sheet_id: str, folder: str) -> list[Rule]:
    """Première fois : crée l'onglet avec les règles de regles_budget.json s'il est dans le dossier (règles du PC
    converties), sinon vide. Format : [{"type": "exacte" | "motif", "motif", "categorie", "sous_categorie"}, ...] ou la
    forme courte [["exacte", "boulangerie du port", "Courses", "Boulangerie"], ...]."""
    seed = next((f for f in drive_files(folder) if f["name"] == SEED_FILE), None)
    rules = []
    if seed is not None:
        data = json.loads(download(seed).decode("utf-8"))
        rules = parse_rules([[r.get("type"), r.get("motif"), r.get("categorie"), r.get("sous_categorie", "")] if isinstance(r, dict)
                             else r for r in data if isinstance(r, (dict, list))])  # objets ou [type, motif, catégorie, sous-catégorie]
    ws = _tab(sheet_id, RULES_TAB, RULES_HEADERS, create=True)
    today = date.today().isoformat()
    ws.update(range_name="A1", values=[RULES_HEADERS] + [[r.kind, r.pattern, r.category, r.subcategory, today] for r in rules],
              value_input_option="RAW")
    return rules


def add_rule(sheet_id: str, rule: Rule) -> None:
    ws = _tab(sheet_id, RULES_TAB, RULES_HEADERS, create=True)
    ws.append_row([rule.kind, rule.pattern, rule.category, rule.subcategory, date.today().isoformat()], value_input_option="RAW")


# --- Import ---

def remembered(sheet_id: str) -> dict[str, str]:
    try:
        data = json.loads(get_setting(sheet_id, FILES_KEY) or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def to_row(op: dict, sent: str, key: str) -> list:
    """Ligne de l'onglet Budget (budget.budget_row, plus la clé de règle pour une opération à catégoriser)."""
    from .budget import budget_row

    return budget_row(op, sent) + [key if op["kind"] == "a_categoriser" else ""]


def sync(sheet_id: str, folder: str | None = None, today: date | None = None) -> dict:
    """Lit les nouveaux exports du dossier et ajoute leurs opérations à l'onglet Budget. Un fichier illisible (pas un
    export du CA) est signalé et retenu comme traité, pour ne pas le relire chaque matin ; le remplacer par un bon
    fichier (autre date de modification) le fait relire."""
    folder = folder or get_setting(sheet_id, FOLDER_KEY)
    if not folder:
        raise OperationError("Aucun dossier Drive configuré pour les relevés (Plus > Budget)")
    sent = (today or date.today()).isoformat()
    done = remembered(sheet_id)
    todo = [f for f in drive_files(folder) if is_export(f) and f["name"] != SEED_FILE and done.get(f["id"]) != f["modifiedTime"]]
    result = {"files": [], "added": 0, "to_categorize": 0, "errors": [], "sent": sent}
    if not todo:
        return result
    rules = read_rules(sheet_id, folder)
    exact, patterns = compile_rules(rules)
    ws = _tab(sheet_id, BUDGET_TAB, BUDGET_HEADERS, create=True)
    values = ws.get_values()
    stored = values[1:]
    known = Counter(op_key(r[0], r[1], r[2]) for r in ((list(r) + [""] * 3)[:3] for r in stored) if _plausible(r))
    rows = []
    for f in todo[:MAX_FILES_PER_SYNC]:
        try:
            lines = read_export_file(download(f))
        except Exception as e:  # mauvais fichier : signalé, on passe au suivant
            result["errors"].append(f"{f['name']} : {e}")
            done[f["id"]] = f["modifiedTime"]
            continue
        fresh = new_lines(lines, known)
        for line in fresh:
            op = budget_operation(line, categorize(line, exact, patterns))
            rows.append(to_row(op, sent, extract_key(line.label)))
        result["files"].append({"name": f["name"], "read": len(lines), "added": len(fresh)})
        done[f["id"]] = f["modifiedTime"]
    if rows:
        if ws.col_count < len(BUDGET_HEADERS):  # onglet créé par l'ancien envoi depuis le PC : 7 colonnes
            ws.resize(cols=len(BUDGET_HEADERS))
        if not values or values[0] != BUDGET_HEADERS:
            ws.update(range_name="A1", values=[BUDGET_HEADERS], value_input_option="RAW")
        ws.append_rows(rows, value_input_option="RAW")  # brut : un libellé qui commence par « = » reste du texte
    result["added"] = len(rows)
    result["to_categorize"] = sum(r[5] == "a_categoriser" for r in rows)
    set_setting(sheet_id, FILES_KEY, json.dumps(dict(list(done.items())[-MAX_REMEMBERED:])))
    return result


def _plausible(row: list) -> bool:
    try:
        float(row[2])
        return bool(row[0])
    except (TypeError, ValueError):
        return False


# --- Validation dans l'appli ---

def categorize_operation(sheet_id: str, payload: dict) -> dict:
    """Range une opération « À catégoriser » (ou corrige une catégorie). payload : row (numéro de ligne), date, label,
    amount (pour vérifier que la ligne n'a pas bougé), category, subcategory, remember (créer une règle exacte sur la
    clé du libellé : les autres opérations à catégoriser de même clé sont rangées en même temps)."""
    category = " ".join(str(payload.get("category") or "").split())[:60]
    sub = " ".join(str(payload.get("subcategory") or "").split())[:60]
    if not category or category == UNCATEGORIZED:
        raise OperationError("Choisis une catégorie")
    ws = _tab(sheet_id, BUDGET_TAB, BUDGET_HEADERS, create=False, write=True)
    if ws is None:
        raise OperationError("Onglet Budget introuvable")
    operations = parse_budget(ws.get_values()[1:])
    target = next((o for o in operations if o["row"] == payload.get("row")), None)
    expected = op_key(str(payload.get("date")), str(payload.get("label")), _number(payload.get("amount")))
    if target is None or op_key(target["date"], target["label"], target["amount"]) != expected:
        raise OperationError("L'onglet Budget a changé entre-temps : recharge la page et recommence")
    key = target["key"] or extract_key(target["label"])
    same = [target]
    if payload.get("remember"):
        same += [o for o in operations if o is not target and o["kind"] == "a_categoriser" and (o["key"] or extract_key(o["label"])) == key]
        add_rule(sheet_id, Rule("exacte", key, category, sub))
    kind = budget_kind(category)
    shown_category, shown_sub = (sub or "Autre", "") if kind == "revenu" else (category, sub)
    for o in same:
        ws.update(range_name=f"D{o['row']}:F{o['row']}", values=[[shown_category, shown_sub, kind]], value_input_option="RAW")
    return {"updated": len(same), "rule": key if payload.get("remember") else None}


def _number(value) -> float:
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        raise OperationError("Montant invalide")
