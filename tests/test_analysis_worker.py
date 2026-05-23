from __future__ import annotations

import unittest

from backend.events import EventEnvelope, EventType
from backend.ids import new_uuid7
from backend.workers.analysis import AnalysisCommandHandler


class AnalysisWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_requested_moves_analysis_to_snapshotting_and_requests_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(update_rows=[{"id": analysis_id}])
        handler = AnalysisCommandHandler(connection)
        event = EventEnvelope.new(
            event_type=EventType.ANALYSIS_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload={
                "repository_url": "https://github.com/example/project.git",
                "requested_ref": "main",
                "config_snapshot_id": str(new_uuid7()),
            },
        )

        await handler(event)

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("UPDATE analyses", executed_sql)
        self.assertIn("status = :status", executed_sql)
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)

        outbox_params = connection.executed[-1][1]
        outbox_event = EventEnvelope.from_json_value(outbox_params["payload_json"])
        self.assertEqual(outbox_event.event_type, EventType.SNAPSHOT_REQUESTED)
        self.assertEqual(outbox_event.analysis_id, analysis_id)
        self.assertEqual(outbox_event.agent_id, agent_id)
        self.assertEqual(outbox_event.causation_id, event.event_id)
        self.assertEqual(outbox_event.payload["repository_url"], "https://github.com/example/project.git")
        self.assertEqual(outbox_event.payload["requested_ref"], "main")

    async def test_analysis_requested_does_not_emit_snapshot_request_when_not_queued(self) -> None:
        analysis_id = new_uuid7()
        connection = FakeConnection(update_rows=[])
        handler = AnalysisCommandHandler(connection)
        event = EventEnvelope.new(
            event_type=EventType.ANALYSIS_REQUESTED,
            analysis_id=analysis_id,
            agent_id=new_uuid7(),
            payload={
                "repository_url": "https://github.com/example/project.git",
                "requested_ref": "main",
            },
        )

        await handler(event)

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("UPDATE analyses", executed_sql)
        self.assertNotIn("INSERT INTO outbox_events", executed_sql)

    async def test_analysis_cancel_requested_marks_analysis_and_agent_cancelled(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(update_rows=[{"id": analysis_id}])
        handler = AnalysisCommandHandler(connection)
        event = EventEnvelope.new(
            event_type=EventType.ANALYSIS_CANCEL_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
        )

        await handler(event)

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("UPDATE analyses", executed_sql)
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertIn("UPDATE tool_calls", executed_sql)
        self.assertIn("status = 'cancelled'", executed_sql)
        self.assertIn("permission_decision = 'deny'", executed_sql)
        self.assertNotIn("COALESCE(permission_decision, 'deny')", executed_sql)
        self.assertIn("INSERT INTO agent_stream_events", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)

        stream_events = [
            params
            for statement, params in connection.executed
            if "INSERT INTO agent_stream_events" in str(statement)
        ]
        self.assertEqual([event["event_type"] for event in stream_events], ["status", "done"])
        self.assertEqual(stream_events[0]["payload_json"], {"status": "cancelled"})
        self.assertEqual(stream_events[1]["payload_json"], {"status": "cancelled"})

        outbox_params = connection.executed[-1][1]
        outbox_event = EventEnvelope.from_json_value(outbox_params["payload_json"])
        self.assertEqual(outbox_event.event_type, EventType.ANALYSIS_CANCELLED)
        self.assertEqual(outbox_event.analysis_id, analysis_id)
        self.assertEqual(outbox_event.agent_id, agent_id)
        self.assertEqual(outbox_event.causation_id, event.event_id)

    async def test_analysis_requested_requires_analysis_and_agent_ids(self) -> None:
        handler = AnalysisCommandHandler(FakeConnection(update_rows=[]))
        event = EventEnvelope.new(
            event_type=EventType.ANALYSIS_REQUESTED,
            analysis_id=new_uuid7(),
            payload={
                "repository_url": "https://github.com/example/project.git",
                "requested_ref": "main",
            },
        )

        with self.assertRaisesRegex(ValueError, "analysis_id and agent_id"):
            await handler(event)

    async def test_unsupported_event_is_rejected(self) -> None:
        handler = AnalysisCommandHandler(FakeConnection(update_rows=[]))
        event = EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7())

        with self.assertRaisesRegex(ValueError, "Unsupported analysis command"):
            await handler(event)


class FakeConnection:
    def __init__(self, *, update_rows: list[dict]) -> None:
        self._update_rows = list(update_rows)
        self.executed = []
        self.scalar_calls = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if "RETURNING id" in statement_text:
            return FakeResult(self._update_rows)
        return FakeResult([])

    async def scalar(self, statement, params=None):
        self.scalar_calls.append((statement, params or {}))
        return 1


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


if __name__ == "__main__":
    unittest.main()
