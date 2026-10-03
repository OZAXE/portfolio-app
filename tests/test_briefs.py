"""Briefs hebdo : lecture du dossier Drive (liste, dates, doublons, isolation entre dossiers)."""

import pytest

from app import briefs


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self.payload, self.content = payload, content

    def json(self):
        return self.payload


@pytest.fixture
def drive(monkeypatch):
    """Faux Drive : dossier -> liste de fichiers ; compte les appels pour vérifier le cache."""
    folders, contents, calls = {}, {}, []

    def fake_get(url, **params):
        calls.append((url, params))
        if params.get("alt") == "media":
            return FakeResponse(content=contents[url.rsplit("/", 1)[1]])
        folder = params["q"].split("'")[1]
        return FakeResponse({"files": folders.get(folder, [])})

    monkeypatch.setattr(briefs, "_get", fake_get)
    monkeypatch.setattr(briefs, "_list_cache", {})
    monkeypatch.setattr(briefs, "_content_cache", {})
    return folders, contents, calls


def file(id_, name, modified="2026-09-27T08:00:00Z", mime="text/html"):
    return {"id": id_, "name": name, "mimeType": mime, "modifiedTime": modified}


def test_briefs_tries_du_plus_recent_au_plus_ancien(drive):
    folders, _, _ = drive
    folders["dossier"] = [file("a", "2026-09-12.html"), file("c", "2026-10-03.html"), file("b", "2026-09-26.html")]
    assert [b["date"] for b in briefs.list_briefs("dossier")] == ["2026-10-03", "2026-09-26", "2026-09-12"]


def test_date_lue_dans_le_nom_meme_entouree_de_texte(drive):
    folders, _, _ = drive
    folders["dossier"] = [file("a", "Brief 2026-09-26 v2.htm")]
    assert briefs.list_briefs("dossier")[0]["date"] == "2026-09-26"


def test_fichiers_qui_ne_sont_pas_des_briefs_ignores(drive):
    folders, _, _ = drive
    folders["dossier"] = [
        file("ref", "DA_de_reference.html"),  # référence de mise en page, sans date
        file("pdf", "2026-09-26.pdf", mime="application/pdf"),
        file("md", "2026-09-26.md"),
        file("mois", "2026-13-05.html"),  # mois 13
        file("jour", "2026-02-30.html"),  # 30 février
        file("ok", "2026-09-19.html"),
    ]
    assert [b["id"] for b in briefs.list_briefs("dossier")] == ["ok"]


def test_doublon_de_date_un_seul_brief_le_dernier_modifie(drive):
    # Cas réel du 26/09/2026 : deux 2026-09-26.html dans « Briefs », affichés deux fois
    folders, _, _ = drive
    folders["dossier"] = [
        file("copie", "2026-09-26.html", modified="2026-09-27T10:00:00Z"),
        file("original", "2026-09-26.html", modified="2026-09-26T09:00:00Z"),
        file("autre", "2026-09-19.html"),
    ]
    listed = briefs.list_briefs("dossier")
    assert [b["id"] for b in listed] == ["copie", "autre"]


def test_doublon_ordre_du_drive_sans_importance(drive):
    folders, _, _ = drive
    folders["dossier"] = [
        file("ancien", "2026-09-26.html", modified="2026-09-26T09:00:00Z"),
        file("recent", "2026-09-26.htm", modified="2026-09-28T09:00:00Z"),
    ]
    assert [b["id"] for b in briefs.list_briefs("dossier")] == ["recent"]


def test_dossier_vide(drive):
    assert briefs.list_briefs("vide") == []


def test_liste_gardee_en_cache(drive):
    folders, _, calls = drive
    folders["dossier"] = [file("a", "2026-09-26.html")]
    briefs.list_briefs("dossier")
    folders["dossier"].append(file("b", "2026-10-03.html"))
    assert len(briefs.list_briefs("dossier")) == 1  # 10 minutes de cache : le nouveau fichier attend
    assert len(calls) == 1


def test_liste_relue_apres_expiration_du_cache(drive, monkeypatch):
    folders, _, _ = drive
    folders["dossier"] = [file("a", "2026-09-26.html")]
    briefs.list_briefs("dossier")
    folders["dossier"].append(file("b", "2026-10-03.html"))
    instant = briefs.time.monotonic()
    monkeypatch.setattr(briefs.time, "monotonic", lambda: instant + briefs.LIST_CACHE_SECONDS + 1)
    assert len(briefs.list_briefs("dossier")) == 2


def test_contenu_servi_et_garde_tant_que_le_fichier_ne_change_pas(drive):
    folders, contents, calls = drive
    folders["dossier"] = [file("a", "2026-09-26.html")]
    contents["a"] = "<h1>Brief</h1>".encode()
    assert briefs.get_brief_html("dossier", "a") == "<h1>Brief</h1>"
    briefs.get_brief_html("dossier", "a")
    assert sum(params.get("alt") == "media" for _, params in calls) == 1


def test_brief_d_un_autre_dossier_refuse(drive):
    # Un ami (dossier public) ne peut pas lire un brief perso en devinant son identifiant
    folders, contents, _ = drive
    folders["perso"] = [file("secret", "2026-09-26.html")]
    folders["public"] = [file("pub", "2026-09-26.html")]
    contents["secret"] = b"positions"
    with pytest.raises(briefs.BriefNotFoundError):
        briefs.get_brief_html("public", "secret")


def test_doublon_ecarte_non_servi(drive):
    # Seul le brief affiché est servi : l'identifiant de la copie écartée ne mène à rien
    folders, contents, _ = drive
    folders["dossier"] = [
        file("garde", "2026-09-26.html", modified="2026-09-27T10:00:00Z"),
        file("ecarte", "2026-09-26.html", modified="2026-09-26T09:00:00Z"),
    ]
    contents["ecarte"] = b"vieux"
    with pytest.raises(briefs.BriefNotFoundError):
        briefs.get_brief_html("dossier", "ecarte")


def test_fichier_inexistant(drive):
    folders, _, _ = drive
    folders["dossier"] = [file("a", "2026-09-26.html")]
    with pytest.raises(briefs.BriefNotFoundError):
        briefs.get_brief_html("dossier", "inconnu")
