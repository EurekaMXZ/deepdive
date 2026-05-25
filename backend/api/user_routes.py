from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator

from backend.api.auth_dependencies import AuthService, auth_exception, get_auth_service, require_permission
from backend.api.auth_schemas import RoleResponse, UserResponse, normalize_email
from backend.api.pagination import cursor_offset
from backend.api.services import maybe_await
from backend.auth import AuthError, CurrentUser

router = APIRouter(tags=["users"])


class UserCreateRequest(BaseModel):
    email: str
    password: str = Field(min_length=12)
    display_name: str | None = None
    role_names: list[str] | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None


class UserListResponse(BaseModel):
    items: list[UserResponse]
    next_cursor: str | None = None


class UserRolesUpdateRequest(BaseModel):
    role_ids: list[UUID]


class UserRolesResponse(BaseModel):
    roles: list[RoleResponse]


@router.get("/users", response_model=UserListResponse)
async def list_users(
    _: Annotated[CurrentUser, Depends(require_permission("users:read"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> UserListResponse:
    offset = cursor_offset(cursor)
    users = await maybe_await(auth_service.list_users(limit=limit + 1, cursor=cursor))
    page = users[:limit]
    next_cursor = str(offset + limit) if len(users) > limit else None
    return UserListResponse(
        items=[UserResponse.from_record(user) for user in page],
        next_cursor=next_cursor,
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    _: Annotated[CurrentUser, Depends(require_permission("users:write"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    try:
        user = await maybe_await(
            auth_service.create_user(
                email=body.email,
                password=body.password,
                display_name=body.display_name,
                role_names=body.role_names,
            )
        )
    except AuthError as exc:
        status_code = status.HTTP_404_NOT_FOUND if exc.code == "ROLE_NOT_FOUND" else status.HTTP_409_CONFLICT
        raise auth_exception(exc.code, exc.message, status_code) from exc
    return UserResponse.from_record(user)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    _: Annotated[CurrentUser, Depends(require_permission("users:read"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    user = await maybe_await(auth_service.get_user(user_id))
    if user is None:
        raise auth_exception("USER_NOT_FOUND", "User does not exist.", status.HTTP_404_NOT_FOUND)
    return UserResponse.from_record(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdateRequest,
    _: Annotated[CurrentUser, Depends(require_permission("users:write"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    user = await maybe_await(
        auth_service.update_user(user_id, display_name=body.display_name, is_active=body.is_active)
    )
    if user is None:
        raise auth_exception("USER_NOT_FOUND", "User does not exist.", status.HTTP_404_NOT_FOUND)
    return UserResponse.from_record(user)


@router.put("/users/{user_id}/roles", response_model=UserRolesResponse)
async def update_user_roles(
    user_id: UUID,
    body: UserRolesUpdateRequest,
    _: Annotated[CurrentUser, Depends(require_permission("users:write"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserRolesResponse:
    try:
        user = await maybe_await(auth_service.assign_roles(user_id, body.role_ids))
    except AuthError as exc:
        raise auth_exception(exc.code, exc.message, status.HTTP_404_NOT_FOUND) from exc
    if user is None:
        raise auth_exception("USER_NOT_FOUND", "User does not exist.", status.HTTP_404_NOT_FOUND)
    return UserRolesResponse(roles=[RoleResponse.from_record(role) for role in user.roles])
