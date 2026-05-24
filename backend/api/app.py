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
from backend.config import DEFAULT_CONFIG_VERSION, AppConfig, load_app_config_from_env, load_dotenv_if_exists
from backend.db.runtime import create_database, create_database_from_env
from backend.document import DocumentRepository, DocumentService
from backend.document.repository import PostgresDocumentRepository
from backend.storage import DEFAULT_OBJECT_BUCKET, InMemoryObjectStorage, MinioObjectStorage


def create_app() -> FastAPI:
    app = FastAPI(title="DeepDive Backend")
    app.state.analysis_service = InMemoryAnalysisService()
    app.state.auth_service = InMemoryAuthService(jwt_secret=_jwt_secret(), refresh_token_store=_refresh_token_store())
    app.state.document_service = DocumentService(repository=DocumentRepository(), storage=InMemoryObjectStorage())
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
    _install_routes(app)

    return app


def create_app_from_env() -> FastAPI:
    load_dotenv_if_exists()
    if "DATABASE_URL" in os.environ:
        return create_postgres_app(config=load_app_config_from_env())
    return create_app()


def _install_routes(app: FastAPI) -> None:
    app.include_router(auth_router)
    app.include_router(user_router)
    app.include_router(role_router)
    app.include_router(router)
    app.include_router(document_router)
    app.add_exception_handler(HTTPException, cast(ExceptionHandler, api_exception_handler))


def _jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "deepdive-dev-secret")


def _refresh_token_store() -> RefreshTokenStore:
    redis_url = os.environ.get("REDIS_URL")
    if redis_url is None or not redis_url.strip():
        return InMemoryRefreshTokenStore()

    from redis import Redis

    redis_factory = cast(Any, Redis)
    return RedisRefreshTokenStore(redis_factory.from_url(redis_url, decode_responses=True))


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


app = create_app_from_env()
