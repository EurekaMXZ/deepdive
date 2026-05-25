from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from backend.api.async_utils import maybe_await
from backend.auth import AuthError, CurrentUser, PermissionRecord, RoleRecord, TokenPair, UserRecord
from backend.ids import new_uuid7


class AuthService(Protocol):
    def register(
        self, *, email: str, password: str, display_name: str | None = None
    ) -> UserRecord | Awaitable[UserRecord]: ...

    def login(self, *, email: str, password: str) -> TokenPair | Awaitable[TokenPair]: ...

    def refresh(self, refresh_token: str) -> TokenPair | Awaitable[TokenPair]: ...

    def logout(self, refresh_token: str) -> None | Awaitable[None]: ...

    def exchange_code(self, user_id: UUID) -> TokenPair | Awaitable[TokenPair]: ...

    def login_or_register_external_user(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_login: str | None,
        email: str,
        email_verified: bool,
        display_name: str | None = None,
    ) -> UserRecord | Awaitable[UserRecord]: ...

    def current_user(self, access_token: str) -> CurrentUser | Awaitable[CurrentUser]: ...

    def list_users(
        self, *, limit: int = 50, cursor: str | None = None
    ) -> list[UserRecord] | Awaitable[list[UserRecord]]: ...

    def get_user(self, user_id: UUID) -> UserRecord | None | Awaitable[UserRecord | None]: ...

    def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
        role_names: list[str] | None = None,
    ) -> UserRecord | Awaitable[UserRecord]: ...

    def update_user(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        is_active: bool | None = None,
    ) -> UserRecord | None | Awaitable[UserRecord | None]: ...

    def list_roles(self) -> list[RoleRecord] | Awaitable[list[RoleRecord]]: ...

    def list_permissions(self) -> list[PermissionRecord] | Awaitable[list[PermissionRecord]]: ...

    def assign_roles(self, user_id: UUID, role_ids: list[UUID]) -> UserRecord | None | Awaitable[UserRecord | None]: ...


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


async def get_current_user(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> CurrentUser:
    if authorization is None or not authorization.startswith("Bearer "):
        raise auth_exception("AUTH_REQUIRED", "Authentication is required.", status.HTTP_401_UNAUTHORIZED)
    try:
        return await maybe_await(auth_service.current_user(authorization.removeprefix("Bearer ").strip()))
    except AuthError as exc:
        raise auth_exception(exc.code, exc.message, status.HTTP_401_UNAUTHORIZED) from exc


def require_permission(permission: str) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    async def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if permission not in user.permissions:
            raise auth_exception(
                "FORBIDDEN", "You do not have permission to access this resource.", status.HTTP_403_FORBIDDEN
            )
        return user

    return dependency


def auth_exception(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "request_id": str(new_uuid7()),
            }
        },
    )
