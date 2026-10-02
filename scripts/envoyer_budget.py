"""
Envoie les opérations de outputs.xlsx (suivi bancaire d'Enzo) à l'appli, qui les affiche dans Plus > Budget.

À lancer sur le PC après update_suivi.py, par la tâche mensuelle « maj-suivi-bancaire » :
    python envoyer_budget.py "C:\\Users\\enzoc\\Documents\\Suivi des opérations bancaires\\outputs.xlsx"

Le fichier n'est que lu, jamais modifié. Toutes les opérations sont envoyées à chaque fois : l'appli remplace son
onglet Budget, donc relancer après un échec ne crée pas de doublon.

Code d'accès (administrateur) : variable d'environnement PORTFOLIO_CODE, sinon fichier code_acces.txt à côté
de outputs.xlsx. Ne jamais l'écrire dans ce script : le dépôt est public.

Lecture des onglets d'outputs.xlsx (un onglet par catégorie, titre en ligne 1, en-têtes Date / Libellé /
Montant (EUR) / Sous-catégorie en ligne 2) :
- Résumé : ignoré, l'appli refait les totaux mois par mois ;
- Revenus : revenu, la colonne D est la catégorie (Salaire, Dividendes...) ;
- Investissement, Virements internes : à part, hors solde ;
- À categoriser : en attente de la validation du mois suivant ;
- tous les autres : dépense, catégorie = nom de l'onglet (« Restaurant-Bar » -> « Restaurant/Bar »).
Bibliothèque standard + openpyxl (déjà utilisé par update_suivi.py).
"""

import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

API_URL = os.environ.get("PORTFOLIO_API", "https://portfolio-app-blvx.onrender.com")
# Noms d'onglets qui ne peuvent pas porter « / » ou un accent dans le fichier
CATEGORY_NAMES = {"restaurant-bar": "Restaurant/Bar", "sante": "Santé"}
SKIPPED = {"resume"}


def _key(name: str) -> str:
    """« À categoriser » / « A catégoriser » / « Résumé » -> clé sans accent ni majuscule."""
    plain = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().split())


def sheet_kind(title: str) -> tuple[str, str] | None:
    """(type, catégorie) d'un onglet, None s'il ne contient pas d'opérations."""
    key = _key(title)
    if key in SKIPPED:
        return None
    if key == "revenus":
        return "revenu", ""
    if key == "investissement":
        return "investissement", "Investissement"
    if key == "virements internes":
        return "interne", "Virements internes"
    if key.startswith("a categoriser"):
        return "a_categoriser", "À catégoriser"
    return "depense", CATEGORY_NAMES.get(key, str(title).strip())


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _amount(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("€", "").replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def sheet_operations(title: str, rows) -> list[dict]:
    """Opérations d'un onglet : lignes sous l'en-tête « Date », colonnes A à D (les colonnes F à H du fichier sont
    un récapitulatif par sous-catégorie, ignoré)."""
    kind = sheet_kind(title)
    if kind is None:
        return []
    kind, category = kind
    operations, started = [], False
    for row in rows:
        row = (list(row) + [None] * 4)[:4]
        if not started:
            started = _key(row[0] or "") == "date"
            continue
        day, amount, label = _iso(row[0]), _amount(row[2]), str(row[1] or "").strip()
        if not day or amount is None or not label:
            continue  # ligne vide ou ligne de total
        sub = str(row[3] or "").strip()
        operations.append({"date": day, "label": label, "amount": round(amount, 2),
                           "category": (sub or "Autre") if kind == "revenu" else category,
                           "subcategory": "" if kind == "revenu" else sub, "kind": kind})
    return operations


def read_outputs(path: Path) -> list[dict]:
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    operations = []
    for ws in book.worksheets:
        operations += sheet_operations(ws.title, ws.iter_rows(values_only=True))
    book.close()
    return operations


def access_code(path: Path) -> str:
    code = os.environ.get("PORTFOLIO_CODE", "").strip()
    if not code:
        file = path.with_name("code_acces.txt")
        code = file.read_text(encoding="utf-8").strip() if file.exists() else ""
    if not code:
        sys.exit("Code d'accès introuvable : définis PORTFOLIO_CODE ou crée code_acces.txt à côté de outputs.xlsx")
    return code


def send(operations: list[dict], code: str, force: bool = False, tries: int = 4) -> dict:
    """POST /budget/import. Render (plan gratuit) dort après 15 min : le premier appel peut prendre une minute,
    d'où le long délai et les nouvelles tentatives (2, 4, 8 s) sur une erreur réseau ou un 502 / 503."""
    body = json.dumps({"operations": operations, "force": force}).encode()
    request = urllib.request.Request(f"{API_URL}/budget/import", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Access-Token": code})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            try:
                detail = json.load(e).get("detail")
            except ValueError:
                detail = e.reason
            sys.exit(f"Envoi refusé par l'appli ({e.code}) : {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == tries - 1:
                sys.exit(f"Appli injoignable : {e}")
            time.sleep(2 ** (attempt + 1))


def main():
    parser = argparse.ArgumentParser(description="Envoie outputs.xlsx à Plus > Budget de l'appli")
    parser.add_argument("outputs", type=Path, help="chemin de outputs.xlsx")
    parser.add_argument("--force", action="store_true", help="remplace même si le fichier a beaucoup moins d'opérations")
    parser.add_argument("--dry-run", action="store_true", help="lit le fichier et affiche le bilan sans rien envoyer")
    args = parser.parse_args()
    operations = read_outputs(args.outputs)
    if not operations:
        sys.exit("Aucune opération trouvée dans le fichier : rien n'est envoyé")
    by_kind = {}
    for op in operations:
        by_kind[op["kind"]] = by_kind.get(op["kind"], 0) + 1
    print(f"{len(operations)} opérations lues : " + ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items())))
    if args.dry_run:
        return
    result = send(operations, access_code(args.outputs), args.force)
    print(f"Envoyé à l'appli : {result['count']} opérations du {result['first']} au {result['last']} "
          f"({result['months']} mois), {result['to_categorize']} à catégoriser.")


if __name__ == "__main__":
    main()
