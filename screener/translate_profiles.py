"""
Traduction en français des présentations d'entreprise (profiles/<ticker>.json), une fois pour toutes.

Yahoo ne fournit la présentation (longBusinessSummary) qu'en anglais. Chaque nuit, ce script traduit les
présentations qui n'ont pas encore de version française, ou dont le texte anglais a changé, et range la
traduction dans le même fichier (summary_fr, avec summary_fr_of : l'empreinte du texte traduit). L'appli
l'affiche directement, avec l'original en anglais à un toucher.

Service : l'API publique de Google Traduction (celle du lien « Traduire » de l'appli), gratuite et sans clé.
Textes découpés par phrases en morceaux de 1 500 caractères au plus (la requête passe dans l'adresse).
Après 5 échecs de suite (service qui bloque), le script s'arrête : la suite sera faite la nuit suivante.

    python screener/translate_profiles.py --data-dir data --max 800 --time-budget-min 20
"""

import argparse
import hashlib
import json
import logging
import re
import time
from pathlib import Path

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
CHUNK_CHARS = 1500
DELAY_SECONDS = 1.0
MAX_CONSECUTIVE_FAILURES = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("translate")


def fingerprint(text: str) -> str:
    """Empreinte du texte anglais : une présentation modifiée par Yahoo est retraduite."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Morceaux d'au plus `size` caractères, coupés entre deux phrases (une phrase trop longue est coupée
    entre deux mots)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    parts, current = [], ""
    for sentence in sentences:
        while len(sentence) > size:
            cut = sentence.rfind(" ", 0, size)
            cut = cut if cut > 0 else size
            parts.append(sentence[:cut])
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > size:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def parse_response(data) -> str:
    """Réponse de Google Traduction : [[["texte traduit", "original", ...], ...], ..., "en"]."""
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise ValueError("réponse de traduction inattendue")
    text = "".join(part[0] for part in data[0] if isinstance(part, list) and part and isinstance(part[0], str))
    if not text.strip():
        raise ValueError("traduction vide")
    return text.strip()


def translate(text: str, session) -> str:
    out = []
    for part in chunks(text):
        response = session.get(TRANSLATE_URL, params={"client": "gtx", "sl": "en", "tl": "fr", "dt": "t", "q": part},
                               timeout=20)
        response.raise_for_status()
        out.append(parse_response(response.json()))
        time.sleep(DELAY_SECONDS / 2)
    return " ".join(out)


def needs_translation(profile: dict) -> bool:
    summary = profile.get("summary")
    return bool(summary) and (not profile.get("summary_fr") or profile.get("summary_fr_of") != fingerprint(summary))


def keep_translation(new: dict, old: dict | None) -> dict:
    """Profil réécrit par une réanalyse : la traduction existante est gardée si le texte anglais est le même."""
    if old and old.get("summary_fr") and old.get("summary_fr_of") == fingerprint(new.get("summary") or ""):
        return {**new, "summary_fr": old["summary_fr"], "summary_fr_of": old["summary_fr_of"]}
    return new


def main():
    import requests

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--max", type=int, default=800)
    parser.add_argument("--time-budget-min", type=float, default=20)
    args = parser.parse_args()
    started = time.monotonic()

    paths = sorted((Path(args.data_dir) / "profiles").glob("*.json"))
    todo = []
    for path in paths:
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if needs_translation(profile):
            todo.append((path, profile))
    log.info("présentations : %d, à traduire : %d, lot de %d", len(paths), len(todo), args.max)

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (portfolio-app)"
    done = failures = 0
    for path, profile in todo[: args.max]:
        if time.monotonic() - started > args.time_budget_min * 60:
            log.info("budget de temps atteint")
            break
        try:
            profile["summary_fr"] = translate(profile["summary"], session)
            profile["summary_fr_of"] = fingerprint(profile["summary"])
            path.write_text(json.dumps(profile, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            done += 1
            failures = 0
        except Exception as e:
            failures += 1
            log.warning("%s : traduction en erreur (%s)", path.stem, e)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                log.warning("service de traduction indisponible, arrêt ; reprise la nuit prochaine")
                break
        time.sleep(DELAY_SECONDS)
    log.info("traduites : %d", done)


if __name__ == "__main__":
    main()
