from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


@dataclass(frozen=True)
class TurnstileConfig:
    enabled: bool = False
    secret_key: str = ""
    allowed_hostnames: frozenset[str] = field(default_factory=lambda: frozenset[str]())
    timeout_seconds: int = 5


@dataclass(frozen=True)
class TurnstileVerification:
    token: str
    action: str
    remote_ip: str | None
    idempotency_key: str


class TurnstileVerifier(Protocol):
    async def verify(self, verification: TurnstileVerification) -> bool: ...


class CloudflareTurnstileVerifier:
    def __init__(self, config: TurnstileConfig) -> None:
        self._config = config

    async def verify(self, verification: TurnstileVerification) -> bool:
        return await asyncio.to_thread(self.verify_sync, verification)

    def verify_sync(self, verification: TurnstileVerification) -> bool:
        if not self._config.secret_key:
            return False
        payload = {
            "secret": self._config.secret_key,
            "response": verification.token,
            "idempotency_key": verification.idempotency_key,
        }
        if verification.remote_ip:
            payload["remoteip"] = verification.remote_ip
        request = urllib.request.Request(
            TURNSTILE_SITEVERIFY_URL,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                data = _json_object(json.loads(response.read().decode("utf-8")))
        except OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError:
            return False
        if not bool(data.get("success")):
            return False
        action = data.get("action")
        if isinstance(action, str) and action and action != verification.action:
            return False
        hostname = data.get("hostname")
        return not (
            self._config.allowed_hostnames
            and isinstance(hostname, str)
            and hostname not in self._config.allowed_hostnames
        )


class NoopTurnstileVerifier:
    async def verify(self, verification: TurnstileVerification) -> bool:
        del verification
        return True


def _json_object(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}
