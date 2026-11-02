"""
Notifications natives de l'appli installée (Web Push), sans appli tierce comme ntfy.

Chaque téléphone qui active les notifications (Plus > Notifications) donne au navigateur une
« adresse d'abonnement » chez le service de push de son système : Google (Android, Chrome),
Apple (iPhone, appli ajoutée à l'écran d'accueil, iOS 16.4 et plus), Mozilla, Microsoft. Elle est
rangée dans l'onglet « Réglages » du Sheet de l'utilisateur (clé `push`, une ligne par appareil).

Envoyer = POST chiffré vers cette adresse (RFC 8291, aes128gcm), signé avec la clé VAPID de l'appli
(RFC 8292) : le service de push vérifie que c'est bien notre serveur, et ne peut pas lire le message.
Codé ici avec `cryptography` plutôt qu'avec pywebpush, qui ne s'installait pas dans le conteneur de dev
(paquet http-ece sans wheel) et tire aiohttp. Vérifié contre le déchiffrement de http-ece (tests).

Clés VAPID dans l'environnement de Render : VAPID_PRIVATE_KEY (32 octets) et VAPID_PUBLIC_KEY (point
P-256 non compressé, 65 octets), en base64url. Générées une fois (`python -m app.push`) : en changer
invalide tous les abonnements (chacun devra réactiver les notifications).
"""

import base64
import json
import os
import struct
import time
from datetime import date
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .operations import OperationError

PUSH_KEY = "push"  # clé des lignes d'abonnement dans l'onglet Réglages
MAX_DEVICES = 10  # au-delà, les plus anciens abonnements sont oubliés
# Le serveur fait un POST vers l'adresse donnée par le téléphone : seulement les vrais services de push,
# sinon un utilisateur pourrait faire appeler n'importe quelle adresse par Render
PUSH_HOSTS = (".googleapis.com", ".push.apple.com", ".push.services.mozilla.com", ".notify.windows.com")
TTL_SECONDS = 2 * 86400  # téléphone éteint : la notification attend deux jours, puis est abandonnée
RECORD_SIZE = 4096
DEFAULT_SUBJECT = "https://portfolio-front-8t6m.onrender.com"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_vapid_keys() -> tuple[str, str]:
    """(privée, publique) en base64url, à mettre dans VAPID_PRIVATE_KEY et VAPID_PUBLIC_KEY."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64url(key.private_numbers().private_value.to_bytes(32, "big")), b64url(_public_bytes(key))


def vapid_public_key() -> str | None:
    return os.environ.get("VAPID_PUBLIC_KEY") or None


def _vapid_private_key() -> ec.EllipticCurvePrivateKey | None:
    raw = os.environ.get("VAPID_PRIVATE_KEY")
    return ec.derive_private_key(int.from_bytes(unb64url(raw), "big"), ec.SECP256R1()) if raw else None


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Corps chiffré aes128gcm d'un message (un seul enregistrement), pour la clé du téléphone (RFC 8291).
    salt et server_key ne sont donnés que par les tests ; sinon tirés au hasard à chaque message."""
    receiver = unb64url(p256dh)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    server_public = _public_bytes(server_key)
    salt = salt or os.urandom(16)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver))
    ikm = _hkdf(unb64url(auth), shared, b"WebPush: info\x00" + receiver + server_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(payload) + 17 > RECORD_SIZE:  # 1 octet de délimiteur + 16 de tag
        raise ValueError("message trop long pour une notification")
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02 : dernier enregistrement
    header = salt + struct.pack("!IB", RECORD_SIZE, len(server_public)) + server_public
    return header + ciphertext


def vapid_header(endpoint: str, key: ec.EllipticCurvePrivateKey, subject: str, now: float | None = None) -> str:
    """En-tête Authorization (RFC 8292) : jeton JWT ES256 pour le service de push de `endpoint`, 12 h."""
    url = urlparse(endpoint)
    claims = {"aud": f"{url.scheme}://{url.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": subject}
    signing_input = (b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
                     + b64url(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing_input + "." + b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={b64url(_public_bytes(key))}"


def check_subscription(sub) -> dict:
    """Abonnement envoyé par le navigateur (PushSubscription.toJSON()), réduit à ce qui sert."""
    if not isinstance(sub, dict):
        raise OperationError("Abonnement invalide")
    endpoint, keys = str(sub.get("endpoint") or ""), sub.get("keys") or {}
    url = urlparse(endpoint)
    if url.scheme != "https" or not url.hostname or not ("." + url.hostname).endswith(PUSH_HOSTS) or len(endpoint) > 1000:
        raise OperationError("Service de notifications non reconnu par l'appli")
    try:
        p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
        if len(unb64url(p256dh)) != 65 or len(unb64url(auth)) != 16:
            raise ValueError
    except ValueError:
        raise OperationError("Clés de l'abonnement invalides")
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


# --- Abonnements rangés dans l'onglet Réglages (clé `push`, valeur JSON, une ligne par appareil) ---

def _settings_tab(sheet_id: str, create: bool, write: bool = False):
    from .notifications import SETTINGS_TAB, _tab

    return _tab(sheet_id, SETTINGS_TAB, ["CLÉ", "VALEUR"], create=create, write=write)


def _rows(ws) -> list[tuple[int, dict]]:
    """(numéro de ligne, abonnement) des lignes `push` lisibles."""
    found = []
    for n, row in enumerate(ws.get_values(), start=1):
        if n > 1 and len(row) > 1 and row[0] == PUSH_KEY:
            try:
                found.append((n, json.loads(row[1])))
            except ValueError:
                continue
    return found


def list_subscriptions(sheet_id: str) -> list[dict]:
    ws = _settings_tab(sheet_id, create=False)
    return [sub for _, sub in _rows(ws)] if ws is not None else []


def add_subscription(sheet_id: str, sub) -> int:
    """Enregistre l'appareil (une seule ligne par adresse) ; renvoie le nombre d'appareils abonnés."""
    sub = {**check_subscription(sub), "added": date.today().isoformat()}
    ws = _settings_tab(sheet_id, create=True)
    rows = _rows(ws)
    stale = [n for n, s in rows if s.get("endpoint") == sub["endpoint"]]
    kept = len(rows) - len(stale)
    stale += [n for n, s in rows if s.get("endpoint") != sub["endpoint"]][:max(0, kept + 1 - MAX_DEVICES)]
    for n in sorted(stale, reverse=True):  # du bas vers le haut : les numéros des autres lignes ne bougent pas
        ws.delete_rows(n)
    # RAW : le JSON reste un texte, jamais interprété comme une formule
    ws.append_row([PUSH_KEY, json.dumps(sub, separators=(",", ":"))], value_input_option="RAW")
    return len(rows) - len(stale) + 1


def remove_subscriptions(sheet_id: str, endpoints: set[str]) -> int:
    ws = _settings_tab(sheet_id, create=False, write=True)
    if ws is None or not endpoints:
        return 0
    stale = [n for n, s in _rows(ws) if s.get("endpoint") in endpoints]
    for n in sorted(stale, reverse=True):
        ws.delete_rows(n)
    return len(stale)


def send_to_subscription(sub: dict, title: str, body: str, url: str | None = None, tag: str | None = None) -> int:
    """Envoie une notification à un appareil ; renvoie le code HTTP du service de push."""
    import requests

    key = _vapid_private_key()
    if key is None:
        raise OperationError("Notifications de l'appli non configurées sur le serveur (clés VAPID absentes)")
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag}, ensure_ascii=False).encode()
    response = requests.post(sub["endpoint"], data=encrypt(payload, sub["keys"]["p256dh"], sub["keys"]["auth"]), timeout=30,
                             headers={"Authorization": vapid_header(sub["endpoint"], key, os.environ.get("VAPID_SUBJECT") or DEFAULT_SUBJECT),
                                      "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                                      "TTL": str(TTL_SECONDS), "Urgency": "normal"})
    return response.status_code


def send_push(sheet_id: str, title: str, body: str, url: str | None = None, tag: str | None = None) -> dict:
    """Envoie à tous les appareils de l'utilisateur. Un abonnement expiré (404 / 410 : appli désinstallée,
    notifications coupées dans les réglages du téléphone) est retiré du Sheet."""
    sent, gone, failed = 0, set(), 0
    for sub in list_subscriptions(sheet_id):
        try:
            status = send_to_subscription(sub, title, body, url, tag)
        except OperationError:
            raise
        except Exception:
            failed += 1
            continue
        if status in (404, 410):
            gone.add(sub["endpoint"])
        elif status < 300:
            sent += 1
        else:
            failed += 1
    removed = remove_subscriptions(sheet_id, gone)
    return {"sent": sent, "removed": removed, "failed": failed}


if __name__ == "__main__":
    private, public = generate_vapid_keys()
    print(f"VAPID_PRIVATE_KEY={private}\nVAPID_PUBLIC_KEY={public}")
