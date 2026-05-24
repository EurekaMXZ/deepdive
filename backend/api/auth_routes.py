from __future__ import annotations

import urllib.parse
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse

from backend.api.auth_dependencies import AuthService, auth_exception, get_auth_service, get_current_user
from backend.api.auth_schemas import (
    LoginRequest,
    OAuthExchangeRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.api.services import maybe_await
from backend.auth import AuthError, CurrentUser
from backend.auth.github import GitHubOAuthConfig, GitHubOAuthError, github_authorize_url, primary_verified_email
from backend.auth.oauth import InMemoryOAuthCodeStore, InMemoryOAuthStateStore
from backend.auth.turnstile import TurnstileConfig, TurnstileVerification

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    await _verify_turnstile(request, token=body.turnstile_token, action="register")
    try:
        user = await maybe_await(
            auth_service.register(email=body.email, password=body.password, display_name=body.display_name)
        )
    except AuthError as exc:
        raise auth_exception(exc.code, exc.message, status.HTTP_409_CONFLICT) from exc
    return UserResponse.from_record(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    await _verify_turnstile(request, token=body.turnstile_token, action="login")
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


@router.get("/github/start")
async def github_start(
    request: Request,
    redirect_to: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    config = _github_config(request)
    if not config.enabled:
        raise auth_exception("GITHUB_OAUTH_DISABLED", "GitHub OAuth is not enabled.", status.HTTP_404_NOT_FOUND)
    state = _oauth_state_store(request).create(
        redirect_to=_safe_redirect_to(redirect_to),
        ttl_seconds=config.state_ttl_seconds,
    )
    return RedirectResponse(
        github_authorize_url(config=config, state=state),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/github/callback")
async def github_callback(
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
) -> RedirectResponse:
    config = _github_config(request)
    if not config.enabled:
        raise auth_exception("GITHUB_OAUTH_DISABLED", "GitHub OAuth is not enabled.", status.HTTP_404_NOT_FOUND)
    state_payload = _oauth_state_store(request).pop(state)
    if state_payload is None:
        raise auth_exception("INVALID_OAUTH_STATE", "OAuth state is invalid or expired.", status.HTTP_400_BAD_REQUEST)
    client = request.app.state.github_oauth_client
    try:
        access_token = await client.exchange_code_for_token(code=code, redirect_uri=config.redirect_uri)
        github_user = await client.get_user(access_token)
        email = primary_verified_email(await client.list_emails(access_token))
    except GitHubOAuthError as exc:
        raise auth_exception("GITHUB_OAUTH_FAILED", str(exc), status.HTTP_400_BAD_REQUEST) from exc
    if email is None:
        raise auth_exception(
            "GITHUB_EMAIL_REQUIRED",
            "GitHub account must have a verified email.",
            status.HTTP_400_BAD_REQUEST,
        )
    _validate_allowed_email_domain(config, email)
    user = await maybe_await(
        auth_service.login_or_register_external_user(
            provider="github",
            provider_account_id=str(github_user.id),
            provider_login=github_user.login,
            email=email,
            email_verified=True,
            display_name=github_user.name or github_user.login,
        )
    )
    exchange_code = _oauth_code_store(request).create(
        user_id=str(user.id),
        ttl_seconds=config.exchange_code_ttl_seconds,
    )
    return RedirectResponse(
        _frontend_redirect_url(config.frontend_redirect_uri, code=exchange_code, redirect_to=state_payload.redirect_to),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.post("/exchange", response_model=TokenResponse)
async def exchange(
    body: OAuthExchangeRequest,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    exchange_payload = _oauth_code_store(request).pop(body.code)
    if exchange_payload is None:
        raise auth_exception(
            "INVALID_OAUTH_CODE",
            "OAuth exchange code is invalid or expired.",
            status.HTTP_401_UNAUTHORIZED,
        )
    try:
        return TokenResponse.from_pair(await maybe_await(auth_service.exchange_code(UUID(exchange_payload.user_id))))
    except (AuthError, ValueError) as exc:
        raise auth_exception(
            "INVALID_OAUTH_CODE",
            "OAuth exchange code is invalid or expired.",
            status.HTTP_401_UNAUTHORIZED,
        ) from exc


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    user = await maybe_await(auth_service.get_user(current_user.id))
    if user is None:
        raise auth_exception("INVALID_TOKEN", "Access token is invalid.", status.HTTP_401_UNAUTHORIZED)
    return UserResponse.from_record(user)


async def _verify_turnstile(request: Request, *, token: str | None, action: str) -> None:
    config = _turnstile_config(request)
    if not config.enabled:
        return
    if token is None or not token.strip():
        raise auth_exception("TURNSTILE_REQUIRED", "Turnstile token is required.", status.HTTP_403_FORBIDDEN)
    verifier = request.app.state.turnstile_verifier
    verification = TurnstileVerification(
        token=token,
        action=action,
        remote_ip=request.client.host if request.client is not None else None,
        idempotency_key=f"{action}:{token}",
    )
    if not await verifier.verify(verification):
        raise auth_exception("TURNSTILE_FAILED", "Turnstile verification failed.", status.HTTP_403_FORBIDDEN)


def _turnstile_config(request: Request) -> TurnstileConfig:
    return request.app.state.turnstile_config


def _github_config(request: Request) -> GitHubOAuthConfig:
    return request.app.state.github_oauth_config


def _oauth_state_store(request: Request) -> InMemoryOAuthStateStore:
    return request.app.state.oauth_state_store


def _oauth_code_store(request: Request) -> InMemoryOAuthCodeStore:
    return request.app.state.oauth_code_store


def _safe_redirect_to(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if not value.startswith("/") or value.startswith("//"):
        return None
    return value


def _frontend_redirect_url(base_url: str, *, code: str, redirect_to: str | None) -> str:
    query = {"code": code}
    if redirect_to is not None:
        query["redirect_to"] = redirect_to
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urllib.parse.urlencode(query)}"


def _validate_allowed_email_domain(config: GitHubOAuthConfig, email: str) -> None:
    if not config.allowed_email_domains:
        return
    domain = email.rsplit("@", 1)[-1].lower()
    if domain not in config.allowed_email_domains:
        raise auth_exception(
            "GITHUB_EMAIL_DOMAIN_DENIED",
            "GitHub email domain is not allowed.",
            status.HTTP_403_FORBIDDEN,
        )
