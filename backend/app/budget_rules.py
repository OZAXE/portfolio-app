"""
Catégorisation des relevés du compte courant (novembre 2026, demande d'Enzo : ne plus passer par son PC).

Portage de update_suivi.py (son script Windows) : lecture d'un export Excel du Crédit Agricole, clé tirée du
libellé, règles exactes apprises puis motifs (expressions régulières), dédoublonnage. Fonctions pures : la lecture
de Drive et l'écriture dans le Sheet sont dans budget_import.py.

Les règles ne sont jamais dans le dépôt (public) : elles citent ses commerçants et les noms de ses proches. Elles
vivent dans l'onglet « Règles budget » de son Sheet, une ligne par règle :
- exacte : la clé du libellé (extract_key) doit être identique au motif (« boulangerie du port ») ;
- motif : expression régulière cherchée dans le libellé brut, sans tenir compte des majuscules (« SUPERMARCHE »).
Les règles exactes passent d'abord, puis les motifs dans l'ordre de l'onglet (le premier qui correspond gagne :
« AIRE DU LAC » est avant la règle des péages, sinon un café sur l'aire serait compté comme un péage).

Différence voulue avec update_suivi.py : la clé ne garde plus la date de fin de libellé. Avant, la règle apprise
« boulangerie du port 23/12 » ne reconnaissait que le paiement du 23 décembre ; « boulangerie du port » reconnaît
tous les mois.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

# Préfixes de type d'opération du CA, du plus long au plus court (« Prélèvement carte » avant « Prélèvement »)
TYPES = sorted(["Virement en votre faveur", "Virement émis", "Annul. opé. débitrices", "Prélèvement carte",
                "Prélèvement", "Paiement par carte", "Cotisation", "Remboursement emprunt", "Intérêts créditeurs",
                "Avoir", "Remise de chèque", "Retrait", "Paiement de coupons"], key=len, reverse=True)
DATE_RE = re.compile(r"\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?")
TRAILING_DATE = re.compile(r"\s+\d{1,2}/\d{1,2}$")  # « boulangerie du port 23/12 » -> « boulangerie du port »
DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y")

# Onglets d'outputs.xlsx -> catégorie affichée dans l'appli (envoyer_budget.py faisait la même conversion)
DISPLAY = {"Restaurant-Bar": "Restaurant/Bar", "Sante": "Santé"}
UNCATEGORIZED = "À catégoriser"
RULES_TAB = "Règles budget"
RULES_HEADERS = ["Type", "Motif", "Catégorie", "Sous-catégorie", "Ajoutée le"]
RULE_KINDS = ("exacte", "motif")


@dataclass(frozen=True)
class Rule:
    kind: str  # exacte ou motif
    pattern: str
    category: str  # nom affiché : « Restaurant/Bar », « Revenus », « Virements internes »...
    subcategory: str


@dataclass(frozen=True)
class Line:
    """Une opération lue dans l'export du CA."""
    day: date
    label: str  # libellé brut, retours à la ligne compris (la clé ne lit que la première ligne)
    amount: float
    credit: bool


# --- Clé du libellé (reprise de update_suivi.py) ---

def strip_prefix(label: str) -> tuple[str | None, str]:
    label = label.strip()
    for t in TYPES:
        m = re.match(r"^\[" + re.escape(t) + r"\]\s*", label) or re.match(r"^" + re.escape(t) + r"\s*-\s*", label)
        if m:
            return t, label[m.end():]
    return None, label


def cut_junk(s: str) -> str:
    low = s.lower()
    for marker in ("numero de client", "numero de compte", "n° client", "réf "):
        idx = low.find(marker)
        if idx != -1:
            s, low = s[:idx], low[:idx]
    return s.strip()


def looks_bad(seg: str) -> bool:
    """Morceau de libellé sans nom exploitable : vide, une date, surtout des chiffres, une référence."""
    s = cut_junk(seg.strip())
    if len(s) < 2 or len(DATE_RE.sub("", s).strip()) < 2:
        return True
    if sum(c.isdigit() for c in s) >= max(3, len(s) // 2):
        return True
    return s.lower().startswith(("numero", "n°", "réf", "ref", "client", "compte"))


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_key(label: str) -> str:
    """Clé stable d'un libellé : le bénéficiaire d'un virement, sinon le dernier morceau qui ressemble à un nom.
    « Paiement par carte - X9900 BOULANGERIE DU PORT 23/12 - Le Fournil » -> « le fournil »."""
    ttype, rest = strip_prefix(label)
    rest = rest.split("\n")[0].strip()
    if rest.upper().startswith("X9900 "):
        rest = rest[6:].strip()
    if ttype in ("Virement émis", "Virement en votre faveur", "Annul. opé. débitrices"):
        for pattern, prefix in ((r"\bvers\s+([A-Za-zÀ-ÿ .'\-]+)", "virement vers "),
                                (r"\bWEB\s+([A-Za-zÀ-ÿ .'\-]+)", "web "),
                                (r"\bde\s+([A-Za-zÀ-ÿ .'\-]+)", "virement de ")):
            m = re.search(pattern, rest, 0 if prefix == "virement vers " else re.IGNORECASE)
            if m:
                return prefix + _squash(m.group(1))
    for seg in reversed([cut_junk(s.strip()) for s in rest.split(" - ")]):
        if not looks_bad(seg):
            return clean_key(seg)
    return clean_key(re.sub(r"\s+", " ", DATE_RE.sub("", rest)).strip()[:30])


def clean_key(key: str) -> str:
    return TRAILING_DATE.sub("", _squash(key))


# --- Catégorie ---

def categorize(line: Line, exact: dict[str, Rule], patterns: list[tuple[re.Pattern, Rule]]) -> tuple[str, str] | None:
    """(catégorie, sous-catégorie), ou None si aucune règle ne reconnaît l'opération."""
    rule = exact.get(extract_key(line.label))
    if rule is None:
        rule = next((r for regex, r in patterns if regex.search(line.label)), None)
    if rule is None:
        return None
    # Un virement perso reçu (un ami rembourse sa part) est un remboursement, pas une dépense négative
    if rule.category == "Autre" and rule.subcategory == "Virement perso" and line.credit:
        return "Revenus", "Remboursement"
    return rule.category, rule.subcategory


def compile_rules(rules: list[Rule]) -> tuple[dict[str, Rule], list[tuple[re.Pattern, Rule]]]:
    exact = {}
    patterns = []
    for rule in rules:
        if rule.kind == "exacte":
            exact.setdefault(clean_key(rule.pattern), rule)
        else:
            try:
                patterns.append((re.compile(rule.pattern, re.IGNORECASE), rule))
            except re.error:
                continue  # motif abîmé à la main dans le Sheet : ignoré plutôt que tout bloquer
    return exact, patterns


def budget_kind(category: str) -> str:
    """Type d'une ligne de l'onglet Budget (budget.KINDS) d'après sa catégorie."""
    return {"Revenus": "revenu", "Investissement": "investissement", "Virements internes": "interne",
            UNCATEGORIZED: "a_categoriser"}.get(category, "depense")


def budget_operation(line: Line, found: tuple[str, str] | None) -> dict:
    """Opération au format de /budget/import (envoyer_budget.py) : un revenu a sa sous-catégorie comme catégorie
    (Salaire, Remboursement...), comme l'onglet Revenus d'outputs.xlsx."""
    category, sub = found or (UNCATEGORIZED, "")
    kind = budget_kind(category)
    if kind == "revenu":
        category, sub = sub or "Autre", ""
    return {"date": line.day.isoformat(), "label": line.label, "amount": round(line.amount, 2),
            "category": category, "subcategory": sub, "kind": kind}


# --- Lecture de l'export Excel du CA ---

def parse_date(value) -> date | None:
    """Vraie date Excel jusqu'en août 2026, texte « 08/09/2026 » depuis."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value) -> float | None:
    """Nombre, ou texte dans l'un des formats vus : « 1 024,50 € » (français) ou « 1,638.26 » (export du CA du
    06/11/2026 : virgule des milliers, point décimal). Le dernier séparateur est le décimal."""
    if isinstance(value, str):
        text = value.replace("\u202f", "").replace("\xa0", "").replace("€", "").replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
        value = text.replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_header(row) -> bool:
    """« Date / Libellé / ... » (anciens exports) ou « Date d'opération / Libellé / ... » (novembre 2026)."""
    return bool(row) and str(row[0] or "").strip().lower().startswith("date") and any(str(v or "").strip().startswith("Libell") for v in row)


def read_export(rows) -> list[Line]:
    """Opérations d'un export CA : lignes sous l'en-tête « Date / Libellé / Débit euros / Crédit euros ». L'export
    contient aussi les livrets à la suite (Livret A...) : leurs lignes sont lues comme avant (update_suivi.py), un
    virement entre ses comptes y apparaît des deux côtés et reste dans « Virements internes », hors du solde."""
    rows = list(rows)
    start = next((i for i, row in enumerate(rows) if is_header(row)), None)
    if start is None:
        raise ValueError("en-tête « Date / Libellé » introuvable : est-ce bien un export du Crédit Agricole ?")
    lines = []
    for row in rows[start + 1:]:
        day, label, debit, credit = (tuple(row) + (None,) * 4)[:4]
        if day is None or label is None or str(label).strip() in ("", "Libellé"):
            continue
        amount = parse_amount(debit if debit is not None else credit)
        day = parse_date(day)
        if amount is None or day is None:
            continue
        lines.append(Line(day, str(label), amount, credit is not None))
    return lines


def read_export_file(content: bytes) -> list[Line]:
    import io

    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        return read_export(book.worksheets[0].iter_rows(values_only=True))
    finally:
        book.close()


# --- Dédoublonnage ---

def op_key(day: str, label: str, amount: float) -> tuple[str, str, float]:
    """Même opération = même date, même libellé (espaces et retours à la ligne ramenés à un espace, comme dans
    l'onglet Budget) et même montant au centime."""
    return day, " ".join(str(label).split()), round(float(amount), 2)


def new_lines(lines: list[Line], known: Counter) -> list[Line]:
    """Opérations pas encore rangées. Compte les occurrences au lieu d'un simple « déjà vu » : deux virements de
    100 € vers Boursorama le même jour (08/08/2026) sont deux opérations réelles, mais deux exports qui se
    chevauchent ne doivent pas les ajouter deux fois. `known` est mis à jour (appeler fichier par fichier)."""
    in_file = Counter(op_key(l.day.isoformat(), l.label, l.amount) for l in lines)
    fresh, taken = [], Counter()
    for line in lines:
        key = op_key(line.day.isoformat(), line.label, line.amount)
        if taken[key] < in_file[key] - known[key]:
            fresh.append(line)
            taken[key] += 1
    for key, n in taken.items():
        known[key] += n
    return fresh
