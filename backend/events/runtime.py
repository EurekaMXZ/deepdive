from __future__ import annotations

from collections.abc import AsyncIterable

from backend.events import EventEnvelope
from backend.events.kafka import (
    ConsumedKafkaMessage,
    EventConsumerRunner,
    EventHandler,
    EventPublisher,
    KafkaProducerClient,
    OutboxPublisher,
    consume_messages,
)
from backend.events.repositories import AsyncConnection, SqlOutboxRepository, SqlProcessedEventRepository


async def publish_outbox_once(
    *,
    connection: AsyncConnection,
    producer: KafkaProducerClient,
    limit: int,
) -> int:
    return await OutboxPublisher(
        SqlOutboxRepository(connection),
        EventPublisher(producer),
    ).publish_batch(limit=limit)


async def run_consumer_once(
    *,
    consumer: AsyncIterable[ConsumedKafkaMessage],
    connection: AsyncConnection | None = None,
    database=None,
    consumer_name: str,
    handler: EventHandler,
    dlq_producer: KafkaProducerClient,
    retry_producer: KafkaProducerClient | None = None,
    max_attempts: int = 3,
    max_messages: int,
    heartbeat_interval_seconds: float = 60.0,
) -> int:
    connection_or_database = database or connection
    if connection_or_database is None:
        raise ValueError("run_consumer_once requires connection or database")
    runner = EventConsumerRunner(
        consumer_name=consumer_name,
        processed_events=SqlProcessedEventRepository(connection_or_database),
        handler=handler,
        dlq_publisher=EventPublisher(dlq_producer),
        retry_publisher=EventPublisher(retry_producer) if retry_producer is not None else None,
        max_attempts=max_attempts,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    return await consume_messages(consumer, runner, max_messages=max_messages)


async def run_consumer_forever(
    *,
    consumer: AsyncIterable[ConsumedKafkaMessage],
    connection: AsyncConnection | None = None,
    database=None,
    consumer_name: str,
    handler: EventHandler,
    dlq_producer: KafkaProducerClient,
    retry_producer: KafkaProducerClient | None = None,
    max_attempts: int = 3,
    heartbeat_interval_seconds: float = 60.0,
) -> int:
    connection_or_database = database or connection
    if connection_or_database is None:
        raise ValueError("run_consumer_forever requires connection or database")
    runner = EventConsumerRunner(
        consumer_name=consumer_name,
        processed_events=SqlProcessedEventRepository(connection_or_database),
        handler=handler,
        dlq_publisher=EventPublisher(dlq_producer),
        retry_publisher=EventPublisher(retry_producer) if retry_producer is not None else None,
        max_attempts=max_attempts,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    return await consume_messages(
        consumer,
        runner,
        max_messages=None,
        continue_on_deferred=True,
        deferred_backoff_seconds=1.0,
    )
