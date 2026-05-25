from __future__ import annotations

import unittest

from backend.ids import new_uuid7
from backend.todo.repository import PostgresTodoRepository


class PostgresTodoRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_add_todo_list_allocates_version_and_emits_stream_event(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        turn_id = new_uuid7()
        tool_call_id = new_uuid7()
        connection = FakeConnection(scalar_values=[None, 3, None, 8])
        repository = PostgresTodoRepository(connection)

        result = await repository.add_todo_list(
            analysis_id=analysis_id,
            agent_id=agent_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            items=[
                {"id": "inspect-repo", "title": "Inspect repository", "status": "completed"},
                {"id": "write-summary", "title": "Write summary", "status": "in_progress"},
            ],
            note="Repository shape is known.",
        )

        self.assertEqual(result["version"], 3)
        self.assertIn("pg_advisory_xact_lock", str(connection.scalar_calls[0][0]))
        todo_insert = _first_executed_params(connection, "INSERT INTO agent_todo_lists")
        self.assertEqual(todo_insert["analysis_id"], analysis_id)
        self.assertEqual(todo_insert["agent_id"], agent_id)
        self.assertEqual(todo_insert["turn_id"], turn_id)
        self.assertEqual(todo_insert["tool_call_id"], tool_call_id)
        self.assertEqual(todo_insert["version"], 3)
        self.assertEqual(todo_insert["items_json"], result["items"])
        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        self.assertEqual(stream_insert["event_type"], "todo_update")
        self.assertEqual(stream_insert["payload_json"]["version"], 3)
        self.assertEqual(stream_insert["payload_json"]["items"][1]["status"], "in_progress")
        self.assertEqual(stream_insert["state"], "completed")

    async def test_latest_todo_list_reads_latest_version_for_agent(self) -> None:
        agent_id = new_uuid7()
        repository = PostgresTodoRepository(
            FakeConnection(
                rows=[
                    {
                        "version": 2,
                        "items_json": [{"id": "write-summary", "title": "Write summary", "status": "in_progress"}],
                        "note": "Current step.",
                    }
                ]
            )
        )

        result = await repository.latest_todo_list(agent_id=agent_id)

        self.assertEqual(result["version"], 2)
        self.assertEqual(result["items"][0]["id"], "write-summary")
        self.assertEqual(result["note"], "Current step.")


class FakeConnection:
    def __init__(
        self,
        *,
        rows: list[dict] | None = None,
        scalar_values: list[object] | None = None,
    ) -> None:
        self.rows = rows or []
        self.scalar_values = list(scalar_values or [])
        self.executed: list[tuple[object, dict]] = []
        self.scalar_calls: list[tuple[object, dict]] = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        return FakeResult(self.rows)

    async def scalar(self, statement, params=None):
        self.scalar_calls.append((statement, params or {}))
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return None


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


def _first_executed_params(connection: FakeConnection, sql_fragment: str) -> dict:
    for statement, params in connection.executed:
        if sql_fragment in str(statement):
            return params
    raise AssertionError(f"SQL fragment not executed: {sql_fragment}")


if __name__ == "__main__":
    unittest.main()
