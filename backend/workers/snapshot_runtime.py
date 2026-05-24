from __future__ import annotations

import os
from dataclasses import dataclass

from backend.config import SnapshotConfig, load_dotenv_if_exists
from backend.db.runtime import create_database
from backend.events.kafka import AiokafkaEventConsumer, AiokafkaEventProducer
from backend.events.runtime import run_consumer_forever, run_consumer_once
from backend.storage import DEFAULT_OBJECT_BUCKET, MinioObjectStorage
from backend.workers.asyncio_compat import run_async_worker
from backend.workers.snapshot import SnapshotCommandHandler


@dataclass(frozen=True)
class SnapshotWorkerSettings:
    database_url: str
    kafka_bootstrap_servers: str
    consumer_group: str = "deepdive-snapshot-worker"
    max_messages: int = 1
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "deepdive"
    minio_secret_key: str = "deepdive-secret"
    minio_bucket: str = DEFAULT_OBJECT_BUCKET
    minio_secure: bool = False
    git_timeout_seconds: int = 300
    max_file_bytes: int = 1_048_576
    max_git_bundle_bytes: int = 536_870_912
    run_forever: bool = False
    idle_sleep_seconds: float = 1.0
    error_backoff_seconds: float = 5.0
    max_attempts: int = 3
    event_heartbeat_interval_seconds: float = 60.0


def build_snapshot_command_topics() -> tuple[str, ...]:
    return ("deepdive.snapshot.commands",)


def load_snapshot_worker_settings() -> SnapshotWorkerSettings:
    load_dotenv_if_exists()
    return SnapshotWorkerSettings(
        database_url=os.environ["DATABASE_URL"],
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        consumer_group=os.environ.get("SNAPSHOT_WORKER_GROUP", "deepdive-snapshot-worker"),
        max_messages=int(os.environ.get("SNAPSHOT_WORKER_MAX_MESSAGES", "1")),
        minio_endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.environ.get("MINIO_ACCESS_KEY", os.environ.get("MINIO_ROOT_USER", "deepdive")),
        minio_secret_key=os.environ.get("MINIO_SECRET_KEY", os.environ.get("MINIO_ROOT_PASSWORD", "deepdive-secret")),
        minio_bucket=os.environ.get("MINIO_BUCKET", DEFAULT_OBJECT_BUCKET),
        minio_secure=_bool_env(os.environ.get("MINIO_SECURE", "false")),
        git_timeout_seconds=int(os.environ.get("SNAPSHOT_GIT_TIMEOUT_SECONDS", "300")),
        max_file_bytes=int(os.environ.get("SNAPSHOT_MAX_FILE_BYTES", "1048576")),
        max_git_bundle_bytes=int(os.environ.get("SNAPSHOT_MAX_GIT_BUNDLE_BYTES", "536870912")),
        run_forever=_bool_env(os.environ.get("SNAPSHOT_WORKER_RUN_FOREVER", "true")),
        idle_sleep_seconds=float(os.environ.get("SNAPSHOT_WORKER_IDLE_SLEEP_SECONDS", "1")),
        error_backoff_seconds=float(os.environ.get("SNAPSHOT_WORKER_ERROR_BACKOFF_SECONDS", "5")),
        max_attempts=int(os.environ.get("SNAPSHOT_WORKER_MAX_ATTEMPTS", os.environ.get("WORKER_MAX_ATTEMPTS", "3"))),
        event_heartbeat_interval_seconds=float(
            os.environ.get(
                "SNAPSHOT_WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS",
                os.environ.get("WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS", "60"),
            )
        ),
    )


async def consume_once(settings: SnapshotWorkerSettings) -> int:
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_snapshot_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    await consumer.start()
    await dlq_producer.start()
    try:
        return await run_consumer_once(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=SnapshotCommandHandler(
                database=database,
                storage=storage,
                snapshot_config=SnapshotConfig(
                    max_file_bytes=settings.max_file_bytes,
                    max_git_bundle_bytes=settings.max_git_bundle_bytes,
                ),
                git_timeout_seconds=settings.git_timeout_seconds,
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


async def consume_forever(settings: SnapshotWorkerSettings) -> int:
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_snapshot_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    await consumer.start()
    await dlq_producer.start()
    try:
        return await run_consumer_forever(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=SnapshotCommandHandler(
                database=database,
                storage=storage,
                snapshot_config=SnapshotConfig(
                    max_file_bytes=settings.max_file_bytes,
                    max_git_bundle_bytes=settings.max_git_bundle_bytes,
                ),
                git_timeout_seconds=settings.git_timeout_seconds,
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
    settings = load_snapshot_worker_settings()
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
