from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast


class JwtError(ValueError):
    pass


def encode_jwt(claims: dict[str, Any], *, secret: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join((_json_b64(header), _json_b64(payload)))
    signature = _sign(signing_input, secret)
    return f"{signing_input}.{signature}"


def decode_jwt(token: str, *, secret: str) -> dict[str, Any]:
    try:
        header_text, payload_text, signature = token.split(".", 2)
    except ValueError as exc:
        raise JwtError("Malformed token") from exc
    signing_input = f"{header_text}.{payload_text}"
    expected = _sign(signing_input, secret)
    if not hmac.compare_digest(signature, expected):
        raise JwtError("Invalid token signature")
    header = _json_unb64(header_text)
    if header.get("alg") != "HS256":
        raise JwtError("Unsupported token algorithm")
    payload = _json_unb64(payload_text)
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(datetime.now(UTC).timestamp()):
        raise JwtError("Expired token")
    return payload


def _json_b64(value: dict[str, Any]) -> str:
    data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _json_unb64(value: str) -> dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    decoded = base64.urlsafe_b64decode((value + padding).encode("ascii"))
    payload = json.loads(decoded)
    if not isinstance(payload, dict):
        raise JwtError("JWT segment is not a JSON object")
    return cast(dict[str, Any], payload)


def _sign(value: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
