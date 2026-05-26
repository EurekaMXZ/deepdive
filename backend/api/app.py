from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, HTTPException
from starlette.types import ExceptionHandler

from backend.api.auth_routes import router as auth_router
from backend.api.document_routes import router as document_router
from backend.api.role_routes import router as role_router
from backend.api.routes import api_exception_handler, router
from backend.api.services import InMemoryAnalysisService, PostgresAnalysisService
from backend.api.user_routes import router as user_router
from backend.auth import (
    InMemoryAuthService,
    InMemoryRefreshTokenStore,
    PostgresAuthRepository,
    PostgresAuthService,
    RedisRefreshTokenStore,
    RefreshTokenStore,
)
from backend.auth.github import GitHubOAuthConfig, UrlLibGitHubOAuthClient
from backend.auth.oauth import (
    InMemoryOAuthCodeStore,
    InMemoryOAuthStateStore,
    RedisOAuthCodeStore,
    RedisOAuthStateStore,
)
from backend.auth.turnstile import CloudflareTurnstileVerifier, NoopTurnstileVerifier, TurnstileConfig
from backend.config import DEFAULT_CONFIG_VERSION, AppConfig, load_app_config_from_env, load_dotenv_if_exists
from backend.db.runtime import create_database, create_database_from_env
from backend.document import DocumentRepository, DocumentService
from backend.document.repository import PostgresDocumentRepository
from backend.storage import DEFAULT_OBJECT_BUCKET, InMemoryObjectStorage, MinioObjectStorage

API_PREFIX = "/api"


def create_app() -> FastAPI:
    app = FastAPI(title="DeepDive Backend")
    app.state.analysis_service = InMemoryAnalysisService()
    app.state.auth_service = InMemoryAuthService(jwt_secret=_jwt_secret(), refresh_token_store=_refresh_token_store())
    app.state.document_service = DocumentService(repository=DocumentRepository(), storage=InMemoryObjectStorage())
    _install_auth_integrations(app)
    _install_routes(app)
    return app


def create_postgres_app(
    *,
    database_url: str | None = None,
    config: AppConfig | None = None,
    config_version: str = DEFAULT_CONFIG_VERSION,
) -> FastAPI:
    database = create_database(database_url) if database_url is not None else create_database_from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(title="DeepDive Backend", lifespan=lifespan)
    effective_config = config or AppConfig.default()
    app.state.database = database
    app.state.analysis_service = PostgresAnalysisService(
        database,
        config=effective_config,
        config_version=config_version,
    )
    app.state.auth_service = PostgresAuthService(
        repository=PostgresAuthRepository(database),
        jwt_secret=_jwt_secret(),
        refresh_token_store=_refresh_token_store(),
    )
    app.state.document_service = DocumentService(
        repository=PostgresDocumentRepository(database),
        storage=_object_storage_from_env(),
    )
    _install_auth_integrations(app)
    _install_routes(app)

    return app


def create_app_from_env() -> FastAPI:
    load_dotenv_if_exists()
    if "DATABASE_URL" in os.environ:
        return create_postgres_app(config=load_app_config_from_env())
    return create_app()


def _install_routes(app: FastAPI) -> None:
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(user_router, prefix=API_PREFIX)
    app.include_router(role_router, prefix=API_PREFIX)
    app.include_router(router, prefix=API_PREFIX)
    app.include_router(document_router, prefix=API_PREFIX)
    app.add_exception_handler(HTTPException, cast(ExceptionHandler, api_exception_handler))


def _install_auth_integrations(app: FastAPI) -> None:
    turnstile_config = _turnstile_config_from_env()
    github_config = _github_oauth_config_from_env()
    app.state.turnstile_config = turnstile_config
    app.state.turnstile_verifier = (
        CloudflareTurnstileVerifier(turnstile_config) if turnstile_config.enabled else NoopTurnstileVerifier()
    )
    app.state.github_oauth_config = github_config
    app.state.github_oauth_client = UrlLibGitHubOAuthClient(github_config)
    redis_client = _redis_client_from_env()
    if redis_client is None:
        app.state.oauth_state_store = InMemoryOAuthStateStore()
        app.state.oauth_code_store = InMemoryOAuthCodeStore()
    else:
        app.state.oauth_state_store = RedisOAuthStateStore(redis_client)
        app.state.oauth_code_store = RedisOAuthCodeStore(redis_client)


def _jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "deepdive-dev-secret")


def _refresh_token_store() -> RefreshTokenStore:
    redis_client = _redis_client_from_env()
    if redis_client is None:
        return InMemoryRefreshTokenStore()
    return RedisRefreshTokenStore(redis_client)


def _redis_client_from_env() -> Any | None:
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None or not redis_url.strip():
        return None
    from redis import Redis

    redis_factory = cast(Any, Redis)
    return redis_factory.from_url(redis_url, decode_responses=True)


def _object_storage_from_env() -> MinioObjectStorage:
    return MinioObjectStorage(
        endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        access_key=os.environ.get("MINIO_ACCESS_KEY", os.environ.get("MINIO_ROOT_USER", "deepdive")),
        secret_key=os.environ.get("MINIO_SECRET_KEY", os.environ.get("MINIO_ROOT_PASSWORD", "deepdive-secret")),
        bucket=os.environ.get("MINIO_BUCKET", DEFAULT_OBJECT_BUCKET),
        secure=_bool_env(os.environ.get("MINIO_SECURE", "false")),
    )


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _turnstile_config_from_env() -> TurnstileConfig:
    return TurnstileConfig(
        enabled=_bool_env(os.environ.get("TURNSTILE_ENABLED", "false")),
        secret_key=os.environ.get("TURNSTILE_SECRET_KEY", ""),
        allowed_hostnames=frozenset(_csv_env("TURNSTILE_ALLOWED_HOSTNAMES")),
        timeout_seconds=int(os.environ.get("TURNSTILE_VERIFY_TIMEOUT_SECONDS", "5")),
    )


def _github_oauth_config_from_env() -> GitHubOAuthConfig:
    return GitHubOAuthConfig(
        enabled=_bool_env(os.environ.get("GITHUB_OAUTH_ENABLED", "false")),
        client_id=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""),
        client_secret=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""),
        redirect_uri=os.environ.get("GITHUB_OAUTH_REDIRECT_URI", ""),
        frontend_redirect_uri=os.environ.get("GITHUB_OAUTH_FRONTEND_REDIRECT_URI", ""),
        state_ttl_seconds=int(os.environ.get("GITHUB_OAUTH_STATE_TTL_SECONDS", "600")),
        exchange_code_ttl_seconds=int(os.environ.get("GITHUB_OAUTH_EXCHANGE_CODE_TTL_SECONDS", "60")),
        allowed_email_domains=frozenset(_csv_env("GITHUB_OAUTH_ALLOWED_EMAIL_DOMAINS")),
    )


def _csv_env(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [item.strip().lower() for item in value.split(",") if item.strip()]


app = create_app_from_env()
