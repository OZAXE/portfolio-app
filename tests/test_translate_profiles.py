import json

import pytest

import run
from translate_profiles import chunks, fingerprint, keep_translation, needs_translation, parse_response, translate

SUMMARY = ("L'Air Liquide S.A. provides gases, technologies, and services for the industrial and health sectors. "
           "It operates in Gas & Services, and Engineering & Construction segments.")


def test_decoupage_entre_deux_phrases():
    text = "Première phrase. " * 200  # 3 400 caractères
    parts = chunks(text, 1500)
    assert all(len(p) <= 1500 for p in parts) and len(parts) == 3
    assert all(p.endswith(".") for p in parts)  # jamais coupé au milieu d'une phrase
    assert " ".join(parts) == text.strip()
    # Phrase plus longue que la limite : coupée entre deux mots
    assert all(len(p) <= 20 for p in chunks("mot " * 30, 20))


def test_lecture_de_la_reponse_google():
    # Format de translate_a/single : une entrée par phrase traduite, puis la langue détectée
    data = [[["L'Air Liquide S.A. fournit des gaz. ", "L'Air Liquide S.A. provides gases. ", None, None, 10],
             ["Elle opère dans deux segments.", "It operates in two segments.", None, None, 10]], None, "en"]
    assert parse_response(data) == "L'Air Liquide S.A. fournit des gaz. Elle opère dans deux segments."
    for bad in ({}, [], [None], [[]]):
        with pytest.raises(ValueError):
            parse_response(bad)


def test_traduction_morceau_par_morceau(monkeypatch):
    monkeypatch.setattr("translate_profiles.DELAY_SECONDS", 0)

    class Session:
        calls = []

        def get(self, url, params, timeout):
            self.calls.append(params)
            return type("R", (), {"raise_for_status": lambda s: None,
                                  "json": lambda s: [[[params["q"].upper(), params["q"]]], None, "en"]})()

    session = Session()
    assert translate("Un. Deux.", session) == "UN. DEUX."
    assert session.calls[0]["sl"] == "en" and session.calls[0]["tl"] == "fr"


def test_retraduction_seulement_si_le_texte_change():
    translated = {"summary": SUMMARY, "summary_fr": "Air Liquide fournit…", "summary_fr_of": fingerprint(SUMMARY)}
    assert not needs_translation(translated)
    assert needs_translation({"summary": SUMMARY})
    assert needs_translation({**translated, "summary": SUMMARY + " New plant."})  # texte modifié par Yahoo
    assert not needs_translation({"summary": None})


def test_reanalyse_garde_la_traduction(tmp_path):
    # Fichier déjà traduit ; la réanalyse de la nuit réécrit le profil avec le même texte anglais
    (tmp_path / "profiles").mkdir()
    old = {"summary": SUMMARY, "summary_fr": "Air Liquide fournit…", "summary_fr_of": fingerprint(SUMMARY)}
    (tmp_path / "profiles" / "AI.PA.json").write_text(json.dumps(old), encoding="utf-8")
    run.save_profile(tmp_path, "AI.PA", {"summary": SUMMARY, "website": "https://www.airliquide.com", "updated": "2026-10-01"})
    saved = json.loads((tmp_path / "profiles" / "AI.PA.json").read_text(encoding="utf-8"))
    assert saved["summary_fr"] == "Air Liquide fournit…" and saved["updated"] == "2026-10-01"
    # Texte anglais différent : l'ancienne traduction n'est pas reprise (elle serait fausse)
    assert "summary_fr" not in keep_translation({"summary": "Other text."}, old)
