from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.auth_dependencies import AuthService, auth_exception, get_auth_service, get_current_user
from backend.api.auth_schemas import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.api.services import maybe_await
from backend.auth import AuthError, CurrentUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    try:
        user = await maybe_await(
            auth_service.register(email=body.email, password=body.password, display_name=body.display_name)
        )
    except AuthError as exc:
        raise auth_exception(exc.code, exc.message, status.HTTP_409_CONFLICT) from exc
    return UserResponse.from_record(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, auth_service: Annotated[AuthService, Depends(get_auth_service)]) -> TokenResponse:
    try:
        return TokenResponse.from_pair(await maybe_await(auth_service.login(email=body.email, password=body.password)))
    except AuthError as exc:
        raise auth_exception(exc.code, exc.message, status.HTTP_401_UNAUTHORIZED) from exc


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        return TokenResponse.from_pair(await maybe_await(auth_service.refresh(body.refresh_token)))
    except AuthError as exc:
        raise auth_exception(exc.code, exc.message, status.HTTP_401_UNAUTHORIZED) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshTokenRequest, auth_service: Annotated[AuthService, Depends(get_auth_service)]) -> None:
    await maybe_await(auth_service.logout(body.refresh_token))


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    user = await maybe_await(auth_service.get_user(current_user.id))
    if user is None:
        raise auth_exception("INVALID_TOKEN", "Access token is invalid.", status.HTTP_401_UNAUTHORIZED)
    return UserResponse.from_record(user)
