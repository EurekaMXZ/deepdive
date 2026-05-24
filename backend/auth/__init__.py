from __future__ import annotations

from backend.auth.models import CurrentUser, PermissionRecord, RoleRecord, TokenPair, UserRecord
from backend.auth.postgres_service import PostgresAuthService
from backend.auth.repository import PostgresAuthRepository
from backend.auth.service import AuthError, InMemoryAuthService
from backend.auth.tokens import InMemoryRefreshTokenStore, RedisRefreshTokenStore, RefreshTokenStore

__all__ = [
    "AuthError",
    "CurrentUser",
    "InMemoryAuthService",
    "InMemoryRefreshTokenStore",
    "PermissionRecord",
    "PostgresAuthRepository",
    "PostgresAuthService",
    "RedisRefreshTokenStore",
    "RefreshTokenStore",
    "RoleRecord",
    "TokenPair",
    "UserRecord",
]
