"""Notifications de l'appli (Web Push) : chiffrement, signature VAPID, abonnements rangés dans le Sheet,
récap de la semaine et annonce du brief."""

import json
from datetime import date

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.testclient import TestClient

from app import main, push, users
from app.notifications import brief_to_announce
from app.operations import OperationError
from app.stats import period_change, weekly_summary
from app.users import User
from notify import brief_message, user_topic
from snapshot import summary_message

AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
P256DH = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def subscription(endpoint=FCM):
    return {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": P256DH, "auth": AUTH}}


def test_chiffrement_identique_au_vecteur_de_la_rfc_8291():
    # Exemple de l'annexe A de la RFC 8291 : mêmes clés et même sel -> exactement le même message chiffré
    server = ec.derive_private_key(int.from_bytes(push.unb64url("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
                                   ec.SECP256R1())
    body = push.encrypt(b"When I grow up, I want to be a watermelon", P256DH, AUTH,
                        salt=push.unb64url("DGv6ra1nlYgDCS1FRnbzlw"), server_key=server)
    assert push.b64url(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PB"
        "ru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_jeton_vapid_signe_pour_le_service_du_telephone():
    private, public = push.generate_vapid_keys()
    key = ec.derive_private_key(int.from_bytes(push.unb64url(private), "big"), ec.SECP256R1())
    header = push.vapid_header("https://web.push.apple.com/QGuQyavXutnMH", key, "https://exemple.fr", now=1_000_000)
    token, k = header.removeprefix("vapid t=").split(", k=")
    assert k == public  # la clé publique annoncée est celle que le téléphone a reçue en s'abonnant
    head, claims, signature = token.split(".")
    assert json.loads(push.unb64url(claims)) == {"aud": "https://web.push.apple.com", "exp": 1_000_000 + 12 * 3600,
                                                "sub": "https://exemple.fr"}
    raw = push.unb64url(signature)  # ES256 : r et s bout à bout (64 octets), pas le format DER
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # lève si faux


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/abc",  # pas https
    "https://exemple.fr/push",  # pas un service de push : Render ferait un POST n'importe où
    "https://googleapis.com.exemple.fr/x",  # se termine mal
])
def test_adresse_d_abonnement_refusee(endpoint):
    with pytest.raises(OperationError):
        push.check_subscription(subscription(endpoint))


def test_abonnement_reduit_a_l_essentiel():
    sub = push.check_subscription({**subscription("https://web.push.apple.com/QGuQ"), "autre": "x"})
    assert sub == {"endpoint": "https://web.push.apple.com/QGuQ", "keys": {"p256dh": P256DH, "auth": AUTH}}
    with pytest.raises(OperationError):  # clé du téléphone tronquée
        push.check_subscription({"endpoint": FCM, "keys": {"p256dh": P256DH[:40], "auth": AUTH}})


class FakeSettings:
    """Onglet Réglages en mémoire."""

    def __init__(self, rows):
        self.rows = [["CLÉ", "VALEUR"]] + rows

    def get_values(self):
        return [list(r) for r in self.rows]

    def delete_rows(self, n):
        del self.rows[n - 1]

    def append_row(self, row, value_input_option=None):
        assert value_input_option == "RAW"
        self.rows.append(row)


@pytest.fixture
def settings_tab(monkeypatch):
    ws = FakeSettings([["ntfy_topic", "portfolio-abcdefghijklmn"]])
    monkeypatch.setattr(push, "_settings_tab", lambda sheet_id, create, write=False: ws)
    return ws


def test_un_seul_abonnement_par_telephone(settings_tab):
    assert push.add_subscription("sheet", subscription()) == 1
    assert push.add_subscription("sheet", subscription()) == 1  # réactivé : la ligne est remplacée, pas doublée
    assert push.add_subscription("sheet", subscription("https://web.push.apple.com/iphone")) == 2
    assert [s["endpoint"] for s in push.list_subscriptions("sheet")] == [FCM, "https://web.push.apple.com/iphone"]
    assert settings_tab.rows[1] == ["ntfy_topic", "portfolio-abcdefghijklmn"]  # le reste de l'onglet est intact


def test_les_plus_vieux_appareils_sont_oublies(settings_tab, monkeypatch):
    monkeypatch.setattr(push, "MAX_DEVICES", 2)
    for name in ("a", "b", "c"):
        push.add_subscription("sheet", subscription(f"{FCM}{name}"))
    assert [s["endpoint"][-1] for s in push.list_subscriptions("sheet")] == ["b", "c"]


def test_abonnement_expire_retire_du_sheet(settings_tab, monkeypatch):
    push.add_subscription("sheet", subscription())
    push.add_subscription("sheet", subscription("https://web.push.apple.com/iphone"))
    # Android répond 410 (appli désinstallée), l'iPhone 201 (reçu)
    monkeypatch.setattr(push, "send_to_subscription", lambda sub, *a: 410 if sub["endpoint"] == FCM else 201)
    assert push.send_push("sheet", "Titre", "Texte") == {"sent": 1, "removed": 1, "failed": 0}
    assert [s["endpoint"] for s in push.list_subscriptions("sheet")] == ["https://web.push.apple.com/iphone"]


def test_envoi_impossible_sans_cles_vapid(settings_tab, monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    push.add_subscription("sheet", subscription())
    with pytest.raises(OperationError):
        push.send_push("sheet", "Titre", "Texte")


def test_envoi_reserve_au_job_de_nuit(monkeypatch):
    monkeypatch.setattr(users, "USERS", [User("Enzo", "code-enzo", "sheet-enzo", admin=True), User("Paul", "code-paul", "sheet-paul")])
    sent = []
    monkeypatch.setattr(push, "send_push", lambda sheet_id, title, body, url, tag: sent.append((sheet_id, title, url)) or {"sent": 1})
    client = TestClient(main.app)
    payload = {"user": "Paul", "title": "Ta semaine : +12 €", "message": "…", "url": "https://pirate.example/"}
    assert client.post("/notifications/send", json=payload, headers={"X-Access-Token": "code-paul"}).status_code == 403
    assert client.post("/notifications/send", json=payload, headers={"X-Access-Token": "code-enzo"}).json() == {"sent": 1}
    assert sent == [("sheet-paul", "Ta semaine : +12 €", main.APP_URL)]  # lien hors de l'appli remplacé par l'appli
    assert client.post("/notifications/send", json={**payload, "user": "Inconnu"},
                       headers={"X-Access-Token": "code-enzo"}).status_code == 404


# Lignes d'index_series : [date, indice, valeur, flux cumulés (achats - ventes - dividendes)]
ROWS = [
    ["2025-12-31", 1.00, 10000.0, 10000.0],
    ["2026-06-30", 1.05, 12500.0, 12000.0],  # 2 000 € achetés entre-temps
    ["2026-10-23", 1.10, 13100.0, 12000.0],  # vendredi d'avant
    ["2026-10-30", 1.12, 13338.0, 12000.0],  # vendredi du récap
]


def test_recap_de_la_semaine_et_de_l_annee():
    summary = weekly_summary(ROWS, date(2026, 10, 30))
    assert summary["value"] == 13338.0
    # Semaine : 13 338 - 13 100 = +238 €, sans achat ; indice 1,12 / 1,10 - 1 = +1,82 %
    assert summary["week"]["gain"] == 238.0 and round(summary["week"]["pct"], 4) == 0.0182
    # Année : 13 338 - 10 000 - 2 000 achetés = +1 338 € (l'achat n'est pas un gain) ; indice +12 %
    assert summary["year"] == {"gain": 1338.0, "pct": pytest.approx(0.12), "since": None}


def test_annee_commencee_en_cours_de_route():
    change = period_change(ROWS[1:], date(2025, 12, 31))  # premier relevé le 30/06 : « depuis le 30 juin »
    assert change["since"] == "2026-06-30" and change["gain"] == 838.0


def test_texte_de_la_notification_du_vendredi():
    title, text, tag = summary_message(weekly_summary(ROWS, date(2026, 10, 30)))
    assert title == "Ta semaine : +238 € (+1,8 %)"
    assert text == "Depuis le 1er janvier : +1 338 € (+12,0 %).\nTon portefeuille vaut 13 338 €."
    assert tag == "chart_with_upwards_trend"
    assert summary_message({"value": 10, "week": None, "year": None}) is None  # pas de semaine complète : ancien message


BRIEFS = [{"id": "b2", "date": "2026-10-31"}, {"id": "b1", "date": "2026-10-24"}]


def test_brief_annonce_une_seule_fois():
    assert brief_to_announce(BRIEFS, None, {}, date(2026, 11, 1)) == {"id": "b2", "date": "2026-10-31"}
    assert brief_to_announce(BRIEFS, "b2", {}, date(2026, 11, 1)) is None  # déjà annoncé la nuit d'avant
    assert brief_to_announce(BRIEFS, None, {"b2": "2026-10-31"}, date(2026, 11, 1)) is None  # déjà coché « Lu »
    assert brief_to_announce(BRIEFS, None, {}, date(2026, 11, 8)) is None  # 8 jours : plus « nouveau »
    assert brief_message(BRIEFS[0]) == ("Nouveau brief : semaine du 26 octobre", "Le point marchés de la semaine est prêt à lire.")


def test_sujet_ntfy_du_proprietaire_seulement_sans_telephone_abonne():
    enzo = {"name": "Enzo", "admin": True, "topic": None, "push": 0}
    assert user_topic(enzo, "secret-ntfy") == "secret-ntfy"
    assert user_topic({**enzo, "push": 1}, "secret-ntfy") is None  # sinon tout arriverait en double
    assert user_topic({"admin": False, "topic": None, "push": 0}, "secret-ntfy") is None


def test_passage_du_soir_annonce_seulement_le_brief(monkeypatch):
    import notify

    sent, marked = [], []
    monkeypatch.setattr(notify, "deliver", lambda user, token, topic, title, text, *a: sent.append((user["name"], title)) or ["appli"])
    monkeypatch.setattr(notify, "api_post", lambda path, token, payload: marked.append((path, payload)))
    users_ = [
        {"name": "Enzo", "admin": True, "push": 1, "brief": BRIEFS[0]},
        {"name": "Paul", "push": 0, "topic": None, "brief": BRIEFS[0]},  # notifications pas activées : rien, pas marqué
        {"name": "Lea", "push": 1, "brief": None},  # déjà annoncé ou lu
        {"name": "Tom", "error": "Sheet illisible"},
    ]
    notify.announce_briefs(users_, "code", None, dry_run=False)
    assert sent == [("Enzo", "Nouveau brief : semaine du 26 octobre")]
    assert marked == [("/notifications/brief-sent", {"user": "Enzo", "id": "b2"})]
