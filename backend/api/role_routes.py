from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.auth_dependencies import AuthService, get_auth_service, require_permission
from backend.api.auth_schemas import PermissionResponse, RoleResponse
from backend.api.services import maybe_await
from backend.auth import CurrentUser

router = APIRouter(tags=["roles"])


class RoleListResponse(BaseModel):
    items: list[RoleResponse]


class PermissionListResponse(BaseModel):
    items: list[PermissionResponse]


@router.get("/roles", response_model=RoleListResponse)
async def list_roles(
    _: Annotated[CurrentUser, Depends(require_permission("roles:read"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> RoleListResponse:
    return RoleListResponse(
        items=[RoleResponse.from_record(role) for role in await maybe_await(auth_service.list_roles())]
    )


@router.get("/permissions", response_model=PermissionListResponse)
async def list_permissions(
    _: Annotated[CurrentUser, Depends(require_permission("roles:read"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> PermissionListResponse:
    return PermissionListResponse(
        items=[
            PermissionResponse.from_record(permission)
            for permission in await maybe_await(auth_service.list_permissions())
        ]
    )
