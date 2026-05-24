from __future__ import annotations

import unittest

from backend.events import EventEnvelope, EventType
from backend.events.repositories import DbOutboxSink, SqlOutboxRepository, SqlProcessedEventRepository
from backend.ids import new_uuid7


class EventRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_db_outbox_sink_inserts_event_payload(self) -> None:
        connection = FakeAsyncConnection()
        sink = DbOutboxSink(connection)
        event = EventEnvelope.new(event_type=EventType.ANALYSIS_REQUESTED, analysis_id=new_uuid7())

        await sink.add(event)

        self.assertEqual(len(connection.executed), 1)
        statement, params = connection.executed[0]
        self.assertIn("INSERT INTO outbox_events", str(statement))
        self.assertEqual(params["event_type"], EventType.ANALYSIS_REQUESTED.value)
        self.assertEqual(EventEnvelope.from_json_value(params["payload_json"]), event)

    async def test_sql_outbox_repository_fetches_unpublished_rows(self) -> None:
        event = EventEnvelope.new(event_type=EventType.ANALYSIS_REQUESTED, analysis_id=new_uuid7())
        outbox_id = new_uuid7()
        connection = FakeAsyncConnection(
            rows=[
                {
                    "id": outbox_id,
                    "payload_json": event.to_dict(),
                }
            ]
        )
        repository = SqlOutboxRepository(connection)

        rows = await repository.fetch_unpublished(limit=25)

        self.assertEqual(rows[0].id, outbox_id)
        self.assertEqual(rows[0].event, event)
        statement, params = connection.executed[0]
        self.assertIn("FOR UPDATE SKIP LOCKED", str(statement))
        self.assertEqual(params["limit"], 25)

    async def test_sql_outbox_repository_marks_published(self) -> None:
        connection = FakeAsyncConnection()
        repository = SqlOutboxRepository(connection)
        outbox_id = new_uuid7()

        await repository.mark_published(outbox_id)

        statement, params = connection.executed[0]
        self.assertIn("UPDATE outbox_events", str(statement))
        self.assertEqual(params["id"], outbox_id)

    async def test_sql_processed_event_repository_checks_and_marks_processed(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(rows=[{"event_id": event_id}], scalar_values=[True])
        repository = SqlProcessedEventRepository(connection)

        is_processed = await repository.is_processed(event_id, "agent-worker")
        await repository.mark_processed(event_id, "agent-worker", "owner-1")

        self.assertTrue(is_processed)
        self.assertEqual(len(connection.executed), 3)
        self.assertIn("SELECT EXISTS", str(connection.executed[0][0]))
        insert_sql = str(connection.executed[1][0])
        self.assertIn("INSERT INTO processed_events", insert_sql)
        self.assertIn("FROM event_processing_claims", insert_sql)
        self.assertIn("claim_owner = :claim_owner", insert_sql)
        self.assertIn("DELETE FROM event_processing_claims", str(connection.executed[2][0]))

    async def test_sql_processed_event_repository_does_not_mark_processed_when_owner_was_lost(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(rows=[], scalar_values=[False])
        repository = SqlProcessedEventRepository(connection)

        marked = await repository.mark_processed(event_id, "agent-worker", "stale-owner")

        self.assertFalse(marked)
        self.assertEqual(len(connection.executed), 2)
        self.assertIn("INSERT INTO processed_events", str(connection.executed[0][0]))

    async def test_sql_processed_event_repository_claims_processing_with_separate_claim_table(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(rows=[{"event_id": event_id}], scalar_values=[False])
        repository = SqlProcessedEventRepository(connection)

        claimed = await repository.claim_processing(event_id, "analysis-worker")

        self.assertTrue(claimed)
        statement, params = connection.executed[1]
        self.assertIn("INSERT INTO event_processing_claims", str(statement))
        self.assertIn("ON CONFLICT", str(statement))
        self.assertIn("RETURNING event_id", str(statement))
        self.assertEqual(params["event_id"], event_id)
        self.assertIn("claim_expires_at", params)
        self.assertIn("claim_owner", params)

    async def test_sql_processed_event_repository_claim_uses_expiring_conflict_update(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(rows=[{"event_id": event_id}], scalar_values=[False])
        repository = SqlProcessedEventRepository(connection)

        await repository.claim_processing(event_id, "analysis-worker")

        statement = str(connection.executed[1][0])
        self.assertIn("ON CONFLICT", statement)
        self.assertIn("WHERE event_processing_claims.claim_expires_at < :now", statement)

    async def test_sql_processed_event_repository_releases_failed_processing_claim(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(rows=[{"event_id": event_id}])
        repository = SqlProcessedEventRepository(connection)

        await repository.release_processing_claim(event_id, "analysis-worker")

        statement, params = connection.executed[0]
        self.assertIn("DELETE FROM event_processing_claims", str(statement))
        self.assertEqual(params["event_id"], event_id)

    async def test_sql_processed_event_repository_renews_processing_claim_for_matching_owner(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(rows=[{"event_id": event_id}])
        repository = SqlProcessedEventRepository(connection)

        renewed = await repository.renew_processing_claim(event_id, "analysis-worker", "owner-1")

        self.assertTrue(renewed)
        statement, params = connection.executed[0]
        statement_text = str(statement)
        self.assertIn("UPDATE event_processing_claims", statement_text)
        self.assertIn("claim_owner = :claim_owner", statement_text)
        self.assertIn("claim_expires_at = :claim_expires_at", statement_text)
        self.assertEqual(params["claim_owner"], "owner-1")

    async def test_sql_processed_event_repository_marks_processed_and_clears_claim(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(rows=[{"event_id": event_id}])
        repository = SqlProcessedEventRepository(connection)

        await repository.mark_processed(event_id, "analysis-worker", "owner-1")

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("INSERT INTO processed_events", executed_sql)
        self.assertIn("DELETE FROM event_processing_claims", executed_sql)

    async def test_sql_processed_event_repository_clears_claim_when_already_processed(self) -> None:
        event_id = new_uuid7()
        connection = FakeAsyncConnection(row_batches=[[], [{"event_id": event_id}]], scalar_values=[True])
        repository = SqlProcessedEventRepository(connection)

        marked = await repository.mark_processed(event_id, "analysis-worker", "owner-1")

        self.assertTrue(marked)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("ON CONFLICT (event_id, consumer_name) DO NOTHING", executed_sql)
        self.assertIn("DELETE FROM event_processing_claims", executed_sql)


class FakeAsyncConnection:
    def __init__(
        self,
        *,
        rows: list[dict] | None = None,
        row_batches: list[list[dict]] | None = None,
        scalar_values: list[object] | None = None,
    ) -> None:
        self.rows = rows or []
        self.row_batches = list(row_batches or [])
        self.scalar_values = scalar_values or []
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        if self.row_batches:
            return FakeResult(self.row_batches.pop(0))
        return FakeResult(self.rows)

    async def scalar(self, statement, params=None):
        self.executed.append((statement, params or {}))
        return self.scalar_values.pop(0)


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


if __name__ == "__main__":
    unittest.main()
