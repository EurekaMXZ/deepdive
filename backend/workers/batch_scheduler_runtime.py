from __future__ import annotations

import os
from dataclasses import dataclass

from backend.config import load_dotenv_if_exists
from backend.db.connections import AsyncConnectionProvider
from backend.db.runtime import create_database
from backend.events import EventEnvelope
from backend.events.kafka import AiokafkaEventConsumer, AiokafkaEventProducer
from backend.events.runtime import run_consumer_forever, run_consumer_once
from backend.workers.asyncio_compat import run_async_worker
from backend.workers.batch_scheduler import AnalysisBatchSchedulerHandler


@dataclass(frozen=True)
class AnalysisBatchSchedulerWorkerSettings:
    database_url: str
    kafka_bootstrap_servers: str
    consumer_group: str = "deepdive-analysis-batch-scheduler-worker"
    max_messages: int = 1
    run_forever: bool = False
    idle_sleep_seconds: float = 1.0
    error_backoff_seconds: float = 5.0
    max_attempts: int = 3
    event_heartbeat_interval_seconds: float = 60.0


def build_analysis_batch_scheduler_command_topics() -> tuple[str, ...]:
    return ("deepdive.analysis-batch.commands",)


def load_analysis_batch_scheduler_worker_settings() -> AnalysisBatchSchedulerWorkerSettings:
    load_dotenv_if_exists()
    return AnalysisBatchSchedulerWorkerSettings(
        database_url=os.environ["DATABASE_URL"],
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        consumer_group=os.environ.get(
            "ANALYSIS_BATCH_SCHEDULER_WORKER_GROUP",
            "deepdive-analysis-batch-scheduler-worker",
        ),
        max_messages=int(os.environ.get("ANALYSIS_BATCH_SCHEDULER_WORKER_MAX_MESSAGES", "1")),
        run_forever=_bool_env(os.environ.get("ANALYSIS_BATCH_SCHEDULER_WORKER_RUN_FOREVER", "true")),
        idle_sleep_seconds=float(os.environ.get("ANALYSIS_BATCH_SCHEDULER_WORKER_IDLE_SLEEP_SECONDS", "1")),
        error_backoff_seconds=float(os.environ.get("ANALYSIS_BATCH_SCHEDULER_WORKER_ERROR_BACKOFF_SECONDS", "5")),
        max_attempts=int(
            os.environ.get(
                "ANALYSIS_BATCH_SCHEDULER_WORKER_MAX_ATTEMPTS",
                os.environ.get("WORKER_MAX_ATTEMPTS", "3"),
            )
        ),
        event_heartbeat_interval_seconds=float(
            os.environ.get(
                "ANALYSIS_BATCH_SCHEDULER_WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS",
                os.environ.get("WORKER_EVENT_HEARTBEAT_INTERVAL_SECONDS", "60"),
            )
        ),
    )


async def consume_once(settings: AnalysisBatchSchedulerWorkerSettings) -> int:
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_analysis_batch_scheduler_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await dlq_producer.start()
    try:
        return await run_consumer_once(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=_AnalysisBatchSchedulerHandlerFactory(database),
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


async def consume_forever(settings: AnalysisBatchSchedulerWorkerSettings) -> int:
    database = create_database(settings.database_url)
    consumer = AiokafkaEventConsumer(
        *build_analysis_batch_scheduler_command_topics(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
    )
    dlq_producer = AiokafkaEventProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await dlq_producer.start()
    try:
        return await run_consumer_forever(
            consumer=consumer,
            database=database,
            consumer_name=settings.consumer_group,
            handler=_AnalysisBatchSchedulerHandlerFactory(database),
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
    settings = load_analysis_batch_scheduler_worker_settings()
    if settings.run_forever:
        await consume_forever(settings)
        return
    await consume_once(settings)


def main() -> None:
    run_async_worker(main_async())


class _AnalysisBatchSchedulerHandlerFactory:
    def __init__(self, database: AsyncConnectionProvider) -> None:
        self._database = database

    async def __call__(self, event: EventEnvelope) -> None:
        async with self._database.begin() as connection:
            await AnalysisBatchSchedulerHandler(connection)(event)


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
