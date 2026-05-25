from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

ACCESS_TOKEN_TTL_SECONDS = 24 * 60 * 60


@dataclass
class PermissionRecord:
    id: UUID
    name: str
    description: str


@dataclass
class RoleRecord:
    id: UUID
    name: str
    description: str
    permissions: list[PermissionRecord]


@dataclass
class UserRecord:
    id: UUID
    tenant_id: UUID
    email: str
    display_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: list[RoleRecord]


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    tenant_id: UUID
    email: str
    roles: tuple[str, ...]
    permissions: frozenset[str]


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_TTL_SECONDS


@dataclass(frozen=True)
class ExternalIdentityRecord:
    user_id: UUID
    provider: str
    provider_account_id: str
    provider_login: str | None
    provider_email: str
    provider_email_verified: bool
