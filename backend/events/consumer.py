from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import Literal, Protocol
from uuid import UUID

from backend.events import EventEnvelope, EventType
from backend.events.messages import ConsumedKafkaMessage
from backend.events.publisher import EventPublisher


class ProcessedEventRepository(Protocol):
    async def is_processed(self, event_id: UUID, consumer_name: str) -> bool: ...

    async def mark_processed(self, event_id: UUID, consumer_name: str, claim_owner: str | None = None) -> bool: ...

    async def claim_processing(self, event_id: UUID, consumer_name: str) -> str | None: ...

    async def release_processing_claim(
        self, event_id: UUID, consumer_name: str, claim_owner: str | None = None
    ) -> None: ...

    async def renew_processing_claim(self, event_id: UUID, consumer_name: str, claim_owner: str) -> bool: ...


EventHandler = Callable[[EventEnvelope], Awaitable[None]]
RenewProcessingClaim = Callable[[UUID, str, str], Awaitable[bool]]
MessageHandleResult = Literal["handled", "skipped_processed", "deferred", "failed_requeued"]


class EventConsumerRunner:
    def __init__(
        self,
        *,
        consumer_name: str,
        processed_events: ProcessedEventRepository,
        handler: EventHandler,
        dlq_publisher: EventPublisher,
        retry_publisher: EventPublisher | None = None,
        max_attempts: int = 3,
        heartbeat_interval_seconds: float = 60.0,
    ) -> None:
        self._consumer_name = consumer_name
        self._processed_events = processed_events
        self._handler = handler
        self._dlq_publisher = dlq_publisher
        self._retry_publisher = retry_publisher
        self._max_attempts = max(1, max_attempts)
        self._heartbeat_interval_seconds = max(0.0, float(heartbeat_interval_seconds))

    async def handle_message(self, message: ConsumedKafkaMessage) -> MessageHandleResult:
        event = EventEnvelope.from_json(message.value.decode())
        claim_owner: str | None = None
        if await self._processed_events.is_processed(event.event_id, self._consumer_name):
            return "skipped_processed"
        claim_result = await self._processed_events.claim_processing(event.event_id, self._consumer_name)
        if claim_result:
            claim_owner = claim_result
        else:
            return "deferred"

        heartbeat_task = self._start_heartbeat(event_id=event.event_id, claim_owner=claim_owner)
        try:
            await self._handler(event)
        except asyncio.CancelledError:
            await self._stop_heartbeat(heartbeat_task)
            await self._processed_events.release_processing_claim(event.event_id, self._consumer_name, claim_owner)
            raise
        except Exception as exc:
            await self._stop_heartbeat(heartbeat_task)
            try:
                if self._retry_publisher is not None and event.attempt < self._max_attempts:
                    await self._retry_publisher.publish(event.with_attempt(event.attempt + 1))
                else:
                    await self._publish_dlq(event, exc)
            finally:
                await self._processed_events.release_processing_claim(event.event_id, self._consumer_name, claim_owner)
            return "failed_requeued"

        await self._stop_heartbeat(heartbeat_task)
        marked = await self._processed_events.mark_processed(event.event_id, self._consumer_name, claim_owner)
        if marked is False:
            raise RuntimeError(f"Event {event.event_id} processing claim was lost before mark_processed")
        return "handled"

    def _start_heartbeat(self, *, event_id: UUID, claim_owner: str | None) -> asyncio.Task[None] | None:
        if not claim_owner:
            return None
        return asyncio.create_task(
            self._heartbeat_claim(
                event_id=event_id,
                claim_owner=claim_owner,
                renew=self._processed_events.renew_processing_claim,
            )
        )

    async def _stop_heartbeat(self, task: asyncio.Task[None] | None) -> None:
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    async def _heartbeat_claim(self, *, event_id: UUID, claim_owner: str, renew: RenewProcessingClaim) -> None:
        while True:
            if self._heartbeat_interval_seconds > 0:
                await asyncio.sleep(self._heartbeat_interval_seconds)
            renewed = await renew(event_id, self._consumer_name, claim_owner)
            if not renewed:
                return
            if self._heartbeat_interval_seconds <= 0:
                return

    async def _publish_dlq(self, event: EventEnvelope, exc: Exception) -> None:
        dlq_event = EventEnvelope.new(
            event_type=EventType.EVENT_PROCESSING_FAILED,
            analysis_id=event.analysis_id,
            agent_id=event.agent_id,
            snapshot_id=event.snapshot_id,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload={
                "original_event_id": str(event.event_id),
                "original_event_type": event.event_type.value,
                "consumer_name": self._consumer_name,
                "attempt": event.attempt,
                "max_attempts": self._max_attempts,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        await self._dlq_publisher.publish(dlq_event, topic_override="deepdive.dlq")


async def consume_messages(
    consumer: AsyncIterable[ConsumedKafkaMessage],
    runner: EventConsumerRunner,
    *,
    max_messages: int | None = None,
    continue_on_deferred: bool = False,
    deferred_backoff_seconds: float = 1.0,
) -> int:
    consumed = 0
    async for message in consumer:
        result = await runner.handle_message(message)
        if result == "deferred":
            if not continue_on_deferred:
                break
            defer = getattr(consumer, "defer", None)
            if defer is not None:
                await defer(message)
            if deferred_backoff_seconds > 0:
                await asyncio.sleep(deferred_backoff_seconds)
            continue
        commit = getattr(consumer, "commit", None)
        if commit is not None:
            await commit()
        if result == "handled":
            consumed += 1
        if max_messages is not None and consumed >= max_messages:
            break
    return consumed
