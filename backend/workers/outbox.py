from __future__ import annotations

import os
from dataclasses import dataclass

from backend.config import load_dotenv_if_exists
from backend.db.runtime import create_database
from backend.events.kafka import AiokafkaEventProducer
from backend.events.runtime import publish_outbox_once
from backend.workers.asyncio_compat import run_async_worker
from backend.workers.looping import run_forever


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str
    kafka_bootstrap_servers: str
    batch_size: int = 100
    run_forever: bool = False
    idle_sleep_seconds: float = 1.0
    error_backoff_seconds: float = 5.0


def load_worker_settings() -> WorkerSettings:
    load_dotenv_if_exists()
    return WorkerSettings(
        database_url=os.environ["DATABASE_URL"],
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        batch_size=int(os.environ.get("OUTBOX_BATCH_SIZE", "100")),
        run_forever=_bool_env(
            os.environ.get("OUTBOX_RUN_FOREVER", os.environ.get("OUTBOX_WORKER_RUN_FOREVER", "true"))
        ),
        idle_sleep_seconds=float(os.environ.get("OUTBOX_IDLE_SLEEP_SECONDS", "1")),
        error_backoff_seconds=float(os.environ.get("OUTBOX_ERROR_BACKOFF_SECONDS", "5")),
    )


async def publish_once(settings: WorkerSettings) -> int:
    database = create_database(settings.database_url)
    producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        async with database.begin() as connection:
            return await publish_outbox_once(
                connection=connection,
                producer=producer,
                limit=settings.batch_size,
            )
    finally:
        await producer.stop()
        await database.dispose()


async def publish_forever(settings: WorkerSettings) -> None:
    database = create_database(settings.database_url)
    producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await producer.start()
    try:

        async def publish_batch() -> int:
            async with database.begin() as connection:
                return await publish_outbox_once(
                    connection=connection,
                    producer=producer,
                    limit=settings.batch_size,
                )

        await run_forever(
            publish_batch,
            idle_sleep_seconds=settings.idle_sleep_seconds,
            error_backoff_seconds=settings.error_backoff_seconds,
        )
    finally:
        await producer.stop()
        await database.dispose()


async def main_async() -> None:
    settings = load_worker_settings()
    if settings.run_forever:
        await publish_forever(settings)
        return
    await publish_once(settings)


def main() -> None:
    run_async_worker(main_async())


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
