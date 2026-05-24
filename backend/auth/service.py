from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.auth.jwt import JwtError, decode_jwt, encode_jwt
from backend.auth.models import CurrentUser, ExternalIdentityRecord, PermissionRecord, RoleRecord, TokenPair, UserRecord
from backend.auth.passwords import hash_password, verify_password
from backend.auth.tokens import InMemoryRefreshTokenStore, RefreshTokenStore
from backend.ids import new_uuid7

DEFAULT_TENANT_ID = UUID("00000000-0000-7000-8000-000000000001")

PERMISSION_DESCRIPTIONS = {
    "analysis:create": "Create analysis jobs",
    "analysis:read": "Read analysis jobs",
    "analysis:cancel": "Cancel analysis jobs",
    "analysis:events": "Read analysis event streams",
    "documents:read": "Read analysis documents",
    "documents:delete": "Delete analysis documents",
    "users:read": "Read users",
    "users:write": "Manage users",
    "roles:read": "Read roles",
    "roles:write": "Manage roles",
}

ROLE_PERMISSIONS = {
    "admin": tuple(PERMISSION_DESCRIPTIONS),
    "member": (
        "analysis:create",
        "analysis:read",
        "analysis:cancel",
        "analysis:events",
        "documents:read",
    ),
    "viewer": (
        "analysis:read",
        "analysis:events",
        "documents:read",
    ),
}


class AuthError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InMemoryAuthService:
    def __init__(
        self,
        *,
        jwt_secret: str = "deepdive-dev-secret",
        refresh_token_store: RefreshTokenStore | None = None,
    ) -> None:
        self._jwt_secret = jwt_secret
        self._refresh_token_store = refresh_token_store or InMemoryRefreshTokenStore()
        self._permissions = {
            name: PermissionRecord(id=new_uuid7(), name=name, description=description)
            for name, description in PERMISSION_DESCRIPTIONS.items()
        }
        self._roles = {
            name: RoleRecord(
                id=new_uuid7(),
                name=name,
                description=f"Built-in {name} role",
                permissions=[self._permissions[permission] for permission in permissions],
            )
            for name, permissions in ROLE_PERMISSIONS.items()
        }
        self._users: dict[UUID, UserRecord] = {}
        self._password_hashes: dict[UUID, str] = {}
        self._external_identities: dict[tuple[str, str], ExternalIdentityRecord] = {}

    def register(self, *, email: str, password: str, display_name: str | None = None) -> UserRecord:
        normalized_email = normalize_email(email)
        if self._user_by_email(normalized_email) is not None:
            raise AuthError("USER_ALREADY_EXISTS", "A user with this email already exists.")
        role_name = "admin" if not self._users else "member"
        return self.create_user(
            email=normalized_email, password=password, display_name=display_name, role_names=[role_name]
        )

    def login(self, *, email: str, password: str) -> TokenPair:
        user = self._user_by_email(normalize_email(email))
        if (
            user is None
            or not user.is_active
            or user.id not in self._password_hashes
            or not verify_password(password, self._password_hashes[user.id])
        ):
            raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.")
        return self._issue_tokens(user)

    def refresh(self, refresh_token: str) -> TokenPair:
        hashed_refresh_token = token_hash(refresh_token)
        user_id_text = self._refresh_token_store.pop(hashed_refresh_token)
        if user_id_text is None:
            raise AuthError("INVALID_REFRESH_TOKEN", "Refresh token is invalid.")
        try:
            user_id = UUID(user_id_text)
        except ValueError as exc:
            raise AuthError("INVALID_REFRESH_TOKEN", "Refresh token is invalid.") from exc
        user = self._users.get(user_id)
        if user is None or not user.is_active:
            raise AuthError("INVALID_REFRESH_TOKEN", "Refresh token is invalid.")
        return self._issue_tokens(user)

    def exchange_code(self, user_id: UUID) -> TokenPair:
        user = self._users.get(user_id)
        if user is None or not user.is_active:
            raise AuthError("INVALID_OAUTH_CODE", "OAuth exchange code is invalid or expired.")
        return self._issue_tokens(user)

    def logout(self, refresh_token: str) -> None:
        self._refresh_token_store.pop(token_hash(refresh_token))

    def current_user(self, access_token: str) -> CurrentUser:
        try:
            claims = decode_jwt(access_token, secret=self._jwt_secret)
        except JwtError as exc:
            raise AuthError("INVALID_TOKEN", "Access token is invalid or expired.") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise AuthError("INVALID_TOKEN", "Access token is invalid.")
        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise AuthError("INVALID_TOKEN", "Access token is invalid.") from exc
        user = self._users.get(user_id)
        if user is None or not user.is_active:
            raise AuthError("INVALID_TOKEN", "Access token is invalid.")
        return current_user_from_record(user)

    def list_users(self) -> list[UserRecord]:
        return sorted(self._users.values(), key=lambda user: user.created_at)

    def get_user(self, user_id: UUID) -> UserRecord | None:
        return self._users.get(user_id)

    def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
        role_names: list[str] | None = None,
    ) -> UserRecord:
        normalized_email = normalize_email(email)
        if self._user_by_email(normalized_email) is not None:
            raise AuthError("USER_ALREADY_EXISTS", "A user with this email already exists.")
        roles = self._roles_by_names(role_names or ["member"])
        now = datetime.now(UTC)
        user = UserRecord(
            id=new_uuid7(),
            tenant_id=DEFAULT_TENANT_ID,
            email=normalized_email,
            display_name=display_name,
            is_active=True,
            created_at=now,
            updated_at=now,
            roles=roles,
        )
        self._users[user.id] = user
        self._password_hashes[user.id] = hash_password(password)
        return user

    def login_or_register_external_user(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_login: str | None,
        email: str,
        email_verified: bool,
        display_name: str | None = None,
    ) -> UserRecord:
        normalized_email = normalize_email(email)
        identity = self._external_identities.get((provider, provider_account_id))
        if identity is not None:
            user = self._users.get(identity.user_id)
            if user is None or not user.is_active:
                raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.")
            return user

        user = self._user_by_email(normalized_email)
        if user is None:
            role_name = "admin" if not self._users else "member"
            user = self.create_user_without_password(
                email=normalized_email,
                display_name=display_name,
                role_names=[role_name],
            )
        self._external_identities[(provider, provider_account_id)] = ExternalIdentityRecord(
            user_id=user.id,
            provider=provider,
            provider_account_id=provider_account_id,
            provider_login=provider_login,
            provider_email=normalized_email,
            provider_email_verified=email_verified,
        )
        return user

    def create_user_without_password(
        self,
        *,
        email: str,
        display_name: str | None = None,
        role_names: list[str] | None = None,
    ) -> UserRecord:
        normalized_email = normalize_email(email)
        if self._user_by_email(normalized_email) is not None:
            raise AuthError("USER_ALREADY_EXISTS", "A user with this email already exists.")
        roles = self._roles_by_names(role_names or ["member"])
        now = datetime.now(UTC)
        user = UserRecord(
            id=new_uuid7(),
            tenant_id=DEFAULT_TENANT_ID,
            email=normalized_email,
            display_name=display_name,
            is_active=True,
            created_at=now,
            updated_at=now,
            roles=roles,
        )
        self._users[user.id] = user
        return user

    def update_user(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        is_active: bool | None = None,
    ) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        if display_name is not None:
            user.display_name = display_name
        if is_active is not None:
            user.is_active = is_active
        user.updated_at = datetime.now(UTC)
        return user

    def reset_password(self, user_id: UUID, *, password: str) -> bool:
        if user_id not in self._users:
            return False
        self._password_hashes[user_id] = hash_password(password)
        return True

    def list_roles(self) -> list[RoleRecord]:
        return sorted(self._roles.values(), key=lambda role: role.name)

    def list_permissions(self) -> list[PermissionRecord]:
        return sorted(self._permissions.values(), key=lambda permission: permission.name)

    def assign_roles(self, user_id: UUID, role_ids: list[UUID]) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        roles_by_id = {role.id: role for role in self._roles.values()}
        missing_role_ids = [role_id for role_id in role_ids if role_id not in roles_by_id]
        if missing_role_ids:
            raise AuthError("ROLE_NOT_FOUND", "One or more roles do not exist.")
        roles = [roles_by_id[role_id] for role_id in dict.fromkeys(role_ids)]
        user.roles = roles
        user.updated_at = datetime.now(UTC)
        return user

    def _roles_by_names(self, role_names: list[str]) -> list[RoleRecord]:
        roles: list[RoleRecord] = []
        for role_name in dict.fromkeys(role_names):
            role = self._roles.get(role_name)
            if role is None:
                raise AuthError("ROLE_NOT_FOUND", "One or more roles do not exist.")
            roles.append(role)
        return roles

    def _issue_tokens(self, user: UserRecord) -> TokenPair:
        current_user = current_user_from_record(user)
        access_token = encode_jwt(
            {
                "sub": str(user.id),
                "tenant_id": str(user.tenant_id),
                "email": user.email,
                "roles": list(current_user.roles),
                "permissions": sorted(current_user.permissions),
                "jti": str(new_uuid7()),
            },
            secret=self._jwt_secret,
            expires_delta=timedelta(minutes=30),
        )
        refresh_token = secrets.token_urlsafe(48)
        self._refresh_token_store.put(
            token_hash(refresh_token),
            str(user.id),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        return TokenPair(access_token=access_token, refresh_token=refresh_token)

    def _user_by_email(self, email: str) -> UserRecord | None:
        for user in self._users.values():
            if user.email == email:
                return user
        return None


def current_user_from_record(user: UserRecord) -> CurrentUser:
    role_names = tuple(role.name for role in user.roles)
    permissions = frozenset(permission.name for role in user.roles for permission in role.permissions)
    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=role_names,
        permissions=permissions,
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()


def token_hash(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


_current_user_from_record = current_user_from_record
_normalize_email = normalize_email
_token_hash = token_hash
