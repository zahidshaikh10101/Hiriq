"""Password hashing and signed access tokens.

Tokens: base64url(json payload) + "." + base64url(HMAC-SHA256 signature), standard library only.
Passwords: argon2id via argon2-cffi.
When refresh tokens or third-party token verification are needed, move to a JWT library.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def same_secret(given: str, expected: str) -> bool:
    """Constant-time comparison (hash first so length differences don't leak)."""
    a = hashlib.sha256(given.encode()).digest()
    b = hashlib.sha256(expected.encode()).digest()
    return hmac.compare_digest(a, b)


# ---------- passwords ----------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


# Used to burn the same time when the account does not exist (no user enumeration by timing).
_DUMMY_HASH = _hasher.hash("hiriq-dummy-password")


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# ---------- tokens ----------
def create_token(subject: str, role: str, secret: str, hours: int) -> str:
    issued = time.time()
    payload = {"sub": subject, "role": role, "iat": int(issued * 1000) / 1000, "exp": int(issued) + hours * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body, secret)}"


def verify_token(token: str, secret: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig.encode(), _sign(body, secret).encode()):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload
