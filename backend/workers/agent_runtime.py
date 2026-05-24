from __future__ import annotations

import os
from dataclasses import dataclass

from backend.agent import AgentCommandHandler, ContextAssembler
from backend.agent.openai_runner import create_openai_responses_runner
from backend.agent.repository import PostgresAgentRepository
from backend.config import load_app_config_from_env, load_dotenv_if_exists
from backend.db.runtime import create_database
from backend.events.kafka import AiokafkaEventConsumer, AiokafkaEventProducer
from backend.events.runtime import run_consumer_forever, run_consumer_once
from backend.storage import DEFAULT_OBJECT_BUCKET, MinioObjectStorage
from backend.workers.asyncio_compat import run_async_worker


@dataclass(frozen=True)
class AgentWorkerSettings:
    database_url: str
    kafka_bootstrap_servers: str
    consumer_group: str = "deepdive-agent-worker"
    max_messages: int = 1
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_user_agent: str = "DeepDive/1.0"
    openai_transport: str = "http"
    openai_timeout_seconds: int = 300
    openai_total_timeout_seconds: float | None = None
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "deepdive"
    minio_secret_key: str = "deepdive-secret"
    minio_bucket: str = DEFAULT_OBJECT_BUCKET
    minio_secure: bool = False
    run_forever: bool = False
    idle_sleep_seconds: float = 1.0
    error_backoff_seconds: float = 5.0
    max_attempts: int = 3
    event_heartbeat_interval_seconds: float = 60.0


def build_agent_command_topics() -> tuple[str, ...]:
    return ("deepdive.agent.commands",)


def load_agent_worker_settings() -> AgentWorkerSettings:
    load_dotenv_if_exists()
    return AgentWorkerSettings(
        database_url=os.environ["DATABASE_URL"],
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        consumer_group=os.environ.get("AGENT_WORKER_GROUP", "deepdive-agent-worker"),
        max_messages=int(os.environ.get("AGENT_WORKER_MAX_MESSAGES", "1")),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_user_agent=os.environ.get("OPENAI_USER_AGENT", "DeepDive/1.0"),
        openai_transport=os.environ.get("OPENAI_TRANSPORT", "http"),
        openai_timeout_seconds=int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "300")),
        openai_total_timeout_seconds=_optional_float_env(os.environ.get("OPENAI_TOTAL_TIMEOUT_SECONDS")),
        minio_endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.environ.get("MINIO_ACCESS_KEY", os.environ.get("MINIO_ROOT_USER", "deepdive")),
        minio_secret_key=os.environ.get("MINIO_SECRET_KEY", os.environ.get("MINIO_ROOT_PASSWORD", "deepdive-secret")),
        minio_bucket=os.environ.get("MINIO_BUCKET", DEFAULT_OBJECT_BUCKET),
        minio_secure=_bool_env(os.environ.get("MINIO_SECURE", "false")),
        run_forever=_bool_env(os.environ.get("AGENT_WORKER_RUN_FOREVER", "true")),
        idle_sleep_seconds=float(os.environ.get("AGENT_WORKER_IDLE_SLEEP_SECONDS", "1")),
        error_backoff_seconds=float(os.environ.get("AGENT_WORKER_ERROR_BACKOFF_SECONDS", "5")),
        max_attempts=int(os.environ.get("AGENT_WORKER_MAX_ATTEMPTS", os.environ.get("WORKER_MAX_ATTEMPTS", "3"))),
        event_heartbeat_interval_seconds=float(
            os.environ.get(
                "AGENT_WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS",
                os.environ.get("WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS", "60"),
            )
        ),
    )


async def consume_once(settings: AgentWorkerSettings) -> int:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for agent worker")
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_agent_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await dlq_producer.start()
    try:
        repository = PostgresAgentRepository(database)
        handler = AgentCommandHandler(
            repository=repository,
            context_assembler=ContextAssembler(
                repository=repository,
                storage=MinioObjectStorage(
                    endpoint=settings.minio_endpoint,
                    access_key=settings.minio_access_key,
                    secret_key=settings.minio_secret_key,
                    bucket=settings.minio_bucket,
                    secure=settings.minio_secure,
                ),
            ),
            responses_runner=_openai_runner(settings),
            config=load_app_config_from_env(),
            model_retry_attempts=settings.max_attempts,
        )
        return await run_consumer_once(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=handler,
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


def _openai_runner(settings: AgentWorkerSettings):
    return create_openai_responses_runner(
        transport=settings.openai_transport,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        user_agent=settings.openai_user_agent,
        timeout_seconds=settings.openai_timeout_seconds,
        total_timeout_seconds=settings.openai_total_timeout_seconds,
    )


async def consume_forever(settings: AgentWorkerSettings) -> int:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for agent worker")
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_agent_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await dlq_producer.start()
    try:
        repository = PostgresAgentRepository(database)
        handler = AgentCommandHandler(
            repository=repository,
            context_assembler=ContextAssembler(
                repository=repository,
                storage=MinioObjectStorage(
                    endpoint=settings.minio_endpoint,
                    access_key=settings.minio_access_key,
                    secret_key=settings.minio_secret_key,
                    bucket=settings.minio_bucket,
                    secure=settings.minio_secure,
                ),
            ),
            responses_runner=_openai_runner(settings),
            config=load_app_config_from_env(),
            model_retry_attempts=settings.max_attempts,
        )
        return await run_consumer_forever(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=handler,
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
    settings = load_agent_worker_settings()
    if settings.run_forever:
        await consume_forever(settings)
        return
    await consume_once(settings)


def main() -> None:
    run_async_worker(main_async())


def _optional_float_env(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
