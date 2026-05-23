from __future__ import annotations

import asyncio
import unittest

from backend.events import EventEnvelope, EventType
from backend.events.kafka import ConsumedKafkaMessage
from backend.events.runtime import publish_outbox_once, run_consumer_forever, run_consumer_once
from backend.ids import new_uuid7
from tests.test_kafka_events import FakeEventHandler, FakeKafkaConsumer, FakeKafkaProducer, FakeProcessedEventRepository


class EventRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_outbox_once_wires_repository_and_publisher(self) -> None:
        event = EventEnvelope.new(event_type=EventType.ANALYSIS_REQUESTED, analysis_id=new_uuid7())
        connection = FakeOutboxConnection(event)
        producer = FakeKafkaProducer()

        published = await publish_outbox_once(connection=connection, producer=producer, limit=10)

        self.assertEqual(published, 1)
        self.assertEqual(len(producer.sent), 1)
        self.assertEqual(EventEnvelope.from_json(producer.sent[0].value.decode()), event)

    async def test_run_consumer_once_wires_consumer_processed_repo_and_handler(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        connection = FakeProcessedConnection()
        handler = AwaitingEventHandler()
        consumer = FakeKafkaConsumer(
            [
                ConsumedKafkaMessage(
                    topic="deepdive.domain.events",
                    key=str(event.analysis_id).encode(),
                    value=event.to_json().encode(),
                )
            ]
        )

        consumed = await run_consumer_once(
            consumer=consumer,
            connection=connection,
            consumer_name="snapshot-worker",
            handler=handler,
            dlq_producer=FakeKafkaProducer(),
            max_messages=1,
            heartbeat_interval_seconds=0,
        )

        self.assertEqual(consumed, 1)
        self.assertEqual(handler.handled, [event])
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("INSERT INTO event_processing_claims", executed_sql)
        self.assertIn("claim_owner", executed_sql)
        self.assertIn("INSERT INTO processed_events", executed_sql)
        self.assertIn("DELETE FROM event_processing_claims", executed_sql)
        self.assertEqual(connection.renewed_claims, [(event.event_id, "snapshot-worker")])

    async def test_run_consumer_once_wires_retry_publisher_and_max_attempts(self) -> None:
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        connection = FakeProcessedConnection()
        retry_producer = FakeKafkaProducer()
        dlq_producer = FakeKafkaProducer()
        consumer = FakeKafkaConsumer(
            [
                ConsumedKafkaMessage(
                    topic="deepdive.domain.events",
                    key=str(event.analysis_id).encode(),
                    value=event.to_json().encode(),
                )
            ]
        )

        consumed = await run_consumer_once(
            consumer=consumer,
            connection=connection,
            consumer_name="agent-worker",
            handler=FakeEventHandler(fail=True),
            dlq_producer=dlq_producer,
            retry_producer=retry_producer,
            max_attempts=4,
            max_messages=1,
        )

        self.assertEqual(consumed, 0)
        self.assertEqual(len(dlq_producer.sent), 0)
        self.assertEqual(len(retry_producer.sent), 1)
        retried = EventEnvelope.from_json(retry_producer.sent[0].value.decode())
        self.assertEqual(retried.event_id, event.event_id)
        self.assertEqual(retried.attempt, 2)

    async def test_run_consumer_forever_consumes_until_consumer_is_exhausted(self) -> None:
        first = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())
        second = EventEnvelope.new(event_type=EventType.TOOL_CALL_COMPLETED, analysis_id=first.analysis_id)
        connection = FakeProcessedConnection()
        handler = AwaitingEventHandler()
        consumer = FakeKafkaConsumer(
            [
                ConsumedKafkaMessage(topic="deepdive.agent.commands", key=b"k1", value=first.to_json().encode()),
                ConsumedKafkaMessage(topic="deepdive.agent.commands", key=b"k2", value=second.to_json().encode()),
            ]
        )

        consumed = await run_consumer_forever(
            consumer=consumer,
            connection=connection,
            consumer_name="agent-worker",
            handler=handler,
            dlq_producer=FakeKafkaProducer(),
            heartbeat_interval_seconds=0,
        )

        self.assertEqual(consumed, 2)
        self.assertEqual(handler.handled, [first, second])


class FakeOutboxConnection:
    def __init__(self, event: EventEnvelope) -> None:
        self.event = event
        self.outbox_id = new_uuid7()
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if "SELECT id, payload_json" in statement_text:
            return FakeResult([{"id": self.outbox_id, "payload_json": self.event.to_json()}])
        return FakeResult([])


class FakeProcessedConnection:
    def __init__(self) -> None:
        self.executed = []
        self.renewed_claims = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if "INSERT INTO processed_events" in statement_text or "INSERT INTO event_processing_claims" in statement_text:
            return FakeResult([{"event_id": params["event_id"]}])
        if "UPDATE event_processing_claims" in statement_text:
            self.renewed_claims.append((params["event_id"], params["consumer_name"]))
            return FakeResult([{"event_id": params["event_id"]}])
        return FakeResult([])

    async def scalar(self, statement, params=None):
        self.executed.append((statement, params or {}))
        return False


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


class AwaitingEventHandler:
    def __init__(self) -> None:
        self.handled: list[EventEnvelope] = []

    async def __call__(self, event: EventEnvelope) -> None:
        await asyncio.sleep(0)
        self.handled.append(event)


if __name__ == "__main__":
    unittest.main()
