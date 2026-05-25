from __future__ import annotations

import unittest
from datetime import UTC, datetime

from backend.api.services import PostgresAnalysisService
from backend.config import AppConfig, OpenAIConfig
from backend.events import EventEnvelope, EventType
from backend.execution import DEFAULT_TOOL_REGISTRY_VERSION
from backend.ids import new_uuid7


class PostgresAnalysisServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_persists_analysis_session_config_and_outbox_in_one_transaction(self) -> None:
        database = FakeDatabase()
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")

        record = await service.create(
            repository_url="https://github.com/example/project.git",
            requested_ref="main",
            analysis_profile_id=None,
        )

        self.assertEqual(database.begin_count, 1)
        self.assertEqual(database.committed_count, 1)
        executed_sql = "\n".join(str(statement) for statement, _ in database.connection.executed)
        self.assertIn("INSERT INTO config_snapshots", executed_sql)
        self.assertIn("INSERT INTO analyses", executed_sql)
        self.assertIn("INSERT INTO agent_sessions", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)

        outbox_params = database.connection.executed[-1][1]
        event = EventEnvelope.from_json_value(outbox_params["payload_json"])
        self.assertEqual(event.event_type, EventType.ANALYSIS_REQUESTED)
        self.assertEqual(event.analysis_id, record.analysis_id)
        self.assertEqual(event.agent_id, record.agent_id)
        self.assertEqual(event.payload["repository_url"], "https://github.com/example/project.git")
        self.assertEqual(event.payload["requested_ref"], "main")
        self.assertIn("config_snapshot_id", event.payload)

        self.assertEqual(record.status, "queued")
        self.assertEqual(record.snapshot_id, None)
        self.assertEqual(record.repository_url, "https://github.com/example/project.git")

    async def test_create_uses_semantic_default_versions(self) -> None:
        database = FakeDatabase()
        service = PostgresAnalysisService(database, config=AppConfig.default())

        await service.create(
            repository_url="https://github.com/example/project.git",
            requested_ref="main",
            analysis_profile_id=None,
        )

        config_snapshot_params = database.connection.executed[0][1]
        agent_session_params = database.connection.executed[2][1]
        self.assertEqual(config_snapshot_params["config_version"], "repository-analysis-config-v1")
        self.assertEqual(agent_session_params["effective_prompt_version"], "repository-analysis-config-v1")
        self.assertEqual(agent_session_params["effective_tool_registry_version"], DEFAULT_TOOL_REGISTRY_VERSION)

    async def test_create_persists_reasoning_summary_runtime_settings(self) -> None:
        database = FakeDatabase()
        service = PostgresAnalysisService(
            database,
            config=AppConfig(
                openai=OpenAIConfig(
                    reasoning_summary="detailed",
                    show_reasoning_summary=False,
                    transport="websocket_v2",
                )
            ),
        )

        await service.create(
            repository_url="https://github.com/example/project.git",
            requested_ref="main",
            analysis_profile_id=None,
        )

        agent_session_params = database.connection.executed[2][1]
        self.assertEqual(agent_session_params["effective_runtime_json"]["reasoning_summary"], "detailed")
        self.assertFalse(agent_session_params["effective_runtime_json"]["show_reasoning_summary"])
        self.assertEqual(agent_session_params["effective_runtime_json"]["transport"], "websocket_v2")

    async def test_cancel_updates_analysis_and_session_then_writes_outbox_event(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        database = FakeDatabase(
            rows=[
                {
                    "analysis_id": analysis_id,
                    "agent_id": agent_id,
                    "snapshot_id": None,
                    "status": "queued",
                    "repository_url": "https://github.com/example/project.git",
                    "requested_ref": "main",
                    "resolved_commit_sha": None,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            ]
        )
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")

        record = await service.cancel(analysis_id)

        self.assertIsNotNone(record)
        self.assertEqual(record.status, "cancelling")
        executed_sql = "\n".join(str(statement) for statement, _ in database.connection.executed)
        self.assertIn("UPDATE analyses", executed_sql)
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertIn("UPDATE tool_calls", executed_sql)
        self.assertIn("status = 'cancelled'", executed_sql)
        self.assertIn("permission_decision = 'deny'", executed_sql)
        self.assertNotIn("COALESCE(permission_decision, 'deny')", executed_sql)
        self.assertIn("INSERT INTO outbox_events", executed_sql)

        outbox_params = database.connection.executed[-1][1]
        event = EventEnvelope.from_json_value(outbox_params["payload_json"])
        self.assertEqual(event.event_type, EventType.ANALYSIS_CANCEL_REQUESTED)
        self.assertEqual(event.analysis_id, analysis_id)
        self.assertEqual(event.agent_id, agent_id)

    async def test_cancel_does_not_publish_when_terminal_update_lost_race(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        database = FakeDatabase(
            rows=[
                {
                    "analysis_id": analysis_id,
                    "agent_id": agent_id,
                    "snapshot_id": None,
                    "status": "queued",
                    "repository_url": "https://github.com/example/project.git",
                    "requested_ref": "main",
                    "resolved_commit_sha": None,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            ],
            cancel_update_rows=[],
        )
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")

        record = await service.cancel(analysis_id)

        self.assertIsNotNone(record)
        executed_sql = "\n".join(str(statement) for statement, _ in database.connection.executed)
        self.assertIn("status NOT IN ('completed', 'failed', 'cancelled')", executed_sql)
        self.assertNotIn("INSERT INTO outbox_events", executed_sql)
        self.assertNotIn("UPDATE tool_calls", executed_sql)

    async def test_get_reads_resolved_commit_sha_from_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        database = FakeDatabase(
            rows=[
                {
                    "analysis_id": analysis_id,
                    "agent_id": agent_id,
                    "snapshot_id": snapshot_id,
                    "status": "running",
                    "repository_url": "https://github.com/example/project.git",
                    "requested_ref": "main",
                    "resolved_commit_sha": "abc123",
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            ]
        )
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")

        record = await service.get(analysis_id)

        self.assertIsNotNone(record)
        self.assertEqual(record.resolved_commit_sha, "abc123")
        executed_sql = "\n".join(str(statement) for statement, _ in database.connection.executed)
        self.assertIn("LEFT JOIN snapshots", executed_sql)
        self.assertIn("snap.resolved_commit_sha", executed_sql)

    async def test_list_accepts_cursor_repository_hash_and_time_filters(self) -> None:
        database = FakeDatabase()
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")
        created_after = datetime(2026, 5, 22, tzinfo=UTC)
        created_before = datetime(2026, 5, 23, tzinfo=UTC)

        await service.list(
            status="running",
            repository_url_hash="sha256:repo",
            created_after=created_after,
            created_before=created_before,
            limit=10,
            cursor="2026-05-22T00:00:00+00:00|019e505e-df2b-7e6f-9a5e-141aa98f59da",
        )

        statement, params = database.connection.executed[-1]
        sql = str(statement)
        self.assertIn("a.repository_url_hash = :repository_url_hash", sql)
        self.assertIn("a.created_at >= :created_after", sql)
        self.assertIn("a.created_at < :created_before", sql)
        self.assertIn("(a.created_at, a.id) < (:cursor_created_at, :cursor_id)", sql)
        self.assertIn("ORDER BY a.created_at DESC, a.id DESC", sql)
        self.assertEqual(params["repository_url_hash"], "sha256:repo")
        self.assertEqual(params["limit"], 10)

    async def test_suggest_by_repository_query_uses_prefix_match_for_github_shorthand(self) -> None:
        database = FakeDatabase()
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")

        await service.suggest(repository_query="openai/codex", limit=6)

        statement, params = database.connection.executed[-1]
        sql = str(statement)
        self.assertIn("a.repository_url LIKE :repository_url_prefix", sql)
        self.assertIn("ORDER BY a.updated_at DESC, a.created_at DESC, a.id DESC", sql)
        self.assertIn("LIMIT :limit", sql)
        self.assertEqual(params["repository_url_prefix"], "https://github.com/openai/codex%")
        self.assertEqual(params["limit"], 6)

    async def test_suggest_by_repository_query_uses_hash_for_full_git_url(self) -> None:
        database = FakeDatabase()
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")

        await service.suggest(repository_query="https://github.com/openai/codex.git", limit=6)

        statement, params = database.connection.executed[-1]
        sql = str(statement)
        self.assertIn("a.repository_url_hash = :repository_url_hash", sql)
        self.assertIn("LIMIT :limit", sql)
        self.assertEqual(
            params["repository_url_hash"], "sha256:105fd62fe5d54a91904a74b56a979a5e9a9245a42108ebb5440bf9adfc688744"
        )

    async def test_suggest_by_repository_query_uses_prefix_match_for_partial_input(self) -> None:
        database = FakeDatabase()
        service = PostgresAnalysisService(database, config=AppConfig.default(), config_version="config-fixture-v1")

        await service.suggest(repository_query="openai/co", limit=6)

        statement, params = database.connection.executed[-1]
        sql = str(statement)
        self.assertIn("a.repository_url LIKE :repository_url_prefix", sql)
        self.assertIn("ORDER BY a.updated_at DESC, a.created_at DESC, a.id DESC", sql)
        self.assertIn("LIMIT :limit", sql)
        self.assertEqual(params["repository_url_prefix"], "https://github.com/openai/co%")
        self.assertEqual(params["limit"], 6)


class FakeDatabase:
    def __init__(self, *, rows: list[dict] | None = None, cancel_update_rows: list[dict] | None = None) -> None:
        self.connection = FakeConnection(rows=rows, cancel_update_rows=cancel_update_rows)
        self.begin_count = 0
        self.committed_count = 0

    def begin(self) -> FakeTransaction:
        self.begin_count += 1
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, database: FakeDatabase) -> None:
        self._database = database

    async def __aenter__(self) -> FakeConnection:
        return self._database.connection

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self._database.committed_count += 1


class FakeConnection:
    def __init__(self, *, rows: list[dict] | None = None, cancel_update_rows: list[dict] | None = None) -> None:
        self._rows = rows or []
        self._cancel_update_rows = cancel_update_rows
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if statement_text.lstrip().startswith("SELECT"):
            return FakeResult(self._rows)
        if "UPDATE analyses" in statement_text and params and params.get("status") == "cancelling":
            if self._cancel_update_rows is not None:
                return FakeResult(self._cancel_update_rows)
            return FakeResult([{"id": params["analysis_id"]}])
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


if __name__ == "__main__":
    unittest.main()
