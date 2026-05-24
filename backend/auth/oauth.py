from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class OAuthState:
    redirect_to: str | None
    expires_at: datetime


@dataclass(frozen=True)
class OAuthExchangeCode:
    user_id: str
    expires_at: datetime


class InMemoryOAuthStateStore:
    def __init__(self) -> None:
        self._states: dict[str, OAuthState] = {}

    def create(self, *, redirect_to: str | None, ttl_seconds: int) -> str:
        state = secrets.token_urlsafe(32)
        self._states[state] = OAuthState(
            redirect_to=redirect_to,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        return state

    def pop(self, state: str) -> OAuthState | None:
        value = self._states.pop(state, None)
        if value is None or value.expires_at < datetime.now(UTC):
            return None
        return value


class InMemoryOAuthCodeStore:
    def __init__(self) -> None:
        self._codes: dict[str, OAuthExchangeCode] = {}

    def create(self, *, user_id: str, ttl_seconds: int) -> str:
        code = secrets.token_urlsafe(32)
        self._codes[code] = OAuthExchangeCode(
            user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        return code

    def pop(self, code: str) -> OAuthExchangeCode | None:
        value = self._codes.pop(code, None)
        if value is None or value.expires_at < datetime.now(UTC):
            return None
        return value


class RedisOAuthStateStore:
    def __init__(self, client: RedisStringClient, *, key_prefix: str = "deepdive:oauth:state") -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")

    def create(self, *, redirect_to: str | None, ttl_seconds: int) -> str:
        state = secrets.token_urlsafe(32)
        value = redirect_to or ""
        self._client.setex(self._key(state), ttl_seconds, value)
        return state

    def pop(self, state: str) -> OAuthState | None:
        value = self._client.getdel(self._key(state))
        if value is None:
            return None
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        return OAuthState(
            redirect_to=text or None,
            expires_at=datetime.now(UTC) + timedelta(seconds=1),
        )

    def _key(self, state: str) -> str:
        return f"{self._key_prefix}:{state}"


class RedisOAuthCodeStore:
    def __init__(self, client: RedisStringClient, *, key_prefix: str = "deepdive:oauth:code") -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")

    def create(self, *, user_id: str, ttl_seconds: int) -> str:
        code = secrets.token_urlsafe(32)
        self._client.setex(self._key(code), ttl_seconds, user_id)
        return code

    def pop(self, code: str) -> OAuthExchangeCode | None:
        value = self._client.getdel(self._key(code))
        if value is None:
            return None
        user_id = value.decode("utf-8") if isinstance(value, bytes) else value
        return OAuthExchangeCode(
            user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=1),
        )

    def _key(self, code: str) -> str:
        return f"{self._key_prefix}:{code}"


class RedisStringClient(Protocol):
    def setex(self, name: str, time: int | timedelta, value: str) -> object: ...

    def getdel(self, name: str) -> str | bytes | None: ...
