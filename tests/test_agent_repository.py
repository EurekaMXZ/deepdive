from __future__ import annotations

import unittest

from backend.agent import AgentSessionState
from backend.agent.repository import PostgresAgentRepository
from backend.events import EventEnvelope, EventType
from backend.execution import DEFAULT_TOOL_REGISTRY_VERSION
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

        config_json = await repository.load_config_snapshot(
            session=_session(snapshot_id=new_uuid7(), config_snapshot_id=config_snapshot_id)
        )

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
                    {"path": ".env.example"},
                    {"path": "frontend/.env.example"},
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
        self.assertIn(".env.example", tree_text)
        self.assertIn("frontend/.env.example", tree_text)
        tree_paths = set(tree_text.splitlines()[1:])
        self.assertNotIn(".env", tree_paths)
        self.assertNotIn(".docker/config.json", tree_text)
        self.assertNotIn("private.pem", tree_text)
        tree_sql = str(connection.executed[0][0])
        self.assertIn("path <> '.env'", tree_sql)
        self.assertIn("'.env.example'", tree_sql)
        self.assertIn("lower(path) NOT LIKE '%.pem'", tree_sql)

    async def test_load_context_items_includes_latest_todo_snapshot(self) -> None:
        snapshot_id = new_uuid7()
        connection = FakeConnection(
            row_batches=[
                [{"path": "README.md"}],
                [],
                [
                    {
                        "version": 4,
                        "items_json": [
                            {"id": "inspect-repo", "title": "Inspect repository", "status": "completed"},
                            {"id": "write-summary", "title": "Write summary", "status": "in_progress"},
                        ],
                        "note": "Repository shape is known.",
                    }
                ],
            ]
        )
        repository = PostgresAgentRepository(connection)

        items = await repository.load_context_items(session=_session(snapshot_id=snapshot_id))

        todo_item = next(item for item in items if "当前 TODO 计划" in item["content"][0]["text"])
        todo_text = todo_item["content"][0]["text"]
        self.assertIn("version: 4", todo_text)
        self.assertIn("[completed] inspect-repo - Inspect repository", todo_text)
        self.assertIn("[in_progress] write-summary - Write summary", todo_text)
        self.assertIn("Repository shape is known.", todo_text)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("FROM agent_todo_lists", executed_sql)

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
            usage={
                "input_tokens": 10,
                "cached_input_tokens": 7,
                "uncached_input_tokens": 3,
                "output_tokens": 2,
                "reasoning_tokens": 1,
                "total_tokens": 12,
            },
        )

        executed_sql = str(connection.executed[0][0])
        params = connection.executed[0][1]
        self.assertIn("output_ref = :output_ref", executed_sql)
        self.assertIn("cached_input_token_count = :cached_input_token_count", executed_sql)
        self.assertIn("uncached_input_token_count = :uncached_input_token_count", executed_sql)
        self.assertIn("reasoning_token_count = :reasoning_token_count", executed_sql)
        self.assertEqual(params["output_ref"], "agent-outputs/a/t.json")
        self.assertEqual(params["input_token_count"], 10)
        self.assertEqual(params["cached_input_token_count"], 7)
        self.assertEqual(params["uncached_input_token_count"], 3)
        self.assertEqual(params["output_token_count"], 2)
        self.assertEqual(params["reasoning_token_count"], 1)
        self.assertEqual(params["total_token_count"], 12)
        self.assertEqual(params["turn_id"], turn_id)

    async def test_append_context_item_allocates_agent_seq_and_persists_payload(self) -> None:
        agent_id = new_uuid7()
        turn_id = new_uuid7()
        connection = FakeConnection(scalar_values=[None, 3])
        repository = PostgresAgentRepository(connection)

        await repository.append_context_item(
            agent_id=agent_id,
            turn_id=turn_id,
            item_type="assistant_output",
            payload={"type": "message", "content": [{"type": "output_text", "text": "已读取 README"}]},
            response_id="resp_1",
            source="model",
            idempotency_key="turn:assistant:resp_1",
        )

        self.assertIn("pg_advisory_xact_lock", str(connection.scalar_calls[0][0]))
        insert_params = _first_executed_params(connection, "INSERT INTO agent_context_items")
        self.assertEqual(insert_params["agent_id"], agent_id)
        self.assertEqual(insert_params["turn_id"], turn_id)
        self.assertEqual(insert_params["seq"], 3)
        self.assertEqual(insert_params["item_type"], "assistant_output")
        self.assertEqual(insert_params["payload_json"]["type"], "message")
        self.assertEqual(insert_params["response_id"], "resp_1")
        self.assertEqual(insert_params["source"], "model")
        self.assertEqual(insert_params["idempotency_key"], "turn:assistant:resp_1")
        self.assertIn("ON CONFLICT", str(connection.executed[-1][0]))

    async def test_context_payload_helpers_create_canonical_shapes(self) -> None:
        from backend.agent.context_items import (
            assistant_output_payload,
            function_call_output_payload,
            function_call_payload,
        )

        function_call = function_call_payload(
            call_id="call_1",
            name="read_file",
            arguments={"path": "README.md"},
        )
        function_output = function_call_output_payload(
            call_id="call_1",
            output={"ok": True, "result": {"path": "README.md"}},
        )
        assistant_output = assistant_output_payload("done")

        self.assertEqual(function_call["type"], "function_call")
        self.assertEqual(function_call["arguments"], '{"path":"README.md"}')
        self.assertEqual(function_output["type"], "function_call_output")
        self.assertIn("README.md", function_output["output"])
        self.assertEqual(assistant_output["type"], "message")
        self.assertEqual(assistant_output["role"], "assistant")
        self.assertEqual(assistant_output["content"], [{"type": "output_text", "text": "done"}])

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
            tool_registry_version=DEFAULT_TOOL_REGISTRY_VERSION,
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
                "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
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
        self.assertIn(
            "status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')", str(connection.executed[0][0])
        )
        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        outbox_insert = _first_executed_params(connection, "INSERT INTO outbox_events")
        self.assertEqual(stream_insert["payload_json"]["tool_call_id"], str(tool_call_id))
        self.assertEqual(outbox_insert["payload_json"]["payload"]["tool_call_id"], str(tool_call_id))

    async def test_request_tool_call_writes_idempotent_stream_event_for_openai_call_id(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": tool_call_id}], scalar_values=[None, 12])
        repository = PostgresAgentRepository(connection)
        analysis_id = new_uuid7()
        agent_id = new_uuid7()

        await repository.request_tool_call(
            tool_call_kwargs={
                "agent_id": agent_id,
                "turn_id": new_uuid7(),
                "snapshot_id": new_uuid7(),
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
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

        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        self.assertEqual(stream_insert["idempotency_key"], "tool_call:call_1")
        self.assertIn("idempotency_key", str(_first_executed_statement(connection, "INSERT INTO agent_stream_events")))
        self.assertIn("ON CONFLICT", str(_first_executed_statement(connection, "INSERT INTO agent_stream_events")))

    async def test_complete_turn_with_tool_call_is_atomic(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": tool_call_id}], scalar_values=[None, 12, 13])
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
                "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                "tool_schema_hash": "sha256:schema",
                "tool_policy_hash": "sha256:policy",
                "status": "queued",
            },
            analysis_id=analysis_id,
            agent_id=agent_id,
            stream_event_type="tool_call",
            stream_payload={"tool_name": "read_file", "arguments": {"path": "README.md"}},
            output_items=[
                {"id": "rs_1", "type": "reasoning", "summary": [], "phase": "analysis"},
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                    "status": "completed",
                    "phase": "tool_calling",
                },
            ],
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
        self.assertIn("INSERT INTO agent_context_items", executed_sql)
        self.assertIn("INSERT INTO agent_stream_events", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)
        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        context_inserts = _executed_params(connection, "INSERT INTO agent_context_items")
        outbox_insert = _first_executed_params(connection, "INSERT INTO outbox_events")
        self.assertEqual([params["item_type"] for params in context_inserts], ["reasoning", "function_call"])
        self.assertEqual(context_inserts[0]["payload_json"]["id"], "rs_1")
        self.assertEqual(context_inserts[0]["payload_json"]["phase"], "analysis")
        self.assertEqual(context_inserts[1]["payload_json"]["id"], "fc_1")
        self.assertEqual(context_inserts[1]["payload_json"]["phase"], "tool_calling")
        self.assertEqual(context_inserts[1]["idempotency_key"], "model:function_call:call_1")
        self.assertEqual(stream_insert["payload_json"]["tool_call_id"], str(tool_call_id))
        self.assertEqual(outbox_insert["payload_json"]["payload"]["tool_call_id"], str(tool_call_id))

    async def test_complete_turn_with_tool_calls_is_atomic_for_parallel_batch(self) -> None:
        first_tool_call_id = new_uuid7()
        second_tool_call_id = new_uuid7()
        connection = FakeConnection(
            rows=[{"id": new_uuid7()}],
            row_batches=[
                [],
                [],
                [{"id": first_tool_call_id}],
                [{"id": second_tool_call_id}],
            ],
            scalar_values=[None, 12, 13, 14, 15],
        )
        repository = PostgresAgentRepository(connection)
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        turn_id = new_uuid7()

        returned_ids = await repository.complete_turn_with_tool_calls(
            turn_id=turn_id,
            response_id="resp_1",
            previous_response_id=None,
            input_ref="agent-inputs/a/t.json",
            output_ref="agent-outputs/a/t.json",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            latest_response_agent_id=agent_id,
            tool_call_requests=[
                {
                    "tool_call_kwargs": {
                        "agent_id": agent_id,
                        "turn_id": turn_id,
                        "snapshot_id": new_uuid7(),
                        "openai_call_id": "call_search",
                        "tool_name": "search_file",
                        "arguments_json": {"query": "handler.py"},
                        "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                        "tool_schema_hash": "sha256:schema",
                        "tool_policy_hash": "sha256:policy",
                        "status": "queued",
                    },
                    "stream_event_type": "tool_call",
                    "stream_payload": {"tool_name": "search_file", "arguments": {"query": "handler.py"}},
                    "event": EventEnvelope.new(
                        event_type=EventType.TOOL_CALL_REQUESTED,
                        analysis_id=analysis_id,
                        agent_id=agent_id,
                        payload={"openai_call_id": "call_search"},
                    ),
                },
                {
                    "tool_call_kwargs": {
                        "agent_id": agent_id,
                        "turn_id": turn_id,
                        "snapshot_id": new_uuid7(),
                        "openai_call_id": "call_read",
                        "tool_name": "read_file",
                        "arguments_json": {"path": "backend/agent/handler.py"},
                        "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                        "tool_schema_hash": "sha256:schema",
                        "tool_policy_hash": "sha256:policy",
                        "status": "queued",
                    },
                    "stream_event_type": "tool_call",
                    "stream_payload": {
                        "tool_name": "read_file",
                        "arguments": {"path": "backend/agent/handler.py"},
                    },
                    "event": EventEnvelope.new(
                        event_type=EventType.TOOL_CALL_REQUESTED,
                        analysis_id=analysis_id,
                        agent_id=agent_id,
                        payload={"openai_call_id": "call_read"},
                    ),
                },
            ],
            analysis_id=analysis_id,
            agent_id=agent_id,
            output_items=[
                {"id": "fc_search", "type": "function_call", "call_id": "call_search", "name": "search_file"},
                {"id": "fc_read", "type": "function_call", "call_id": "call_read", "name": "read_file"},
            ],
        )

        self.assertEqual(returned_ids, [first_tool_call_id, second_tool_call_id])
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertIn("UPDATE agent_turns", executed_sql)
        self.assertEqual(len(_executed_params(connection, "INSERT INTO tool_calls")), 2)
        self.assertEqual(len(_executed_params(connection, "INSERT INTO agent_context_items")), 2)
        stream_inserts = _executed_params(connection, "INSERT INTO agent_stream_events")
        outbox_inserts = _executed_params(connection, "INSERT INTO outbox_events")
        self.assertEqual(
            [params["payload_json"]["tool_call_id"] for params in stream_inserts],
            [str(first_tool_call_id), str(second_tool_call_id)],
        )
        self.assertEqual(
            [params["payload_json"]["payload"]["tool_call_id"] for params in outbox_inserts],
            [str(first_tool_call_id), str(second_tool_call_id)],
        )

    async def test_complete_turn_with_reused_tool_result_persists_function_output_context_item(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": tool_call_id}], scalar_values=[None, 1])
        repository = PostgresAgentRepository(connection)
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        turn_id = new_uuid7()

        await repository.complete_turn_with_tool_call(
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
                "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                "tool_schema_hash": "sha256:schema",
                "tool_policy_hash": "sha256:policy",
                "status": "completed",
                "result_summary": {"ok": True, "result": {"path": "README.md"}},
            },
            analysis_id=analysis_id,
            agent_id=agent_id,
            stream_event_type="tool_result",
            stream_payload={"ok": True, "result": {"path": "README.md"}},
            event=EventEnvelope.new(
                event_type=EventType.TOOL_CALL_COMPLETED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={"openai_call_id": "call_1"},
            ),
        )

        context_inserts = _executed_params(connection, "INSERT INTO agent_context_items")
        self.assertEqual(
            [params["item_type"] for params in context_inserts],
            ["function_call", "function_call_output"],
        )
        self.assertEqual(context_inserts[1]["payload_json"]["call_id"], "call_1")
        self.assertIn("README.md", context_inserts[1]["payload_json"]["output"])
        self.assertEqual(context_inserts[1]["idempotency_key"], "tool:function_call_output:call_1")

    async def test_complete_turn_with_final_answer_is_atomic(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": analysis_id}], rowcounts=[1, 1, 1], scalar_values=[None, 4, 5])
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
            output_items=[
                {"id": "rs_1", "type": "reasoning", "summary": [], "phase": "analysis"},
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                    "status": "completed",
                    "phase": "final",
                },
            ],
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
        self.assertIn("UPDATE analysis_repositories", executed_sql)
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertIn("INSERT INTO agent_context_items", executed_sql)
        self.assertIn("INSERT INTO agent_stream_events", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)
        stream_insert = _first_executed_params(connection, "INSERT INTO agent_stream_events")
        context_inserts = _executed_params(connection, "INSERT INTO agent_context_items")
        outbox_insert = _first_executed_params(connection, "INSERT INTO outbox_events")
        self.assertEqual([params["item_type"] for params in context_inserts], ["reasoning", "message"])
        self.assertEqual(context_inserts[0]["payload_json"]["phase"], "analysis")
        self.assertEqual(context_inserts[1]["payload_json"]["id"], "msg_1")
        self.assertEqual(context_inserts[1]["payload_json"]["content"], [{"type": "output_text", "text": "done"}])
        self.assertEqual(context_inserts[1]["idempotency_key"], "model:message:msg_1")
        self.assertEqual(stream_insert["event_type"], "done")
        self.assertEqual(outbox_insert["payload_json"]["event_type"], "AnalysisCompleted")

    async def test_complete_turn_with_final_answer_writes_final_delta_before_done(self) -> None:
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
            final_delta_payload={"text": "done"},
        )

        self.assertTrue(completed)
        stream_inserts = _executed_params(connection, "INSERT INTO agent_stream_events")
        self.assertEqual([params["event_type"] for params in stream_inserts], ["delta", "done"])
        self.assertEqual(stream_inserts[0]["payload_json"], {"text": "done"})
        self.assertEqual(stream_inserts[0]["response_id"], "resp_1")
        self.assertEqual(stream_inserts[1]["payload_json"], {"status": "completed"})

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
                    "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
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
        turn_id = new_uuid7()
        connection = FakeConnection(
            rows=[
                {
                    "id": new_uuid7(),
                    "turn_id": turn_id,
                    "openai_call_id": "call_1",
                    "tool_name": "search_text",
                    "arguments_json": {"query": "["},
                    "result_summary": '{"ok":false}',
                    "output_ref": "agent-outputs/a/t.json",
                }
            ]
        )
        repository = PostgresAgentRepository(connection)

        output = await repository.get_pending_tool_output(tool_call_id=new_uuid7())

        self.assertEqual(output["call_id"], "call_1")
        self.assertEqual(output["name"], "search_text")
        self.assertEqual(output["arguments"], {"query": "["})
        self.assertEqual(output["output"], '{"ok":false}')
        self.assertEqual(output["output_ref"], "agent-outputs/a/t.json")
        self.assertEqual(output["turn_id"], turn_id)
        self.assertIn("JOIN agent_turns", str(connection.executed[0][0]))
        self.assertIn("IN ('completed', 'failed', 'denied')", str(connection.executed[0][0]))

    async def test_load_ready_tool_outputs_for_turn_returns_none_while_batch_has_pending_calls(self) -> None:
        turn_id = new_uuid7()
        connection = FakeConnection(scalar_values=[1])
        repository = PostgresAgentRepository(connection)

        outputs = await repository.load_ready_tool_outputs_for_turn(turn_id=turn_id)

        self.assertIsNone(outputs)
        self.assertIn("status IN ('queued', 'validating', 'running')", str(connection.scalar_calls[0][0]))
        self.assertEqual(connection.scalar_calls[0][1]["turn_id"], turn_id)
        self.assertEqual(connection.executed, [])

    async def test_load_ready_tool_outputs_for_turn_reads_all_terminal_outputs_in_order(self) -> None:
        turn_id = new_uuid7()
        first_tool_call_id = new_uuid7()
        second_tool_call_id = new_uuid7()
        connection = FakeConnection(
            row_batches=[
                [
                    {
                        "id": first_tool_call_id,
                        "turn_id": turn_id,
                        "openai_call_id": "call_search",
                        "tool_name": "search_file",
                        "arguments_json": {"query": "handler.py"},
                        "result_summary": '{"ok":true}',
                        "output_ref": "agent-outputs/a/t.json",
                    },
                    {
                        "id": second_tool_call_id,
                        "turn_id": turn_id,
                        "openai_call_id": "call_read",
                        "tool_name": "read_file",
                        "arguments_json": {"path": "backend/agent/handler.py"},
                        "result_summary": '{"ok":true}',
                        "output_ref": "agent-outputs/a/t.json",
                    },
                ]
            ],
            scalar_values=[0],
        )
        repository = PostgresAgentRepository(connection)

        outputs = await repository.load_ready_tool_outputs_for_turn(turn_id=turn_id)

        self.assertEqual([output["call_id"] for output in outputs], ["call_search", "call_read"])
        self.assertEqual(outputs[0]["id"], first_tool_call_id)
        self.assertEqual(outputs[1]["arguments"], {"path": "backend/agent/handler.py"})
        self.assertIn("ORDER BY tc.created_at, tc.id", str(connection.executed[0][0]))
        self.assertIn("IN ('completed', 'failed', 'denied')", str(connection.executed[0][0]))

    async def test_load_uncompacted_context_items_reads_recent_window_in_chronological_order(self) -> None:
        agent_id = new_uuid7()
        connection = FakeConnection(
            rows=[
                {
                    "seq": 1,
                    "item_type": "function_call",
                    "payload_json": {"type": "function_call", "name": "read_file"},
                    "source": "model",
                    "response_id": "resp_1",
                },
                {
                    "seq": 2,
                    "item_type": "function_call_output",
                    "payload_json": {"type": "function_call_output", "output": '{"ok":true}'},
                    "source": "tool",
                    "response_id": None,
                },
            ]
        )
        repository = PostgresAgentRepository(connection)

        items = await repository.load_uncompacted_context_items(agent_id=agent_id, limit=8)

        self.assertEqual([item["seq"] for item in items], [1, 2])
        self.assertEqual(items[0]["payload_json"]["name"], "read_file")
        statement = str(connection.executed[0][0])
        self.assertIn("FROM agent_context_items", statement)
        self.assertIn("compacted_at IS NULL", statement)
        self.assertIn("ORDER BY seq DESC", statement)
        self.assertIn("ORDER BY recent.seq", statement)
        self.assertEqual(connection.executed[0][1]["agent_id"], agent_id)
        self.assertEqual(connection.executed[0][1]["limit"], 8)

    async def test_compact_context_items_marks_rows_and_writes_memory_summary(self) -> None:
        agent_id = new_uuid7()
        connection = FakeConnection()
        repository = PostgresAgentRepository(connection)

        await repository.compact_context_items(
            agent_id=agent_id,
            compacted_until_seq=12,
            compacted_until_turn=3,
            summary_json={"confirmed_facts": ["已读取 README"]},
            evidence_ids_json=[],
            focus_paths_json=["README.md"],
            next_action="继续读取 src",
        )

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("UPDATE agent_context_items", executed_sql)
        self.assertIn("INSERT INTO memory_summaries", executed_sql)
        update_params = _first_executed_params(connection, "UPDATE agent_context_items")
        summary_params = _first_executed_params(connection, "INSERT INTO memory_summaries")
        self.assertEqual(update_params["agent_id"], agent_id)
        self.assertEqual(update_params["compacted_until_seq"], 12)
        self.assertEqual(summary_params["summary_json"]["confirmed_facts"], ["已读取 README"])

    async def test_save_compacted_context_window_records_replacement_metadata_and_items(self) -> None:
        agent_id = new_uuid7()
        turn_id = new_uuid7()
        connection = FakeConnection(scalar_values=[None, 20, None, 21])
        repository = PostgresAgentRepository(connection)

        await repository.save_compacted_context_window(
            agent_id=agent_id,
            turn_id=turn_id,
            compacted_until_turn=4,
            compaction_id="cmp_1",
            output_json=[
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "retained"}]},
                {"type": "compaction", "id": "cmp_item_1", "encrypted_content": "opaque"},
            ],
            usage_json={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            strategy="remote",
        )

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("INSERT INTO agent_context_windows", executed_sql)
        window_params = _first_executed_params(connection, "INSERT INTO agent_context_windows")
        self.assertEqual(window_params["agent_id"], agent_id)
        self.assertEqual(window_params["turn_id"], turn_id)
        self.assertEqual(window_params["strategy"], "remote")
        self.assertEqual(window_params["compaction_id"], "cmp_1")
        self.assertEqual(window_params["compacted_until_turn"], 4)
        self.assertEqual(window_params["usage_json"]["total_tokens"], 12)
        context_inserts = _executed_params(connection, "INSERT INTO agent_context_items")
        self.assertEqual([params["item_type"] for params in context_inserts], ["message", "compaction"])
        self.assertEqual(context_inserts[1]["idempotency_key"], "model:remote_compaction:cmp_1:1")

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

    def mappings(self) -> FakeResult:
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


def _first_executed_statement(connection: FakeConnection, sql_fragment: str) -> object:
    for statement, _ in connection.executed:
        if sql_fragment in str(statement):
            return statement
    raise AssertionError(f"SQL fragment not executed: {sql_fragment}")


def _executed_params(connection: FakeConnection, sql_fragment: str) -> list[dict]:
    return [params for statement, params in connection.executed if sql_fragment in str(statement)]


if __name__ == "__main__":
    unittest.main()
