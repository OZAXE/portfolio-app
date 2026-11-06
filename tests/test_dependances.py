"""Chaque bibliothèque importée par le serveur doit être dans backend/requirements.txt, la seule liste installée sur
Render. Le 06/11/2026, openpyxl n'était que dans requirements-dev.txt : les tests passaient en local et sur la CI,
mais en ligne la lecture des relevés du budget échouait (« No module named 'openpyxl' »)."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Nom à l'import -> nom du paquet dans requirements.txt quand ils diffèrent
PACKAGES = {"google": "google-auth", "dotenv": "python-dotenv", "yaml": "pyyaml"}
# Installés avec un paquet de la liste (requests vient avec yfinance, gspread et google-auth)
TRANSITIVE = {"requests"}


def imported_modules() -> set[str]:
    names = set()
    for path in (ROOT / "backend" / "app").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return {n for n in names if n not in sys.stdlib_module_names and n != "app" and n not in TRANSITIVE}


def test_le_serveur_n_importe_que_des_paquets_installes_sur_render():
    lines = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    declared = {l.split("#")[0].split("==")[0].split(">=")[0].split("[")[0].strip().lower() for l in lines if l.strip() and not l.startswith("#")}
    missing = sorted(m for m in imported_modules() if PACKAGES.get(m, m).lower() not in declared)
    assert missing == [], f"à ajouter à backend/requirements.txt : {missing}"
