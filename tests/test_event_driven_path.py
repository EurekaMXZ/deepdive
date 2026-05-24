from __future__ import annotations

import unittest

from backend.events import EventEnvelope, EventType
from backend.events.kafka import ConsumedKafkaMessage
from backend.events.runtime import publish_outbox_once, run_consumer_once
from backend.ids import new_uuid7
from backend.workers.analysis import AnalysisCommandHandler

from tests.test_kafka_events import FakeKafkaProducer


class EventDrivenPathTest(unittest.IsolatedAsyncioTestCase):
    async def test_outbox_publishes_analysis_requested_then_worker_requests_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        requested = EventEnvelope.new(
            event_type=EventType.ANALYSIS_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload={
                "repository_url": "https://github.com/example/project.git",
                "requested_ref": "main",
                "config_snapshot_id": str(new_uuid7()),
            },
        )
        connection = FakePathConnection(outbox_event=requested, update_rows=[{"id": analysis_id}])
        producer = FakeKafkaProducer()

        published = await publish_outbox_once(connection=connection, producer=producer, limit=10)

        self.assertEqual(published, 1)
        self.assertEqual(len(producer.sent), 1)
        self.assertEqual(producer.sent[0].topic, "deepdive.analysis.commands")

        consumed = await run_consumer_once(
            consumer=SingleMessageConsumer(
                ConsumedKafkaMessage(
                    topic=producer.sent[0].topic,
                    key=producer.sent[0].key,
                    value=producer.sent[0].value,
                )
            ),
            connection=connection,
            consumer_name="deepdive-analysis-worker",
            handler=AnalysisCommandHandler(connection),
            dlq_producer=FakeKafkaProducer(),
            max_messages=1,
        )

        self.assertEqual(consumed, 1)
        self.assertTrue(connection.marked_outbox_published)
        self.assertEqual(connection.processed_events, [(requested.event_id, "deepdive-analysis-worker")])
        emitted_events = [
            EventEnvelope.from_json_value(params["payload_json"])
            for statement, params in connection.executed
            if "INSERT INTO outbox_events" in str(statement)
        ]
        self.assertEqual(emitted_events[-1].event_type, EventType.SNAPSHOT_REQUESTED)
        self.assertEqual(emitted_events[-1].analysis_id, analysis_id)
        self.assertEqual(emitted_events[-1].agent_id, agent_id)
        self.assertEqual(emitted_events[-1].causation_id, requested.event_id)


class FakePathConnection:
    def __init__(self, *, outbox_event: EventEnvelope, update_rows: list[dict]) -> None:
        self.outbox_id = new_uuid7()
        self.outbox_event = outbox_event
        self.update_rows = update_rows
        self.executed = []
        self.marked_outbox_published = False
        self.processed_events = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if "SELECT id, payload_json" in statement_text:
            return FakeResult([{"id": self.outbox_id, "payload_json": self.outbox_event.to_dict()}])
        if "UPDATE outbox_events" in statement_text:
            self.marked_outbox_published = True
            return FakeResult([])
        if "UPDATE analyses" in statement_text and "RETURNING id" in statement_text:
            return FakeResult(self.update_rows)
        if "INSERT INTO event_processing_claims" in statement_text:
            return FakeResult([{"event_id": params["event_id"]}])
        if "INSERT INTO processed_events" in statement_text:
            self.processed_events.append((params["event_id"], params["consumer_name"]))
            return FakeResult([{"event_id": params["event_id"]}])
        return FakeResult([])

    async def scalar(self, statement, params=None):
        self.executed.append((statement, params or {}))
        return False


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


class SingleMessageConsumer:
    def __init__(self, message: ConsumedKafkaMessage) -> None:
        self._message = message
        self._consumed = False

    def __aiter__(self) -> SingleMessageConsumer:
        return self

    async def __anext__(self) -> ConsumedKafkaMessage:
        if self._consumed:
            raise StopAsyncIteration
        self._consumed = True
        return self._message


if __name__ == "__main__":
    unittest.main()
