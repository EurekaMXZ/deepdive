from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(PASSWORD_ITERATIONS),
            _b64(salt),
            _b64(digest),
        )
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_text)
        salt = _unb64(salt_text)
        expected = _unb64(digest_text)
    except ValueError, TypeError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
