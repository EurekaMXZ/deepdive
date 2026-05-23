from __future__ import annotations

from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
import os

from backend.api.live_stream import KafkaLiveStreamSubscriber, LiveStreamHub, live_stream_topic, unique_api_live_group_id
from backend.api.routes import api_exception_handler, router
from backend.api.services import InMemoryAnalysisService, PostgresAnalysisService
from backend.config import DEFAULT_CONFIG_VERSION, AppConfig, load_app_config_from_env, load_dotenv_if_exists
from backend.db.runtime import create_database, create_database_from_env
from backend.events.kafka import AiokafkaEventConsumer


def create_app() -> FastAPI:
    app = FastAPI(title="DeepDive Backend")
    app.state.analysis_service = InMemoryAnalysisService()
    app.state.live_stream_hub = LiveStreamHub()
    app.state.show_model_reasoning_summary = AppConfig.default().openai.show_reasoning_summary
    app.include_router(router)
    app.add_exception_handler(HTTPException, api_exception_handler)
    return app


def create_postgres_app(
    *,
    database_url: str | None = None,
    config: AppConfig | None = None,
    config_version: str = DEFAULT_CONFIG_VERSION,
) -> FastAPI:
    database = create_database(database_url) if database_url is not None else create_database_from_env()
    live_stream_hub = LiveStreamHub(queue_size=int(os.environ.get("API_LIVE_STREAM_CLIENT_QUEUE_SIZE", "1000")))
    kafka_bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    live_group_prefix = os.environ.get("API_LIVE_STREAM_GROUP_PREFIX", "deepdive-api-live")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        live_subscriber = None
        try:
            if kafka_bootstrap_servers:
                live_consumer = AiokafkaEventConsumer(
                    live_stream_topic(),
                    bootstrap_servers=kafka_bootstrap_servers,
                    group_id=unique_api_live_group_id(live_group_prefix),
                    enable_auto_commit=True,
                    auto_offset_reset="latest",
                )
                live_subscriber = KafkaLiveStreamSubscriber(live_consumer, live_stream_hub)
            if live_subscriber is not None:
                await live_subscriber.start()
            yield
        finally:
            if live_subscriber is not None:
                await live_subscriber.stop()
            await database.dispose()

    app = FastAPI(title="DeepDive Backend", lifespan=lifespan)
    effective_config = config or AppConfig.default()
    app.state.database = database
    app.state.live_stream_hub = live_stream_hub
    app.state.show_model_reasoning_summary = effective_config.openai.show_reasoning_summary
    app.state.analysis_service = PostgresAnalysisService(
        database,
        config=effective_config,
        config_version=config_version,
    )
    app.include_router(router)
    app.add_exception_handler(HTTPException, api_exception_handler)

    return app


def create_app_from_env() -> FastAPI:
    load_dotenv_if_exists()
    if "DATABASE_URL" in os.environ:
        return create_postgres_app(config=load_app_config_from_env())
    return create_app()


app = create_app_from_env()
