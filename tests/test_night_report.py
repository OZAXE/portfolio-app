"""Rapport du calcul de nuit (screener/night_report.py) et échec du relevé (screener/snapshot.py)."""

import pytest

import night_report
import snapshot


def test_lecture_des_resultats_du_workflow():
    # Format de la variable OUTCOMES (repliée par YAML : espaces après les points-virgules)
    text = "Relevé du patrimoine=failure; Screener=success; Contenu des ETF=skipped; "
    assert night_report.parse_outcomes(text) == [
        ("Relevé du patrimoine", "failure"), ("Screener", "success"), ("Contenu des ETF", "skipped")]
    assert night_report.parse_outcomes("") == []


def test_rien_a_signaler_quand_tout_reussit():
    assert night_report.report_message([("Screener", "success"), ("Traduction", "success")], []) is None


def test_message_liste_les_etapes_en_echec_et_celles_pas_lancees():
    # Screener planté (sans continue-on-error) : les étapes suivantes sont « skipped »
    outcomes = [("Relevé du patrimoine", "success"), ("Screener", "failure"), ("Traduction", "skipped"),
                ("Historique financier", "cancelled")]
    title, message = night_report.report_message(outcomes, [])
    assert title == "Calcul de nuit : 2 étapes en échec"
    assert "• Screener" in message and "• Historique financier" in message
    assert "Pas lancées ensuite : Traduction." in message


def test_details_prives_ajoutes_au_message(tmp_path, monkeypatch):
    report = tmp_path / "rapport.txt"
    monkeypatch.setenv("NIGHT_REPORT", str(report))
    night_report.add_detail("Relevé impossible pour Evan : valeur illisible pour EWLD.PA")
    title, message = night_report.report_message([("Relevé du patrimoine", "failure")], night_report.read_details(str(report)))
    assert title == "Calcul de nuit : 1 étape en échec"
    assert "Evan : valeur illisible pour EWLD.PA" in message


def test_sans_fichier_de_rapport_add_detail_ne_fait_rien(monkeypatch):
    monkeypatch.delenv("NIGHT_REPORT", raising=False)
    night_report.add_detail("ignoré")  # script lancé à la main : pas d'erreur


def test_envoi_ntfy_seulement_en_cas_d_echec(monkeypatch):
    sent = []
    monkeypatch.setattr(night_report, "send", lambda *a: sent.append(a))
    monkeypatch.setenv("NTFY_TOPIC", "sujet")
    monkeypatch.setenv("RUN_URL", "https://github.com/run/1")
    monkeypatch.delenv("NIGHT_REPORT", raising=False)
    monkeypatch.setenv("OUTCOMES", "Screener=success")
    night_report.main()
    assert sent == []
    monkeypatch.setenv("OUTCOMES", "Screener=success; Publication des données=failure")
    night_report.main()
    assert sent[0][0] == "sujet" and sent[0][1] == "Calcul de nuit : 1 étape en échec"
    assert sent[0][3] == "https://github.com/run/1"


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_releve_impossible_fait_echouer_l_etape(tmp_path, monkeypatch):
    # Un utilisateur en erreur (cours GOOGLEFINANCE illisible), l'autre enregistré : l'étape échoue après avoir
    # traité tout le monde, et le nom va dans le rapport privé, pas dans le journal public
    report = tmp_path / "rapport.txt"
    monkeypatch.setenv("NIGHT_REPORT", str(report))
    monkeypatch.setenv("APP_ACCESS_TOKEN", "code")
    monkeypatch.setattr(snapshot, "api_get", lambda path, token: {"status": "ok"})
    results = [{"name": "Evan", "admin": False, "error": "valeur illisible pour EWLD.PA"},
               {"name": "Enzo", "admin": True, "recorded": True, "reason": None, "weekly": None}]
    monkeypatch.setattr(snapshot.requests, "post", lambda *a, **k: FakeResponse(results))
    monkeypatch.setattr("sys.argv", ["snapshot.py", "--day", "2026-09-29", "--dry-run"])
    with pytest.raises(SystemExit) as stop:
        snapshot.main()
    assert "1 relevé(s) impossible(s)" in str(stop.value)
    assert report.read_text(encoding="utf-8") == "Relevé impossible pour Evan : valeur illisible pour EWLD.PA\n"


def test_releve_reussi_ne_fait_pas_echouer_l_etape(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_TOKEN", "code")
    monkeypatch.setattr(snapshot, "api_get", lambda path, token: {"status": "ok"})
    results = [{"name": "Enzo", "admin": True, "recorded": False, "reason": "relevé déjà présent", "weekly": None}]
    monkeypatch.setattr(snapshot.requests, "post", lambda *a, **k: FakeResponse(results))
    monkeypatch.setattr("sys.argv", ["snapshot.py", "--day", "2026-09-29", "--dry-run"])
    snapshot.main()
