from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.auth import PermissionRecord, RoleRecord, TokenPair, UserRecord


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("email must be a valid email address")
    return email


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=12)
    display_name: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int

    @classmethod
    def from_pair(cls, pair: TokenPair) -> TokenResponse:
        return cls(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
        )


class PermissionResponse(BaseModel):
    id: UUID
    name: str
    description: str

    @classmethod
    def from_record(cls, permission: PermissionRecord) -> PermissionResponse:
        return cls(id=permission.id, name=permission.name, description=permission.description)


class RoleResponse(BaseModel):
    id: UUID
    name: str
    description: str
    permissions: list[PermissionResponse]

    @classmethod
    def from_record(cls, role: RoleRecord) -> RoleResponse:
        return cls(
            id=role.id,
            name=role.name,
            description=role.description,
            permissions=[PermissionResponse.from_record(permission) for permission in role.permissions],
        )


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    email: str
    display_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: list[RoleResponse]
    permissions: list[str]

    @classmethod
    def from_record(cls, user: UserRecord) -> UserResponse:
        permissions = sorted({permission.name for role in user.roles for permission in role.permissions})
        return cls(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            display_name=user.display_name,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at,
            roles=[RoleResponse.from_record(role) for role in user.roles],
            permissions=permissions,
        )
