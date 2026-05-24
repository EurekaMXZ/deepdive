from __future__ import annotations

import unittest
from datetime import UTC, datetime

from backend.documents.repository import PostgresDocumentRepository
from backend.ids import new_uuid7


class PostgresDocumentRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_update_document_with_revision_uses_atomic_version_guard_and_returning_row(self) -> None:
        document_id = new_uuid7()
        connection = FakeConnection(
            rows=[
                {
                    "id": document_id,
                    "analysis_id": new_uuid7(),
                    "agent_id": new_uuid7(),
                    "title": "Review",
                    "kind": "markdown",
                    "status": "draft",
                    "current_version": 2,
                    "content_ref": "documents/a/doc/revisions/call.md",
                    "content_hash": "sha256:abc",
                    "size_bytes": 12,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "finalized_at": None,
                }
            ]
        )
        repository = PostgresDocumentRepository(connection)

        updated = await repository.update_document_with_revision(
            document_id,
            {
                "expected_version": 1,
                "expected_status": "draft",
                "current_version": 2,
                "status": "draft",
                "content_ref": "documents/a/doc/revisions/call.md",
                "content_hash": "sha256:abc",
                "size_bytes": 12,
                "updated_at": datetime.now(UTC),
                "finalized_at": None,
            },
            {
                "id": new_uuid7(),
                "document_id": document_id,
                "version": 2,
                "tool_call_id": new_uuid7(),
                "operation": "update",
                "content_ref": "documents/a/doc/revisions/call.md",
                "content_hash": "sha256:abc",
                "size_bytes": 12,
                "created_at": datetime.now(UTC),
            },
        )

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed).lower()
        self.assertIsNotNone(updated)
        self.assertIn("current_version = :expected_version", executed_sql)
        self.assertIn("status = :expected_status", executed_sql)
        self.assertIn("returning id, analysis_id, agent_id", executed_sql)
        self.assertEqual(connection.execute_count("select id, analysis_id"), 0)


class FakeConnection:
    def __init__(self, *, rows: list[dict]) -> None:
        self.rows = rows
        self.executed: list[tuple[object, dict]] = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        if "returning id" in str(statement).lower():
            return FakeResult(self.rows)
        return FakeResult([])

    def execute_count(self, needle: str) -> int:
        return sum(1 for statement, _ in self.executed if needle.lower() in str(statement).lower())


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> FakeResult:
        return self

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


if __name__ == "__main__":
    unittest.main()
