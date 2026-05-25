from __future__ import annotations

import unittest

from backend.events import EventEnvelope, EventType
from backend.ids import new_uuid7
from backend.workers.batch_scheduler import AnalysisBatchSchedulerHandler


class AnalysisBatchSchedulerWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_submitted_claims_available_pending_items_and_dispatches_analysis_requests(self) -> None:
        batch_id = new_uuid7()
        first_analysis_id = new_uuid7()
        first_agent_id = new_uuid7()
        second_analysis_id = new_uuid7()
        second_agent_id = new_uuid7()
        third_analysis_id = new_uuid7()
        connection = FakeConnection(
            row_batches=[
                [
                    {
                        "id": batch_id,
                        "max_parallel": 2,
                        "active_count": 0,
                        "pending_count": 3,
                    }
                ],
                [
                    {
                        "batch_item_id": new_uuid7(),
                        "analysis_id": first_analysis_id,
                        "agent_id": first_agent_id,
                        "repository_url": "https://github.com/example/one.git",
                        "requested_ref": "main",
                        "analysis_profile_id": None,
                        "config_snapshot_id": str(new_uuid7()),
                    },
                    {
                        "batch_item_id": new_uuid7(),
                        "analysis_id": second_analysis_id,
                        "agent_id": second_agent_id,
                        "repository_url": "https://github.com/example/two.git",
                        "requested_ref": "release",
                        "analysis_profile_id": None,
                        "config_snapshot_id": str(new_uuid7()),
                    },
                ],
            ],
        )
        handler = AnalysisBatchSchedulerHandler(connection)

        await handler(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_BATCH_SUBMITTED,
                payload={"batch_id": str(batch_id), "max_parallel": 2},
            )
        )

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("FOR UPDATE SKIP LOCKED", executed_sql)
        self.assertIn("ORDER BY sort_order", executed_sql)
        self.assertIn("LIMIT :limit", executed_sql)
        self.assertIn("status = 'dispatched'", executed_sql)
        self.assertNotIn(str(third_analysis_id), executed_sql)

        outbox_events = _outbox_events(connection)
        self.assertEqual([event.event_type for event in outbox_events], [EventType.ANALYSIS_REQUESTED] * 2)
        self.assertEqual([event.analysis_id for event in outbox_events], [first_analysis_id, second_analysis_id])
        self.assertEqual([event.agent_id for event in outbox_events], [first_agent_id, second_agent_id])
        self.assertEqual(outbox_events[1].payload["requested_ref"], "release")

    async def test_batch_submitted_does_not_dispatch_when_all_slots_are_active(self) -> None:
        batch_id = new_uuid7()
        connection = FakeConnection(
            row_batches=[
                [
                    {
                        "id": batch_id,
                        "max_parallel": 2,
                        "active_count": 2,
                        "pending_count": 3,
                    }
                ],
            ],
        )
        handler = AnalysisBatchSchedulerHandler(connection)

        await handler(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_BATCH_SUBMITTED,
                payload={"batch_id": str(batch_id), "max_parallel": 2},
            )
        )

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertNotIn("status = 'dispatched'", executed_sql)
        self.assertEqual(_outbox_events(connection), [])

    async def test_terminal_analysis_event_releases_slot_and_dispatches_next_pending_item(self) -> None:
        batch_id = new_uuid7()
        completed_analysis_id = new_uuid7()
        next_analysis_id = new_uuid7()
        next_agent_id = new_uuid7()
        connection = FakeConnection(
            row_batches=[
                [{"batch_id": batch_id, "previous_status": "dispatched"}],
                [
                    {
                        "id": batch_id,
                        "max_parallel": 2,
                        "active_count": 1,
                        "pending_count": 1,
                    }
                ],
                [
                    {
                        "batch_item_id": new_uuid7(),
                        "analysis_id": next_analysis_id,
                        "agent_id": next_agent_id,
                        "repository_url": "https://github.com/example/next.git",
                        "requested_ref": "main",
                        "analysis_profile_id": None,
                        "config_snapshot_id": str(new_uuid7()),
                    }
                ],
            ],
        )
        handler = AnalysisBatchSchedulerHandler(connection)

        await handler(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_COMPLETED,
                analysis_id=completed_analysis_id,
                payload={},
            )
        )

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("UPDATE analysis_batch_items", executed_sql)
        self.assertIn("status = :terminal_status", executed_sql)
        outbox_events = _outbox_events(connection)
        self.assertEqual([event.event_type for event in outbox_events], [EventType.ANALYSIS_REQUESTED])
        self.assertEqual(outbox_events[0].analysis_id, next_analysis_id)
        self.assertEqual(outbox_events[0].agent_id, next_agent_id)

    async def test_slot_available_event_schedules_existing_batch(self) -> None:
        batch_id = new_uuid7()
        next_analysis_id = new_uuid7()
        next_agent_id = new_uuid7()
        connection = FakeConnection(
            row_batches=[
                [
                    {
                        "id": batch_id,
                        "max_parallel": 1,
                        "active_count": 0,
                        "pending_count": 1,
                    }
                ],
                [
                    {
                        "batch_item_id": new_uuid7(),
                        "analysis_id": next_analysis_id,
                        "agent_id": next_agent_id,
                        "repository_url": "https://github.com/example/next.git",
                        "requested_ref": "main",
                        "analysis_profile_id": None,
                        "config_snapshot_id": str(new_uuid7()),
                    }
                ],
            ],
        )
        handler = AnalysisBatchSchedulerHandler(connection)

        await handler(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_BATCH_SLOT_AVAILABLE,
                payload={"batch_id": str(batch_id)},
            )
        )

        outbox_events = _outbox_events(connection)
        self.assertEqual([event.event_type for event in outbox_events], [EventType.ANALYSIS_REQUESTED])
        self.assertEqual(outbox_events[0].analysis_id, next_analysis_id)

    async def test_unsupported_event_is_rejected(self) -> None:
        handler = AnalysisBatchSchedulerHandler(FakeConnection(row_batches=[]))

        with self.assertRaisesRegex(ValueError, "Unsupported analysis batch scheduler event"):
            await handler(EventEnvelope.new(event_type=EventType.SNAPSHOT_READY, analysis_id=new_uuid7()))


class FakeConnection:
    def __init__(self, *, row_batches: list[list[dict]]) -> None:
        self.row_batches = list(row_batches)
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if statement_text.lstrip().startswith("SELECT") or "RETURNING" in statement_text:
            rows = self.row_batches.pop(0) if self.row_batches else []
            return FakeResult(rows)
        return FakeResult([])


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


def _outbox_events(connection: FakeConnection) -> list[EventEnvelope]:
    return [
        EventEnvelope.from_json_value(params["payload_json"])
        for statement, params in connection.executed
        if "INSERT INTO outbox_events" in str(statement)
    ]


if __name__ == "__main__":
    unittest.main()
