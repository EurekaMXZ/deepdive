from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.auth.jwt import JwtError, decode_jwt, encode_jwt
from backend.auth.models import (
    ACCESS_TOKEN_TTL_SECONDS,
    CurrentUser,
    PermissionRecord,
    RoleRecord,
    TokenPair,
    UserRecord,
)
from backend.auth.passwords import verify_password
from backend.auth.repository import PostgresAuthRepository, RoleNotFoundError
from backend.auth.service import AuthError, current_user_from_record, normalize_email, token_hash
from backend.auth.tokens import RefreshTokenStore
from backend.ids import new_uuid7


class PostgresAuthService:
    def __init__(
        self, *, repository: PostgresAuthRepository, jwt_secret: str, refresh_token_store: RefreshTokenStore
    ) -> None:
        self._repository = repository
        self._jwt_secret = jwt_secret
        self._refresh_token_store = refresh_token_store

    async def register(self, *, email: str, password: str, display_name: str | None = None) -> UserRecord:
        await self._repository.ensure_seed_data()
        normalized_email = normalize_email(email)
        if await self._repository.get_user_by_email_with_password(normalized_email) is not None:
            raise AuthError("USER_ALREADY_EXISTS", "A user with this email already exists.")
        role_name = "admin" if not await self._repository.has_users() else "member"
        return await self.create_user(
            email=normalized_email,
            password=password,
            display_name=display_name,
            role_names=[role_name],
        )

    async def login(self, *, email: str, password: str) -> TokenPair:
        await self._repository.ensure_seed_data()
        user_and_password = await self._repository.get_user_by_email_with_password(normalize_email(email))
        if user_and_password is None:
            raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.")
        user, password_hash = user_and_password
        if not user.is_active or not verify_password(password, password_hash):
            raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.")
        return self._issue_tokens(user)

    async def exchange_code(self, user_id: UUID) -> TokenPair:
        user = await self._repository.get_user(user_id)
        if user is None or not user.is_active:
            raise AuthError("INVALID_OAUTH_CODE", "OAuth exchange code is invalid or expired.")
        return self._issue_tokens(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        user_id_text = self._refresh_token_store.pop(token_hash(refresh_token))
        if user_id_text is None:
            raise AuthError("INVALID_REFRESH_TOKEN", "Refresh token is invalid.")
        try:
            user_id = UUID(user_id_text)
        except ValueError as exc:
            raise AuthError("INVALID_REFRESH_TOKEN", "Refresh token is invalid.") from exc
        user = await self._repository.get_user(user_id)
        if user is None or not user.is_active:
            raise AuthError("INVALID_REFRESH_TOKEN", "Refresh token is invalid.")
        return self._issue_tokens(user)

    async def logout(self, refresh_token: str) -> None:
        self._refresh_token_store.pop(token_hash(refresh_token))

    async def current_user(self, access_token: str) -> CurrentUser:
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
        user = await self._repository.get_user(user_id)
        if user is None or not user.is_active:
            raise AuthError("INVALID_TOKEN", "Access token is invalid.")
        return current_user_from_record(user)

    async def list_users(self, *, limit: int = 50, cursor: str | None = None) -> list[UserRecord]:
        await self._repository.ensure_seed_data()
        return await self._repository.list_users(limit=limit, cursor=cursor)

    async def get_user(self, user_id: UUID) -> UserRecord | None:
        await self._repository.ensure_seed_data()
        return await self._repository.get_user(user_id)

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
        role_names: list[str] | None = None,
    ) -> UserRecord:
        await self._repository.ensure_seed_data()
        normalized_email = normalize_email(email)
        if await self._repository.get_user_by_email_with_password(normalized_email) is not None:
            raise AuthError("USER_ALREADY_EXISTS", "A user with this email already exists.")
        names = role_names or ["member"]
        if not await self._repository.role_names_exist(names):
            raise AuthError("ROLE_NOT_FOUND", "One or more roles do not exist.")
        return await self._repository.create_user(
            email=normalized_email,
            password=password,
            display_name=display_name,
            role_names=names,
        )

    async def login_or_register_external_user(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_login: str | None,
        email: str,
        email_verified: bool,
        display_name: str | None = None,
    ) -> UserRecord:
        await self._repository.ensure_seed_data()
        normalized_email = normalize_email(email)
        user = await self._repository.get_user_by_external_identity(provider, provider_account_id)
        if user is not None:
            if not user.is_active:
                raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.")
            return user

        user_by_email = await self._repository.get_user_by_email(normalized_email)
        if user_by_email is None:
            role_name = "admin" if not await self._repository.has_users() else "member"
            user_by_email = await self._repository.create_user_without_password(
                email=normalized_email,
                display_name=display_name,
                role_names=[role_name],
            )
        await self._repository.link_external_identity(
            user_id=user_by_email.id,
            provider=provider,
            provider_account_id=provider_account_id,
            provider_login=provider_login,
            provider_email=normalized_email,
            provider_email_verified=email_verified,
        )
        return user_by_email

    async def update_user(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        is_active: bool | None = None,
    ) -> UserRecord | None:
        await self._repository.ensure_seed_data()
        return await self._repository.update_user(user_id, display_name=display_name, is_active=is_active)

    async def reset_password(self, user_id: UUID, *, password: str) -> bool:
        await self._repository.ensure_seed_data()
        return await self._repository.reset_password(user_id, password=password)

    async def list_roles(self) -> list[RoleRecord]:
        await self._repository.ensure_seed_data()
        return await self._repository.list_roles()

    async def list_permissions(self) -> list[PermissionRecord]:
        await self._repository.ensure_seed_data()
        return await self._repository.list_permissions()

    async def assign_roles(self, user_id: UUID, role_ids: list[UUID]) -> UserRecord | None:
        await self._repository.ensure_seed_data()
        try:
            return await self._repository.assign_roles(user_id, role_ids)
        except RoleNotFoundError as exc:
            raise AuthError("ROLE_NOT_FOUND", "One or more roles do not exist.") from exc

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
            expires_delta=timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
        )
        refresh_token = secrets.token_urlsafe(48)
        self._refresh_token_store.put(
            token_hash(refresh_token),
            str(user.id),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        return TokenPair(access_token=access_token, refresh_token=refresh_token)
