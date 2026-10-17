"""Team codes: a team's Discord webhooks in one string to paste into setup.

make_team_hooks.py turns the webhooks in a config.toml into a team code, to
post somewhere private (e.g. a pinned message in the guild's Discord). Setup
asks for it, so the exe and this repo hold no webhooks and can be public.

The code carries its own key, so the encryption only keeps the URLs from being
read casually (and from secret scanners); anyone with the code can post to the
channels. If it leaks, recreate the webhooks in Discord and make a new code.

Cipher: SHA-256 in counter mode as the keystream, HMAC-SHA256 over nonce and
ciphertext for integrity (standard library only, so the exe stays small).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import zlib

MAGIC = b"FNTH1"
CODE_PREFIX = "FNTEAM1-"
KEY_SIZE = 32
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
        raise TeamHooksError("not a team code")
    enc_key, mac_key = _keys(key)
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_SIZE]
    body, tag = blob[len(MAGIC) + NONCE_SIZE:-TAG_SIZE], blob[-TAG_SIZE:]
    expected = hmac.new(mac_key, MAGIC + nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise TeamHooksError("the team code is incomplete or mistyped")
    return bytes(a ^ b for a, b in zip(body, _keystream(enc_key, nonce, len(body))))


def encode(webhook_url: str, webhooks: dict[str, str], key: bytes) -> bytes:
    data = json.dumps({"webhook_url": webhook_url, "webhooks": webhooks}, separators=(",", ":"))
    return seal(zlib.compress(data.encode("utf-8"), 9), key)


def decode(blob: bytes, key: bytes) -> tuple[str, dict[str, str]]:
    try:
        data = json.loads(zlib.decompress(unseal(blob, key)).decode("utf-8"))
    except (zlib.error, UnicodeDecodeError, ValueError) as e:
        if isinstance(e, TeamHooksError):
            raise
        raise TeamHooksError("not a team code") from e
    return data.get("webhook_url", ""), dict(data.get("webhooks", {}))


def make_code(webhook_url: str, webhooks: dict[str, str]) -> str:
    key = os.urandom(KEY_SIZE)
    return CODE_PREFIX + base64.urlsafe_b64encode(key + encode(webhook_url, webhooks, key)).decode("ascii").rstrip("=")


def read_code(code: str) -> tuple[str, dict[str, str]]:
    """The webhooks in a team code. Spaces and line breaks (from wrapped chat messages) are ignored."""
    code = re.sub(r"\s+", "", code).strip("`\"'")
    if not code.startswith(CODE_PREFIX):
        raise TeamHooksError("not a team code (it starts with " + CODE_PREFIX + ")")
    body = code[len(CODE_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError as e:
        raise TeamHooksError("the team code is incomplete or mistyped") from e
    return decode(raw[KEY_SIZE:], raw[:KEY_SIZE])
