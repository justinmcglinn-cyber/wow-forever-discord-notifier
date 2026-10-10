"""Team webhooks built into the code, encrypted.

make_team_hooks.py encrypts the webhook URLs from a config.toml with a fresh
random key into forever_notify/team_data.py (committed), so every build is a
ready-to-share team exe.

This keeps the URLs from being read casually (Notepad, strings, secret
scanners), but the key sits next to the encrypted data, so anyone with the repo
or the exe can recover them. If one leaks, recreate that webhook in Discord,
re-run make_team_hooks.py and rebuild.

Cipher: SHA-256 in counter mode as the keystream, HMAC-SHA256 over nonce and
ciphertext for integrity (standard library only, so the exe stays small).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

MAGIC = b"FNTH1"
NONCE_SIZE = 16
TAG_SIZE = 32


class TeamHooksError(ValueError):
    pass


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:length])


def _keys(key: bytes) -> tuple[bytes, bytes]:
    """Separate encryption and authentication keys derived from the one key."""
    return hashlib.sha256(b"enc" + key).digest(), hashlib.sha256(b"mac" + key).digest()


def seal(data: bytes, key: bytes) -> bytes:
    enc_key, mac_key = _keys(key)
    nonce = os.urandom(NONCE_SIZE)
    body = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, MAGIC + nonce + body, hashlib.sha256).digest()
    return MAGIC + nonce + body + tag


def unseal(blob: bytes, key: bytes) -> bytes:
    if len(blob) < len(MAGIC) + NONCE_SIZE + TAG_SIZE or not blob.startswith(MAGIC):
        raise TeamHooksError("not a team webhook file")
    enc_key, mac_key = _keys(key)
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_SIZE]
    body, tag = blob[len(MAGIC) + NONCE_SIZE:-TAG_SIZE], blob[-TAG_SIZE:]
    expected = hmac.new(mac_key, MAGIC + nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise TeamHooksError("team webhooks are damaged or were built with a different key")
    return bytes(a ^ b for a, b in zip(body, _keystream(enc_key, nonce, len(body))))


def encode(webhook_url: str, webhooks: dict[str, str], key: bytes) -> bytes:
    return seal(json.dumps({"webhook_url": webhook_url, "webhooks": webhooks}).encode("utf-8"), key)


def decode(blob: bytes, key: bytes) -> tuple[str, dict[str, str]]:
    data = json.loads(unseal(blob, key).decode("utf-8"))
    return data.get("webhook_url", ""), dict(data.get("webhooks", {}))


def load_builtin() -> tuple[str, dict[str, str]] | None:
    """The team webhooks built into the code, or None if there are none."""
    try:
        from . import team_data  # written by make_team_hooks.py
    except ImportError:
        return None
    return decode(base64.b64decode(team_data.BLOB), bytes.fromhex(team_data.KEY))
