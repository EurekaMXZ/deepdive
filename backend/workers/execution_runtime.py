from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.cache import LocalSourceCache
from backend.config import load_app_config_from_env, load_dotenv_if_exists
from backend.db.runtime import create_database
from backend.documents import DocumentService
from backend.documents.repository import PostgresDocumentRepository
from backend.events.kafka import AiokafkaEventConsumer, AiokafkaEventProducer
from backend.events.runtime import run_consumer_forever, run_consumer_once
from backend.execution import PermissionEngine, SourceToolExecutor
from backend.execution.repository import PostgresSnapshotToolRepository, PostgresToolCallRepository
from backend.storage import DEFAULT_OBJECT_BUCKET, MinioObjectStorage
from backend.workers.asyncio_compat import run_async_worker
from backend.workers.execution import ExecutionCommandHandler


@dataclass(frozen=True)
class ExecutionWorkerSettings:
    database_url: str
    kafka_bootstrap_servers: str
    consumer_group: str = "deepdive-execution-worker"
    max_messages: int = 1
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "deepdive"
    minio_secret_key: str = "deepdive-secret"
    minio_bucket: str = DEFAULT_OBJECT_BUCKET
    minio_secure: bool = False
    cache_root_dir: str = "/cache/deepdive"
    run_forever: bool = False
    idle_sleep_seconds: float = 1.0
    error_backoff_seconds: float = 5.0
    max_attempts: int = 3
    event_heartbeat_interval_seconds: float = 60.0
    tool_heartbeat_interval_seconds: float = 60.0
    tavily_api_key: str = ""

    def __repr__(self) -> str:
        values = dict(self.__dict__)
        if values.get("tavily_api_key"):
            values["tavily_api_key"] = "***"
        args = ", ".join(f"{key}={value!r}" for key, value in values.items())
        return f"{type(self).__name__}({args})"


def build_execution_command_topics() -> tuple[str, ...]:
    return ("deepdive.execution.commands",)


def load_execution_worker_settings() -> ExecutionWorkerSettings:
    load_dotenv_if_exists()
    app_config = load_app_config_from_env()
    return ExecutionWorkerSettings(
        database_url=os.environ["DATABASE_URL"],
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        consumer_group=os.environ.get("EXECUTION_WORKER_GROUP", "deepdive-execution-worker"),
        max_messages=int(os.environ.get("EXECUTION_WORKER_MAX_MESSAGES", "1")),
        minio_endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.environ.get("MINIO_ACCESS_KEY", os.environ.get("MINIO_ROOT_USER", "deepdive")),
        minio_secret_key=os.environ.get("MINIO_SECRET_KEY", os.environ.get("MINIO_ROOT_PASSWORD", "deepdive-secret")),
        minio_bucket=os.environ.get("MINIO_BUCKET", DEFAULT_OBJECT_BUCKET),
        minio_secure=_bool_env(os.environ.get("MINIO_SECURE", "false")),
        cache_root_dir=app_config.cache.root_dir,
        run_forever=_bool_env(os.environ.get("EXECUTION_WORKER_RUN_FOREVER", "true")),
        idle_sleep_seconds=float(os.environ.get("EXECUTION_WORKER_IDLE_SLEEP_SECONDS", "1")),
        error_backoff_seconds=float(os.environ.get("EXECUTION_WORKER_ERROR_BACKOFF_SECONDS", "5")),
        max_attempts=int(os.environ.get("EXECUTION_WORKER_MAX_ATTEMPTS", os.environ.get("WORKER_MAX_ATTEMPTS", "3"))),
        event_heartbeat_interval_seconds=float(
            os.environ.get(
                "EXECUTION_WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS",
                os.environ.get("WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS", "60"),
            )
        ),
        tool_heartbeat_interval_seconds=float(os.environ.get("EXECUTION_TOOL_HEARTBEAT_INTERVAL_SECONDS", "60")),
        tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
    )


async def consume_once(settings: ExecutionWorkerSettings) -> int:
    app_config = load_app_config_from_env()
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_execution_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await dlq_producer.start()
    try:
        snapshot_repository = PostgresSnapshotToolRepository(database)
        tool_calls = PostgresToolCallRepository(database)
        cache = LocalSourceCache(root_dir=Path(settings.cache_root_dir))
        cache.cleanup(app_config.cache)
        storage = MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
        executor = SourceToolExecutor(
            repository=snapshot_repository,
            storage=storage,
            cache=cache,
            permission_engine=PermissionEngine(),
            read_config=app_config.tools.read_file,
            search_config=app_config.tools.search_text,
            web_search_config=app_config.tools.web_search,
            cache_config=app_config.cache,
            tavily_api_key=settings.tavily_api_key or os.environ.get("TAVILY_API_KEY", ""),
            document_service=DocumentService(repository=PostgresDocumentRepository(database), storage=storage),
        )
        return await run_consumer_once(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=ExecutionCommandHandler(
                tool_calls=tool_calls,
                executor=executor,
                heartbeat_interval_seconds=settings.tool_heartbeat_interval_seconds,
            ),
            dlq_producer=dlq_producer,
            retry_producer=dlq_producer,
            max_attempts=settings.max_attempts,
            max_messages=settings.max_messages,
            heartbeat_interval_seconds=settings.event_heartbeat_interval_seconds,
        )
    finally:
        await consumer.stop()
        await dlq_producer.stop()
        await database.dispose()


async def consume_forever(settings: ExecutionWorkerSettings) -> int:
    app_config = load_app_config_from_env()
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_execution_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await dlq_producer.start()
    try:
        snapshot_repository = PostgresSnapshotToolRepository(database)
        tool_calls = PostgresToolCallRepository(database)
        cache = LocalSourceCache(root_dir=Path(settings.cache_root_dir))
        cache.cleanup(app_config.cache)
        storage = MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
        executor = SourceToolExecutor(
            repository=snapshot_repository,
            storage=storage,
            cache=cache,
            permission_engine=PermissionEngine(),
            read_config=app_config.tools.read_file,
            search_config=app_config.tools.search_text,
            web_search_config=app_config.tools.web_search,
            cache_config=app_config.cache,
            tavily_api_key=settings.tavily_api_key or os.environ.get("TAVILY_API_KEY", ""),
            document_service=DocumentService(repository=PostgresDocumentRepository(database), storage=storage),
        )
        return await run_consumer_forever(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=ExecutionCommandHandler(
                tool_calls=tool_calls,
                executor=executor,
                heartbeat_interval_seconds=settings.tool_heartbeat_interval_seconds,
            ),
            dlq_producer=dlq_producer,
            retry_producer=dlq_producer,
            max_attempts=settings.max_attempts,
            heartbeat_interval_seconds=settings.event_heartbeat_interval_seconds,
        )
    finally:
        await consumer.stop()
        await dlq_producer.stop()
        await database.dispose()


async def main_async() -> None:
    settings = load_execution_worker_settings()
    if settings.run_forever:
        await consume_forever(settings)
        return
    await consume_once(settings)


def main() -> None:
    run_async_worker(main_async())


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
