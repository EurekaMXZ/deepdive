from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException
from starlette.types import ExceptionHandler

from backend.api.routes import api_exception_handler, router
from backend.api.services import InMemoryAnalysisService, PostgresAnalysisService
from backend.config import DEFAULT_CONFIG_VERSION, AppConfig, load_app_config_from_env, load_dotenv_if_exists
from backend.db.runtime import create_database, create_database_from_env


def create_app() -> FastAPI:
    app = FastAPI(title="DeepDive Backend")
    app.state.analysis_service = InMemoryAnalysisService()
    app.include_router(router)
    app.add_exception_handler(HTTPException, cast(ExceptionHandler, api_exception_handler))
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
    app.include_router(router)
    app.add_exception_handler(HTTPException, cast(ExceptionHandler, api_exception_handler))

    return app


def create_app_from_env() -> FastAPI:
    load_dotenv_if_exists()
    if "DATABASE_URL" in os.environ:
        return create_postgres_app(config=load_app_config_from_env())
    return create_app()


app = create_app_from_env()
