from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class RefreshTokenStore(Protocol):
    def put(self, token_hash: str, user_id: str, *, expires_at: datetime) -> None: ...

    def pop(self, token_hash: str) -> str | None: ...


class OAuthStateStore(Protocol):
    def create(self, *, redirect_to: str | None, ttl_seconds: int) -> str: ...

    def pop(self, state: str) -> object | None: ...


class OAuthCodeStore(Protocol):
    def create(self, *, user_id: str, ttl_seconds: int) -> str: ...

    def pop(self, code: str) -> object | None: ...


class InMemoryRefreshTokenStore:
    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, datetime]] = {}

    def put(self, token_hash: str, user_id: str, *, expires_at: datetime) -> None:
        self._tokens[token_hash] = (user_id, expires_at)

    def pop(self, token_hash: str) -> str | None:
        value = self._tokens.pop(token_hash, None)
        if value is None:
            return None
        user_id, expires_at = value
        if expires_at < datetime.now(UTC):
            return None
        return user_id


class RedisRefreshTokenStore:
    def __init__(self, client: RedisHashClient, *, key_prefix: str = "deepdive:refresh") -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")

    def put(self, token_hash: str, user_id: str, *, expires_at: datetime) -> None:
        ttl_seconds = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
        self._client.setex(self._key(token_hash), ttl_seconds, user_id)

    def pop(self, token_hash: str) -> str | None:
        key = self._key(token_hash)
        user_id = self._client.getdel(key)
        if isinstance(user_id, bytes):
            return user_id.decode("utf-8")
        return user_id

    def _key(self, token_hash: str) -> str:
        return f"{self._key_prefix}:{token_hash}"


class RedisHashClient(Protocol):
    def setex(self, name: str, time: int | timedelta, value: str) -> object: ...

    def getdel(self, name: str) -> str | bytes | None: ...
