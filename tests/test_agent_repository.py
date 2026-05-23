from __future__ import annotations

import unittest

from backend.agent import AgentSessionState
from backend.agent.repository import PostgresAgentRepository
from backend.events import EventEnvelope, EventType
from backend.ids import new_uuid7


class PostgresAgentRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_load_instruction_files_queries_snapshot_instruction_records(self) -> None:
        snapshot_id = new_uuid7()
        connection = FakeConnection(
            rows=[
                {
                    "path": "AGENTS.md",
                    "scope_path": "",
                    "depth": 0,
                    "content_hash": "sha256:abc",
                    "content_ref": "instructions/root.md",
                }
            ]
        )
        repository = PostgresAgentRepository(connection)

        rows = await repository.load_instruction_files(session=_session(snapshot_id=snapshot_id))

        self.assertEqual(rows[0]["path"], "AGENTS.md")
        self.assertEqual(rows[0]["content_ref"], "instructions/root.md")
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("FROM agent_instruction_files", executed_sql)
        self.assertEqual(connection.executed[0][1]["snapshot_id"], snapshot_id)

    async def test_load_config_snapshot_reads_config_json(self) -> None:
        config_snapshot_id = new_uuid7()
        connection = FakeConnection(rows=[{"config_json": {"tools": {"enabled": ["read_file"]}}}])
        repository = PostgresAgentRepository(connection)

        config_json = await repository.load_config_snapshot(session=_session(snapshot_id=new_uuid7(), config_snapshot_id=config_snapshot_id))

        self.assertEqual(config_json["tools"]["enabled"], ["read_file"])
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("FROM config_snapshots", executed_sql)
        self.assertEqual(connection.executed[0][1]["config_snapshot_id"], config_snapshot_id)

    async def test_load_context_items_hides_secret_paths_from_agent_tree(self) -> None:
        snapshot_id = new_uuid7()
        connection = FakeConnection(
            row_batches=[
                [
                    {"path": ".env"},
                    {"path": ".docker/config.json"},
                    {"path": "private.pem"},
                    {"path": "src/app.py"},
                ],
                [],
            ]
        )
        repository = PostgresAgentRepository(connection)

        items = await repository.load_context_items(session=_session(snapshot_id=snapshot_id))

        tree_item = next(item for item in items if "当前 snapshot 的文件树摘要" in item["content"][0]["text"])
        tree_text = tree_item["content"][0]["text"]
        self.assertIn("src/app.py", tree_text)
        self.assertNotIn(".env", tree_text)
        self.assertNotIn(".docker/config.json", tree_text)
        self.assertNotIn("private.pem", tree_text)
        tree_sql = str(connection.executed[0][0])
        self.assertIn("path <> '.env'", tree_sql)
        self.assertIn("lower(path) NOT LIKE '%.pem'", tree_sql)

    async def test_has_turn_for_event_queries_trigger_event_id(self) -> None:
        agent_id = new_uuid7()
        event_id = new_uuid7()
        connection = FakeConnection(scalar_values=[True])
        repository = PostgresAgentRepository(connection)

        exists = await repository.has_turn_for_event(agent_id=agent_id, event_id=event_id)

        self.assertTrue(exists)
        statement = str(connection.scalar_calls[0][0])
        params = connection.scalar_calls[0][1]
        self.assertIn("trigger_event_id", statement)
        self.assertEqual(params["agent_id"], agent_id)
        self.assertEqual(params["event_id"], event_id)

    async def test_get_turn_for_event_reads_existing_turn_status(self) -> None:
        turn_id = new_uuid7()
        agent_id = new_uuid7()
        event_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": turn_id, "status": "calling_model"}])
        repository = PostgresAgentRepository(connection)

        row = await repository.get_turn_for_event(agent_id=agent_id, event_id=event_id)

        self.assertEqual(row["id"], turn_id)
        self.assertEqual(row["status"], "calling_model")
        statement = str(connection.executed[0][0])
        self.assertIn("FROM agent_turns", statement)
        self.assertEqual(connection.executed[0][1]["agent_id"], agent_id)
        self.assertEqual(connection.executed[0][1]["event_id"], event_id)

    async def test_get_turn_for_domain_key_reads_existing_turn_status(self) -> None:
        turn_id = new_uuid7()
        agent_id = new_uuid7()
        trigger_domain_key = f"SnapshotReady:{new_uuid7()}"
        connection = FakeConnection(rows=[{"id": turn_id, "status": "completed"}])
        repository = PostgresAgentRepository(connection)

        row = await repository.get_turn_for_domain_key(agent_id=agent_id, trigger_domain_key=trigger_domain_key)

        self.assertEqual(row["id"], turn_id)
        self.assertEqual(row["status"], "completed")
        statement = str(connection.executed[0][0])
        self.assertIn("trigger_domain_key", statement)
        self.assertEqual(connection.executed[0][1]["agent_id"], agent_id)
        self.assertEqual(connection.executed[0][1]["trigger_domain_key"], trigger_domain_key)

    async def test_get_pending_tool_call_for_turn_reads_recoverable_tool_call(self) -> None:
        turn_id = new_uuid7()
        tool_call_id = new_uuid7()
        snapshot_id = new_uuid7()
        connection = FakeConnection(
            rows=[
                {
                    "id": tool_call_id,
                    "snapshot_id": snapshot_id,
                    "openai_call_id": "call_1",
                    "tool_name": "read_file",
                    "arguments_json": {"path": "README.md"},
                    "status": "queued",
                }
            ]
        )
        repository = PostgresAgentRepository(connection)

        row = await repository.get_pending_tool_call_for_turn(turn_id=turn_id)

        self.assertEqual(row["id"], tool_call_id)
        self.assertEqual(row["snapshot_id"], snapshot_id)
        self.assertEqual(row["openai_call_id"], "call_1")
        self.assertEqual(row["arguments_json"], {"path": "README.md"})
        statement = str(connection.executed[0][0])
        self.assertIn("FROM tool_calls", statement)
        self.assertIn("status IN ('queued', 'running')", statement)
        self.assertEqual(connection.executed[0][1]["turn_id"], turn_id)

    async def test_complete_turn_persists_output_ref(self) -> None:
        connection = FakeConnection()
        repository = PostgresAgentRepository(connection)
        turn_id = new_uuid7()

        await repository.complete_turn(
            turn_id=turn_id,
            response_id="resp_1",
            previous_response_id="resp_0",
            input_ref="agent-inputs/a/t.json",
            output_ref="agent-outputs/a/t.json",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        )

        executed_sql = str(connection.executed[0][0])
        params = connection.executed[0][1]
        self.assertIn("output_ref = :output_ref", executed_sql)
        self.assertEqual(params["output_ref"], "agent-outputs/a/t.json")
        self.assertEqual(params["turn_id"], turn_id)

    async def test_start_turn_persists_trigger_event_id(self) -> None:
        connection = FakeConnection()
        repository = PostgresAgentRepository(connection)
        event_id = new_uuid7()

        trigger_domain_key = f"SnapshotReady:{new_uuid7()}"

        await repository.start_turn(
            session=_session(snapshot_id=new_uuid7()),
            trigger_event_id=event_id,
            trigger_domain_key=trigger_domain_key,
        )

        statement = str(connection.executed[0][0])
        params = connection.executed[0][1]
        self.assertIn("trigger_event_id", statement)
        self.assertIn("trigger_domain_key", statement)
        self.assertEqual(params["trigger_event_id"], event_id)
        self.assertEqual(params["trigger_domain_key"], trigger_domain_key)

    async def test_create_tool_call_reuses_existing_openai_call_id(self) -> None:
        existing_tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": existing_tool_call_id}])
        repository = PostgresAgentRepository(connection)

        tool_call_id = await repository.create_tool_call(
            agent_id=new_uuid7(),
            turn_id=new_uuid7(),
            snapshot_id=new_uuid7(),
            openai_call_id="call_1",
            tool_name="read_file",
            arguments_json={"path": "README.md"},
            tool_registry_version="readonly-source-tools-v1",
            tool_schema_hash="sha256:schema",
            tool_policy_hash="sha256:policy",
            status="queued",
        )

        self.assertEqual(tool_call_id, existing_tool_call_id)
        statement = str(connection.executed[0][0])
        self.assertIn("ON CONFLICT", statement)
        self.assertIn("openai_call_id", statement)

    async def test_request_tool_call_writes_tool_call_stream_event_and_outbox_together(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": tool_call_id}], scalar_values=[None, 12])
        repository = PostgresAgentRepository(connection)
        analysis_id = new_uuid7()
        agent_id = new_uuid7()

        returned_id = await repository.request_tool_call(
            tool_call_kwargs={
                "agent_id": agent_id,
                "turn_id": new_uuid7(),
                "snapshot_id": new_uuid7(),
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "tool_registry_version": "readonly-source-tools-v1",
                "tool_schema_hash": "sha256:schema",
                "tool_policy_hash": "sha256:policy",
                "status": "queued",
            },
            analysis_id=analysis_id,
            agent_id=agent_id,
            stream_event_type="tool_call",
            stream_payload={"tool_name": "read_file", "arguments": {"path": "README.md"}},
            event=EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={"openai_call_id": "call_1"},
            ),
        )

        self.assertEqual(returned_id, tool_call_id)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("INSERT INTO tool_calls", executed_sql)
        self.assertIn("INSERT INTO agent_stream_events", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)
        self.assertIn("FOR UPDATE", str(connection.executed[0][0]))
        self.assertIn("status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')", str(connection.executed[0][0]))
        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        outbox_insert = _first_executed_params(connection, "INSERT INTO outbox_events")
        self.assertEqual(stream_insert["payload_json"]["tool_call_id"], str(tool_call_id))
        self.assertEqual(outbox_insert["payload_json"]["payload"]["tool_call_id"], str(tool_call_id))

    async def test_complete_turn_with_tool_call_is_atomic(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": tool_call_id}], scalar_values=[None, 12])
        repository = PostgresAgentRepository(connection)
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        turn_id = new_uuid7()

        returned_id = await repository.complete_turn_with_tool_call(
            turn_id=turn_id,
            response_id="resp_1",
            previous_response_id=None,
            input_ref="agent-inputs/a/t.json",
            output_ref="agent-outputs/a/t.json",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            latest_response_agent_id=agent_id,
            tool_call_kwargs={
                "agent_id": agent_id,
                "turn_id": turn_id,
                "snapshot_id": new_uuid7(),
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "tool_registry_version": "readonly-source-tools-v1",
                "tool_schema_hash": "sha256:schema",
                "tool_policy_hash": "sha256:policy",
                "status": "queued",
            },
            analysis_id=analysis_id,
            agent_id=agent_id,
            stream_event_type="tool_call",
            stream_payload={"tool_name": "read_file", "arguments": {"path": "README.md"}},
            event=EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={"openai_call_id": "call_1"},
            ),
        )

        self.assertEqual(returned_id, tool_call_id)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("FOR UPDATE", str(connection.executed[0][0]))
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertIn("UPDATE agent_turns", executed_sql)
        self.assertIn("INSERT INTO tool_calls", executed_sql)
        self.assertIn("INSERT INTO agent_stream_events", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)
        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        outbox_insert = _first_executed_params(connection, "INSERT INTO outbox_events")
        self.assertEqual(stream_insert["payload_json"]["tool_call_id"], str(tool_call_id))
        self.assertEqual(outbox_insert["payload_json"]["payload"]["tool_call_id"], str(tool_call_id))

    async def test_complete_turn_with_final_answer_is_atomic(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": analysis_id}], rowcounts=[1, 1, 1], scalar_values=[None, 4])
        repository = PostgresAgentRepository(connection)
        turn_id = new_uuid7()

        completed = await repository.complete_turn_with_final_answer(
            turn_id=turn_id,
            response_id="resp_1",
            previous_response_id=None,
            input_ref="agent-inputs/a/t.json",
            output_ref="agent-outputs/a/t.json",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            latest_response_agent_id=agent_id,
            analysis_id=analysis_id,
            agent_id=agent_id,
            output_text="done",
            stream_payload={"status": "completed"},
            event=EventEnvelope.new(
                event_type=EventType.ANALYSIS_COMPLETED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={"response_id": "resp_1"},
            ),
        )

        self.assertTrue(completed)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("FOR UPDATE", str(connection.executed[0][0]))
        self.assertIn("UPDATE agent_turns", executed_sql)
        self.assertIn("UPDATE analyses", executed_sql)
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertIn("INSERT INTO agent_stream_events", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)
        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        outbox_insert = _first_executed_params(connection, "INSERT INTO outbox_events")
        self.assertEqual(stream_insert["event_type"], "done")
        self.assertEqual(outbox_insert["payload_json"]["event_type"], "AnalysisCompleted")

    async def test_complete_turn_with_final_answer_writes_only_done_for_final_output(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": analysis_id}], rowcounts=[1, 1, 1], scalar_values=[None, 4])
        repository = PostgresAgentRepository(connection)
        turn_id = new_uuid7()

        completed = await repository.complete_turn_with_final_answer(
            turn_id=turn_id,
            response_id="resp_1",
            previous_response_id=None,
            input_ref="agent-inputs/a/t.json",
            output_ref="agent-outputs/a/t.json",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            latest_response_agent_id=agent_id,
            analysis_id=analysis_id,
            agent_id=agent_id,
            output_text="done",
            stream_payload={"status": "completed"},
            event=EventEnvelope.new(
                event_type=EventType.ANALYSIS_COMPLETED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={"response_id": "resp_1"},
            ),
            final_output_payload={"text": "done"},
        )

        self.assertTrue(completed)
        stream_inserts = _executed_params(connection, "INSERT INTO agent_stream_events")
        self.assertEqual([params["event_type"] for params in stream_inserts], ["done"])
        self.assertEqual(stream_inserts[0]["payload_json"], {"status": "completed"})

    async def test_request_tool_call_rejects_terminal_or_cancelling_analysis(self) -> None:
        connection = FakeConnection(rows=[])
        repository = PostgresAgentRepository(connection)

        with self.assertRaisesRegex(RuntimeError, "terminal or cancelling"):
            await repository.request_tool_call(
                tool_call_kwargs={
                    "agent_id": new_uuid7(),
                    "turn_id": new_uuid7(),
                    "snapshot_id": new_uuid7(),
                    "openai_call_id": "call_1",
                    "tool_name": "read_file",
                    "arguments_json": {"path": "README.md"},
                    "tool_registry_version": "readonly-source-tools-v1",
                    "tool_schema_hash": "sha256:schema",
                    "tool_policy_hash": "sha256:policy",
                    "status": "queued",
                },
                analysis_id=new_uuid7(),
                agent_id=new_uuid7(),
                stream_event_type="tool_call",
                stream_payload={"tool_name": "read_file", "arguments": {"path": "README.md"}},
                event=EventEnvelope.new(event_type=EventType.TOOL_CALL_REQUESTED, payload={"openai_call_id": "call_1"}),
            )

        self.assertEqual(len(connection.executed), 1)
        self.assertIn("FOR UPDATE", str(connection.executed[0][0]))

    async def test_get_pending_tool_output_reads_completed_failed_and_denied_tool_results(self) -> None:
        connection = FakeConnection(
            rows=[
                {
                    "openai_call_id": "call_1",
                    "tool_name": "search_text",
                    "arguments_json": {"query": "["},
                    "result_summary": "{\"ok\":false}",
                    "output_ref": "agent-outputs/a/t.json",
                }
            ]
        )
        repository = PostgresAgentRepository(connection)

        output = await repository.get_pending_tool_output(tool_call_id=new_uuid7())

        self.assertEqual(output["call_id"], "call_1")
        self.assertEqual(output["name"], "search_text")
        self.assertEqual(output["arguments"], {"query": "["})
        self.assertEqual(output["output"], "{\"ok\":false}")
        self.assertEqual(output["output_ref"], "agent-outputs/a/t.json")
        self.assertIn("JOIN agent_turns", str(connection.executed[0][0]))
        self.assertIn("IN ('completed', 'failed', 'denied')", str(connection.executed[0][0]))

    async def test_count_tool_calls_counts_agent_tool_rows(self) -> None:
        agent_id = new_uuid7()
        connection = FakeConnection(scalar_values=[5])
        repository = PostgresAgentRepository(connection)

        count = await repository.count_tool_calls(agent_id=agent_id)

        self.assertEqual(count, 5)
        self.assertIn("FROM tool_calls", str(connection.scalar_calls[0][0]))
        self.assertEqual(connection.scalar_calls[0][1]["agent_id"], agent_id)

    async def test_add_stream_event_uses_advisory_transaction_lock_before_seq_allocation(self) -> None:
        connection = FakeConnection(scalar_values=[None, 7])
        repository = PostgresAgentRepository(connection)
        analysis_id = new_uuid7()

        await repository.add_stream_event(
            analysis_id=analysis_id,
            agent_id=new_uuid7(),
            event_type="delta",
            payload={"text": "hello"},
        )

        self.assertIn("pg_advisory_xact_lock", str(connection.scalar_calls[0][0]))
        self.assertEqual(connection.scalar_calls[0][1]["analysis_id"], str(analysis_id))
        insert_sql = str(connection.executed[0][0])
        self.assertIn("INSERT INTO agent_stream_events", insert_sql)
        self.assertEqual(connection.executed[0][1]["seq"], 7)

    async def test_complete_analysis_does_not_overwrite_cancelling_status(self) -> None:
        connection = FakeConnection(rowcounts=[0, 0])
        repository = PostgresAgentRepository(connection)

        completed = await repository.complete_analysis(
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            output_text="done",
        )

        self.assertFalse(completed)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("'cancelling'", executed_sql)

    async def test_update_session_status_does_not_overwrite_terminal_or_cancelling_status(self) -> None:
        connection = FakeConnection()
        repository = PostgresAgentRepository(connection)

        await repository.update_session_status(agent_id=new_uuid7(), status="waiting_tool")

        self.assertIn(
            "status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')",
            str(connection.executed[0][0]),
        )

    async def test_fail_analysis_does_not_overwrite_cancelling_status(self) -> None:
        connection = FakeConnection(rowcounts=[0, 0])
        repository = PostgresAgentRepository(connection)

        failed = await repository.fail_analysis(
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            error_code="MODEL_CALL_FAILED",
            error_message="interrupted",
        )

        self.assertFalse(failed)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("'cancelling'", executed_sql)


class FakeConnection:
    def __init__(
        self,
        rows: list[dict] | None = None,
        row_batches: list[list[dict]] | None = None,
        scalar_values: list[object] | None = None,
        rowcounts: list[int] | None = None,
    ) -> None:
        self.rows = rows or []
        self.row_batches = list(row_batches or [])
        self.scalar_values = list(scalar_values or [])
        self.rowcounts = list(rowcounts or [])
        self.executed = []
        self.scalar_calls = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if "FOR UPDATE OF a, s" in statement_text:
            rows = [{"id": params.get("analysis_id")}] if self.rows else []
            return FakeResult(rows, rowcount=len(rows))
        rows = self.row_batches.pop(0) if self.row_batches else self.rows
        rowcount = self.rowcounts.pop(0) if self.rowcounts else len(self.rows)
        return FakeResult(rows, rowcount=rowcount)

    async def scalar(self, statement, params=None):
        self.scalar_calls.append((statement, params or {}))
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return None


class FakeResult:
    def __init__(self, rows: list[dict], *, rowcount: int | None = None) -> None:
        self._rows = rows
        self.rowcount = len(rows) if rowcount is None else rowcount

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


def _session(*, snapshot_id, config_snapshot_id=None):
    return AgentSessionState(
        analysis_id=new_uuid7(),
        agent_id=new_uuid7(),
        snapshot_id=snapshot_id,
        config_snapshot_id=config_snapshot_id or new_uuid7(),
        status="queued",
        effective_model="gpt-5.5",
        latest_response_id=None,
        turn_count=0,
        max_turns=10,
        effective_limits_json={},
        effective_runtime_json={},
    )


def _first_executed_params(connection: FakeConnection, sql_fragment: str) -> dict:
    for statement, params in connection.executed:
        if sql_fragment in str(statement):
            return params
    raise AssertionError(f"SQL fragment not executed: {sql_fragment}")


def _executed_params(connection: FakeConnection, sql_fragment: str) -> list[dict]:
    return [params for statement, params in connection.executed if sql_fragment in str(statement)]


if __name__ == "__main__":
    unittest.main()
