from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from uuid import UUID

from backend.events import EventEnvelope, EventType
from backend.events.kafka import (
    AiokafkaEventConsumer,
    ConsumedKafkaMessage,
    EventConsumerRunner,
    EventPublisher,
    OutboxEvent,
    OutboxPublisher,
    consume_messages,
)
from backend.ids import new_uuid7


class KafkaEventInfrastructureTest(unittest.IsolatedAsyncioTestCase):
    async def test_event_publisher_sends_topic_key_and_json_bytes(self) -> None:
        client = FakeKafkaProducer()
        publisher = EventPublisher(client)
        analysis_id = new_uuid7()
        event = EventEnvelope.new(
            event_type=EventType.ANALYSIS_REQUESTED,
            analysis_id=analysis_id,
            payload={"repository_url": "https://github.com/example/project.git"},
        )

        await publisher.publish(event)

        self.assertEqual(len(client.sent), 1)
        sent = client.sent[0]
        self.assertEqual(sent.topic, "deepdive.analysis.commands")
        self.assertEqual(sent.key, str(analysis_id).encode())
        self.assertEqual(EventEnvelope.from_json(sent.value.decode()), event)

    async def test_aiokafka_consumer_starts_from_earliest_when_group_has_no_offset(self) -> None:
        consumer = AiokafkaEventConsumer(
            "deepdive.snapshot.commands",
            bootstrap_servers="localhost:9092",
            group_id="snapshot-worker",
        )

        try:
            self.assertEqual(consumer._consumer._auto_offset_reset, "earliest")
        finally:
            await consumer.stop()

    async def test_outbox_publisher_marks_rows_only_after_publish(self) -> None:
        event = EventEnvelope.new(event_type=EventType.ANALYSIS_REQUESTED, analysis_id=new_uuid7())
        outbox = FakeOutboxRepository([OutboxEvent(id=new_uuid7(), event=event)])
        client = FakeKafkaProducer()

        published = await OutboxPublisher(outbox, EventPublisher(client)).publish_batch(limit=10)

        self.assertEqual(published, 1)
        self.assertEqual(outbox.marked_published, [outbox.rows[0].id])
        self.assertEqual(len(client.sent), 1)

    async def test_outbox_publisher_does_not_mark_failed_publish(self) -> None:
        event = EventEnvelope.new(event_type=EventType.ANALYSIS_REQUESTED, analysis_id=new_uuid7())
        outbox = FakeOutboxRepository([OutboxEvent(id=new_uuid7(), event=event)])
        client = FakeKafkaProducer(fail=True)

        with self.assertRaises(RuntimeError):
            await OutboxPublisher(outbox, EventPublisher(client)).publish_batch(limit=10)

        self.assertEqual(outbox.marked_published, [])

    async def test_consumer_runner_skips_duplicate_events(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository(already_processed={event.event_id})
        handler = FakeEventHandler()
        dlq = EventPublisher(FakeKafkaProducer())
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=handler,
            dlq_publisher=dlq,
        )

        result = await runner.handle_message(_message(event))

        self.assertEqual(result, "skipped_processed")
        self.assertEqual(handler.handled, [])
        self.assertEqual(idempotency.marked, [])

    async def test_consumer_runner_marks_processed_after_success(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository()
        handler = FakeEventHandler()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=handler,
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        result = await runner.handle_message(_message(event))

        self.assertEqual(result, "handled")
        self.assertEqual(handler.handled, [event])
        self.assertEqual(idempotency.claimed_events, [(event.event_id, "agent-worker")])
        self.assertEqual(idempotency.marked, [(event.event_id, "agent-worker", idempotency.claim_owner)])

    async def test_consumer_runner_requeues_when_processing_owner_was_lost_before_mark_processed(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository(mark_processed_result=False)
        handler = FakeEventHandler()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=handler,
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        with self.assertRaisesRegex(RuntimeError, "processing claim"):
            await runner.handle_message(_message(event))

        self.assertEqual(handler.handled, [event])

    async def test_consumer_runner_renews_processing_claim_while_handler_runs(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=AwaitingEventHandler(),
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
            heartbeat_interval_seconds=0,
        )

        result = await runner.handle_message(_message(event))

        self.assertEqual(result, "handled")
        self.assertGreaterEqual(len(idempotency.renewed), 1)
        self.assertEqual(idempotency.renewed[0], (event.event_id, "agent-worker", idempotency.claim_owner))

    async def test_consumer_runner_commits_kafka_offset_after_success(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        consumer = FakeKafkaConsumer([_message(event)])
        handler = FakeEventHandler()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=FakeProcessedEventRepository(),
            handler=handler,
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        consumed = await consume_messages(consumer, runner, max_messages=1)

        self.assertEqual(consumed, 1)
        self.assertEqual(consumer.commits, 1)

    async def test_consumer_runner_skips_when_event_claim_is_not_acquired(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository(claimed=False)
        handler = FakeEventHandler()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=handler,
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        result = await runner.handle_message(_message(event))

        self.assertEqual(result, "deferred")
        self.assertEqual(handler.handled, [])
        self.assertEqual(idempotency.claimed_events, [(event.event_id, "agent-worker")])
        self.assertEqual(idempotency.marked, [])

    async def test_consume_messages_does_not_commit_deferred_claim(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        consumer = FakeKafkaConsumer([_message(event)])
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=FakeProcessedEventRepository(claimed=False),
            handler=FakeEventHandler(),
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        consumed = await consume_messages(consumer, runner, max_messages=1)

        self.assertEqual(consumed, 0)
        self.assertEqual(consumer.commits, 0)

    async def test_consume_messages_forever_seeks_deferred_claim_and_retries(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        consumer = FakeKafkaConsumer([_message(event)])
        idempotency = FakeProcessedEventRepository(claim_sequence=[False, True])
        handler = FakeEventHandler()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=handler,
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        consumed = await consume_messages(consumer, runner, max_messages=1, continue_on_deferred=True, deferred_backoff_seconds=0)

        self.assertEqual(consumed, 1)
        self.assertEqual(handler.handled, [event])
        self.assertEqual(consumer.commits, 1)
        self.assertEqual(consumer.deferred, [_message(event)])

    async def test_consumer_runner_sends_failed_events_to_dlq_without_marking_processed(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository()
        handler = FakeEventHandler(fail=True)
        dlq_client = FakeKafkaProducer()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=handler,
            dlq_publisher=EventPublisher(dlq_client),
        )

        result = await runner.handle_message(_message(event))

        self.assertEqual(result, "failed_requeued")
        self.assertEqual(idempotency.marked, [])
        self.assertEqual(len(dlq_client.sent), 1)
        self.assertEqual(dlq_client.sent[0].topic, "deepdive.dlq")
        dlq_event = EventEnvelope.from_json(dlq_client.sent[0].value.decode())
        self.assertEqual(dlq_event.payload["original_event_id"], str(event.event_id))
        self.assertEqual(dlq_event.payload["consumer_name"], "agent-worker")
        self.assertEqual(idempotency.released, [(event.event_id, "agent-worker", idempotency.claim_owner)])

    async def test_consumer_runner_requeues_failed_event_until_max_attempts(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        retry_client = FakeKafkaProducer()
        dlq_client = FakeKafkaProducer()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=FakeProcessedEventRepository(),
            handler=FakeEventHandler(fail=True),
            dlq_publisher=EventPublisher(dlq_client),
            retry_publisher=EventPublisher(retry_client),
            max_attempts=3,
        )

        result = await runner.handle_message(_message(event))

        self.assertEqual(result, "failed_requeued")
        self.assertEqual(len(dlq_client.sent), 0)
        self.assertEqual(len(retry_client.sent), 1)
        retried_event = EventEnvelope.from_json(retry_client.sent[0].value.decode())
        self.assertEqual(retried_event.event_id, event.event_id)
        self.assertEqual(retried_event.attempt, 2)

    async def test_consumer_runner_sends_to_dlq_after_max_attempts(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        event = event.with_attempt(3)
        retry_client = FakeKafkaProducer()
        dlq_client = FakeKafkaProducer()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=FakeProcessedEventRepository(),
            handler=FakeEventHandler(fail=True),
            dlq_publisher=EventPublisher(dlq_client),
            retry_publisher=EventPublisher(retry_client),
            max_attempts=3,
        )

        result = await runner.handle_message(_message(event))

        self.assertEqual(result, "failed_requeued")
        self.assertEqual(len(retry_client.sent), 0)
        self.assertEqual(len(dlq_client.sent), 1)
        dlq_event = EventEnvelope.from_json(dlq_client.sent[0].value.decode())
        self.assertEqual(dlq_event.payload["attempt"], 3)
        self.assertEqual(dlq_event.payload["max_attempts"], 3)

    async def test_consumer_runner_releases_processing_claim_when_retry_publish_fails(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=FakeEventHandler(fail=True),
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
            retry_publisher=EventPublisher(FakeKafkaProducer(fail=True)),
            max_attempts=3,
        )

        with self.assertRaises(RuntimeError):
            await runner.handle_message(_message(event))

        self.assertEqual(idempotency.released, [(event.event_id, "agent-worker", idempotency.claim_owner)])

    async def test_consumer_runner_releases_processing_claim_when_cancelled(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        idempotency = FakeProcessedEventRepository()
        handler = FakeEventHandler(cancel=True)
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=idempotency,
            handler=handler,
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        with self.assertRaises(asyncio.CancelledError):
            await runner.handle_message(_message(event))

        self.assertEqual(idempotency.marked, [])
        self.assertEqual(idempotency.released, [(event.event_id, "agent-worker", idempotency.claim_owner)])

    async def test_consume_messages_stops_at_max_messages(self) -> None:
        events = [
            EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7()),
            EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7()),
        ]
        consumer = FakeKafkaConsumer([_message(event) for event in events])
        handler = FakeEventHandler()
        runner = EventConsumerRunner(
            consumer_name="agent-worker",
            processed_events=FakeProcessedEventRepository(),
            handler=handler,
            dlq_publisher=EventPublisher(FakeKafkaProducer()),
        )

        consumed = await consume_messages(consumer, runner, max_messages=1)

        self.assertEqual(consumed, 1)
        self.assertEqual(handler.handled, [events[0]])


@dataclass
class SentMessage:
    topic: str
    key: bytes
    value: bytes


class FakeKafkaProducer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[SentMessage] = []

    async def send_and_wait(self, topic: str, *, key: bytes, value: bytes) -> None:
        if self.fail:
            raise RuntimeError("publish failed")
        self.sent.append(SentMessage(topic=topic, key=key, value=value))


class FakeOutboxRepository:
    def __init__(self, rows: list[OutboxEvent]) -> None:
        self.rows = rows
        self.marked_published: list[UUID] = []

    async def fetch_unpublished(self, *, limit: int) -> list[OutboxEvent]:
        return self.rows[:limit]

    async def mark_published(self, outbox_id: UUID) -> None:
        self.marked_published.append(outbox_id)


class FakeProcessedEventRepository:
    def __init__(
        self,
        *,
        already_processed: set[UUID] | None = None,
        claimed: bool = True,
        claim_sequence: list[bool] | None = None,
        mark_processed_result: bool = True,
    ) -> None:
        self.already_processed = already_processed or set()
        self.claimed = claimed
        self.claim_sequence = list(claim_sequence or [])
        self.mark_processed_result = mark_processed_result
        self.claimed_events: list[tuple[UUID, str]] = []
        self.marked: list[tuple[UUID, str, str | None]] = []
        self.released: list[tuple[UUID, str, str | None]] = []
        self.renewed: list[tuple[UUID, str, str]] = []
        self.claim_owner = "test-event-claim-owner"

    async def is_processed(self, event_id: UUID, consumer_name: str) -> bool:
        del consumer_name
        return event_id in self.already_processed

    async def mark_processed(self, event_id: UUID, consumer_name: str, claim_owner: str | None = None) -> bool:
        self.marked.append((event_id, consumer_name, claim_owner))
        return self.mark_processed_result

    async def claim_processing(self, event_id: UUID, consumer_name: str) -> str | None:
        if event_id in self.already_processed:
            return None
        self.claimed_events.append((event_id, consumer_name))
        if self.claim_sequence:
            return self.claim_owner if self.claim_sequence.pop(0) else None
        return self.claim_owner if self.claimed else None

    async def renew_processing_claim(self, event_id: UUID, consumer_name: str, claim_owner: str) -> bool:
        self.renewed.append((event_id, consumer_name, claim_owner))
        return claim_owner == self.claim_owner

    async def release_processing_claim(self, event_id: UUID, consumer_name: str, claim_owner: str | None = None) -> None:
        if (event_id, consumer_name) in self.claimed_events:
            self.claimed_events.remove((event_id, consumer_name))
        self.released.append((event_id, consumer_name, claim_owner))


class FakeEventHandler:
    def __init__(self, *, fail: bool = False, cancel: bool = False) -> None:
        self.fail = fail
        self.cancel = cancel
        self.handled: list[EventEnvelope] = []

    async def __call__(self, event: EventEnvelope) -> None:
        if self.cancel:
            raise asyncio.CancelledError()
        if self.fail:
            raise RuntimeError("handler failed")
        self.handled.append(event)


class AwaitingEventHandler:
    def __init__(self) -> None:
        self.handled: list[EventEnvelope] = []

    async def __call__(self, event: EventEnvelope) -> None:
        await asyncio.sleep(0)
        self.handled.append(event)


class FakeKafkaConsumer:
    def __init__(self, messages: list[ConsumedKafkaMessage]) -> None:
        self._messages = messages
        self._index = 0
        self.commits = 0
        self.deferred: list[ConsumedKafkaMessage] = []

    def __aiter__(self) -> "FakeKafkaConsumer":
        return self

    async def __anext__(self) -> ConsumedKafkaMessage:
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        message = self._messages[self._index]
        self._index += 1
        return message

    async def commit(self) -> None:
        self.commits += 1

    async def defer(self, message: ConsumedKafkaMessage) -> None:
        self.deferred.append(message)
        self._index = max(0, self._index - 1)


def _message(event: EventEnvelope) -> ConsumedKafkaMessage:
    return ConsumedKafkaMessage(
        topic="deepdive.domain.events",
        key=b"key",
        value=event.to_json().encode(),
    )


if __name__ == "__main__":
    unittest.main()
