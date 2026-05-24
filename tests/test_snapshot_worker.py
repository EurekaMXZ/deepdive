from __future__ import annotations

import unittest

from backend.config import AppConfig
from backend.events import EventEnvelope, EventType
from backend.ids import new_uuid7
from backend.snapshot import (
    SnapshotBuildError,
    SnapshotBuildResult,
    SnapshotFileRecord,
    SnapshotInstructionRecord,
)
from backend.workers.snapshot import SnapshotCommandHandler

_DEFAULT_CONFIG_SNAPSHOT = object()


class SnapshotWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_requested_persists_snapshot_and_emits_ready_event(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        connection = FakeConnection()
        database = FakeDatabase(connection)
        builder = FakeBuilder(
            SnapshotBuildResult(
                snapshot_id=snapshot_id,
                repository_url_hash="sha256:" + "a" * 64,
                requested_ref="main",
                resolved_commit_sha="b" * 40,
                tree_sha="c" * 40,
                snapshot_policy_hash="sha256:" + "d" * 64,
                manifest_key=f"snapshots/{snapshot_id}/manifest.json.zst",
                git_bundle_key=f"git-bundles/{'a' * 64}/{'b' * 40}.bundle",
                tree_text_key=f"snapshots/{snapshot_id}/tree.txt",
                file_tree_key=f"snapshots/{snapshot_id}/file-tree.json.zst",
                file_count=1,
                total_bytes=14,
                files=[
                    SnapshotFileRecord(
                        path="backend/app.py",
                        path_hash="sha256:" + "1" * 64,
                        parent_path="backend",
                        name="app.py",
                        entry_kind="file",
                        git_mode="100644",
                        git_blob_oid="e" * 40,
                        content_key="blobs/sha256/11/11/" + "1" * 64,
                        content_hash="sha256:" + "1" * 64,
                        size_bytes=14,
                        line_count=1,
                        is_binary=False,
                        is_large=False,
                    )
                ],
                instructions=[
                    SnapshotInstructionRecord(
                        path="AGENTS.md",
                        scope_path="",
                        depth=0,
                        content_hash="sha256:" + "2" * 64,
                        content_ref=f"instructions/{snapshot_id}/{'2' * 64}.md",
                    )
                ],
            )
        )
        handler = SnapshotCommandHandler(database=database, builder=builder)
        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload=_snapshot_payload(),
        )

        await handler(event)

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("INSERT INTO snapshots", executed_sql)
        self.assertIn("INSERT INTO snapshot_files", executed_sql)
        self.assertIn("INSERT INTO agent_instruction_files", executed_sql)
        self.assertIn("UPDATE agent_sessions", executed_sql)
        self.assertEqual(builder.requests[0].repository_url, "https://github.com/example/project.git")
        self.assertEqual(builder.requests[0].requested_ref, "main")

        outbox_events = _outbox_events(connection)
        self.assertEqual(
            [event.event_type for event in outbox_events], [EventType.SNAPSHOT_STARTED, EventType.SNAPSHOT_READY]
        )
        self.assertEqual(outbox_events[-1].snapshot_id, snapshot_id)
        self.assertEqual(outbox_events[-1].payload["resolved_commit_sha"], "b" * 40)

    async def test_snapshot_requested_uses_snapshot_config_from_config_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        config_snapshot_id = new_uuid7()
        connection = FakeConnection(
            config_snapshot_json={
                "snapshot": {
                    "max_file_bytes": 2048,
                    "lfs_policy": "metadata_only",
                    "submodule_policy": "skip",
                    "binary_policy": "skip",
                }
            }
        )
        database = FakeDatabase(connection)
        builder = FakeBuilder(_build_result())
        handler = SnapshotCommandHandler(database=database, builder=builder)

        await handler(
            EventEnvelope.new(
                event_type=EventType.SNAPSHOT_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={
                    "repository_url": "https://github.com/example/project.git",
                    "requested_ref": "main",
                    "config_snapshot_id": str(config_snapshot_id),
                },
            )
        )

        request = builder.requests[0]
        self.assertEqual(request.policy.max_file_bytes, 2048)
        self.assertEqual(request.policy.lfs_policy, "metadata_only")
        self.assertEqual(request.policy.submodule_policy, "skip")
        self.assertEqual(request.policy.binary_policy, "skip")
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("FROM config_snapshots", executed_sql)

    async def test_snapshot_requested_fails_when_config_snapshot_id_is_missing(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection()
        database = FakeDatabase(connection)
        builder = FakeBuilder(_build_result())
        handler = SnapshotCommandHandler(database=database, builder=builder)

        await handler(
            EventEnvelope.new(
                event_type=EventType.SNAPSHOT_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={"repository_url": "https://github.com/example/project.git", "requested_ref": "main"},
            )
        )

        self.assertEqual(builder.requests, [])
        outbox_events = _outbox_events(connection)
        self.assertEqual(
            [event.event_type for event in outbox_events], [EventType.SNAPSHOT_STARTED, EventType.SNAPSHOT_FAILED]
        )
        self.assertEqual(outbox_events[-1].payload["error_code"], "CONFIG_SNAPSHOT_REQUIRED")
        stream_events = _stream_events(connection)
        self.assertEqual(stream_events[-1]["payload_json"]["error_code"], "CONFIG_SNAPSHOT_REQUIRED")

    async def test_snapshot_requested_fails_when_config_snapshot_is_not_found(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        config_snapshot_id = new_uuid7()
        connection = FakeConnection(config_snapshot_json=None)
        database = FakeDatabase(connection)
        builder = FakeBuilder(_build_result())
        handler = SnapshotCommandHandler(database=database, builder=builder)

        await handler(
            EventEnvelope.new(
                event_type=EventType.SNAPSHOT_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                payload={
                    "repository_url": "https://github.com/example/project.git",
                    "requested_ref": "main",
                    "config_snapshot_id": str(config_snapshot_id),
                },
            )
        )

        self.assertEqual(builder.requests, [])
        outbox_events = _outbox_events(connection)
        self.assertEqual(
            [event.event_type for event in outbox_events], [EventType.SNAPSHOT_STARTED, EventType.SNAPSHOT_FAILED]
        )
        self.assertEqual(outbox_events[-1].payload["error_code"], "CONFIG_SNAPSHOT_NOT_FOUND")
        stream_events = _stream_events(connection)
        self.assertEqual(stream_events[-1]["payload_json"]["error_code"], "CONFIG_SNAPSHOT_NOT_FOUND")

    async def test_snapshot_requested_reuses_existing_ready_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        existing_snapshot_id = new_uuid7()
        connection = FakeConnection(
            existing_snapshot={
                "id": existing_snapshot_id,
                "manifest_key": f"snapshots/{existing_snapshot_id}/manifest.json.zst",
                "git_bundle_key": "git-bundles/repo/commit.bundle",
                "resolved_commit_sha": "b" * 40,
                "tree_sha": "c" * 40,
                "file_count": 3,
            }
        )
        database = FakeDatabase(connection)
        builder = FakeBuilder(_build_result(snapshot_id=new_uuid7()))
        handler = SnapshotCommandHandler(database=database, builder=builder)
        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload=_snapshot_payload(),
        )

        await handler(event)

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertNotIn("INSERT INTO snapshots", executed_sql)
        ready_event = _outbox_events(connection)[-1]
        self.assertEqual(ready_event.event_type, EventType.SNAPSHOT_READY)
        self.assertEqual(ready_event.snapshot_id, existing_snapshot_id)
        self.assertTrue(ready_event.payload["reused_existing_snapshot"])

    async def test_snapshot_ready_does_not_reactivate_cancelled_analysis(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        connection = FakeConnection(associate_snapshot_rows=[])
        database = FakeDatabase(connection)
        builder = FakeBuilder(_build_result(snapshot_id=snapshot_id))
        handler = SnapshotCommandHandler(database=database, builder=builder)
        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload=_snapshot_payload(),
        )

        await handler(event)

        outbox_events = _outbox_events(connection)
        self.assertEqual([event.event_type for event in outbox_events], [EventType.SNAPSHOT_STARTED])

    async def test_snapshot_requested_does_not_start_when_analysis_is_cancelling(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(mark_snapshotting_rows=[])
        database = FakeDatabase(connection)
        builder = FakeBuilder(_build_result())
        handler = SnapshotCommandHandler(database=database, builder=builder)
        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload=_snapshot_payload(),
        )

        await handler(event)

        self.assertEqual(builder.requests, [])
        self.assertEqual(_outbox_events(connection), [])

    async def test_snapshot_requested_does_not_start_when_session_already_has_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(mark_snapshotting_rows=[])
        database = FakeDatabase(connection)
        builder = FakeBuilder(_build_result())
        handler = SnapshotCommandHandler(database=database, builder=builder)
        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload=_snapshot_payload(),
        )

        await handler(event)

        self.assertEqual(builder.requests, [])
        self.assertEqual(_outbox_events(connection), [])
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("s.snapshot_id IS NULL", executed_sql)
        self.assertIn("a.status = 'snapshotting'", executed_sql)

    async def test_snapshot_requested_marks_analysis_failed_when_build_fails(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection()
        database = FakeDatabase(connection)
        handler = SnapshotCommandHandler(
            database=database,
            builder=FailingBuilder(SnapshotBuildError("GitCommandFailed", "clone failed")),
        )
        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload=_snapshot_payload(),
        )

        await handler(event)

        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("error_code = :error_code", executed_sql)
        self.assertIn("completed_at = :completed_at", executed_sql)
        outbox_events = _outbox_events(connection)
        self.assertEqual(outbox_events[-1].event_type, EventType.SNAPSHOT_FAILED)
        self.assertEqual(outbox_events[-1].payload["error_code"], "GitCommandFailed")
        stream_events = _stream_events(connection)
        self.assertEqual(stream_events[-1]["event_type"], "error")
        self.assertEqual(stream_events[-1]["payload_json"]["error_code"], "GitCommandFailed")

    async def test_snapshot_build_failure_after_cancel_does_not_emit_failure_events(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        connection = FakeConnection(mark_failed_rows=[])
        database = FakeDatabase(connection)
        handler = SnapshotCommandHandler(
            database=database,
            builder=FailingBuilder(SnapshotBuildError("GitCommandFailed", "clone failed")),
        )
        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_REQUESTED,
            analysis_id=analysis_id,
            agent_id=agent_id,
            payload=_snapshot_payload(),
        )

        await handler(event)

        self.assertEqual(
            [event.event_type for event in _outbox_events(connection)],
            [EventType.SNAPSHOT_STARTED],
        )
        self.assertEqual(_stream_events(connection), [])

    async def test_unsupported_event_is_rejected(self) -> None:
        handler = SnapshotCommandHandler(database=FakeDatabase(FakeConnection()), builder=FakeBuilder(_build_result()))

        with self.assertRaisesRegex(ValueError, "Unsupported snapshot command"):
            await handler(EventEnvelope.new(event_type=EventType.ANALYSIS_REQUESTED, analysis_id=new_uuid7()))


class FakeDatabase:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self.connection)


class FakeTransaction:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeConnection:
    def __init__(
        self,
        *,
        existing_snapshot: dict | None = None,
        associate_snapshot_rows: list[dict] | None = None,
        mark_snapshotting_rows: list[dict] | None = None,
        mark_failed_rows: list[dict] | None = None,
        config_snapshot_json: dict | None | object = _DEFAULT_CONFIG_SNAPSHOT,
    ) -> None:
        self.existing_snapshot = existing_snapshot
        self.associate_snapshot_rows = associate_snapshot_rows
        self.mark_snapshotting_rows = mark_snapshotting_rows
        self.mark_failed_rows = mark_failed_rows
        self.config_snapshot_json = (
            AppConfig.default().to_json_dict()
            if config_snapshot_json is _DEFAULT_CONFIG_SNAPSHOT
            else config_snapshot_json
        )
        self.executed = []
        self.scalar_calls = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        statement_text = str(statement)
        if "FROM config_snapshots" in statement_text:
            return FakeResult(
                [{"config_json": self.config_snapshot_json}] if self.config_snapshot_json is not None else []
            )
        if "SELECT id, manifest_key" in statement_text:
            return FakeResult([self.existing_snapshot] if self.existing_snapshot else [])
        if (
            "UPDATE agent_sessions" in statement_text
            and "snapshot_id = :snapshot_id" in statement_text
            and "RETURNING id" in statement_text
        ):
            return FakeResult(
                self.associate_snapshot_rows
                if self.associate_snapshot_rows is not None
                else [{"id": params.get("agent_id")}]
            )
        if "RETURNING tenant_id" in statement_text or "RETURNING a.tenant_id" in statement_text:
            return FakeResult(
                self.mark_snapshotting_rows if self.mark_snapshotting_rows is not None else [{"tenant_id": None}]
            )
        if "UPDATE analyses" in statement_text and "error_code = :error_code" in statement_text:
            return FakeResult(
                self.mark_failed_rows if self.mark_failed_rows is not None else [{"id": params.get("analysis_id")}]
            )
        return FakeResult([])

    async def scalar(self, statement, params=None):
        self.scalar_calls.append((statement, params or {}))
        if "COALESCE(MAX(seq)" in str(statement):
            return 1
        return None


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> FakeResult:
        return self

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict]:
        return self._rows


class FakeBuilder:
    def __init__(self, result: SnapshotBuildResult) -> None:
        self.result = result
        self.requests = []

    def build(self, request):
        self.requests.append(request)
        return self.result


class FailingBuilder:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def build(self, request):
        raise self.error


def _build_result(*, snapshot_id=None) -> SnapshotBuildResult:
    snapshot_id = snapshot_id or new_uuid7()
    return SnapshotBuildResult(
        snapshot_id=snapshot_id,
        repository_url_hash="sha256:" + "a" * 64,
        requested_ref="main",
        resolved_commit_sha="b" * 40,
        tree_sha="c" * 40,
        snapshot_policy_hash="sha256:" + "d" * 64,
        manifest_key=f"snapshots/{snapshot_id}/manifest.json.zst",
        git_bundle_key=f"git-bundles/{'a' * 64}/{'b' * 40}.bundle",
        tree_text_key=f"snapshots/{snapshot_id}/tree.txt",
        file_tree_key=f"snapshots/{snapshot_id}/file-tree.json.zst",
        file_count=0,
        total_bytes=0,
        files=[],
        instructions=[],
    )


def _snapshot_payload(*, config_snapshot_id=None) -> dict:
    return {
        "repository_url": "https://github.com/example/project.git",
        "requested_ref": "main",
        "config_snapshot_id": str(config_snapshot_id or new_uuid7()),
    }


def _outbox_events(connection: FakeConnection) -> list[EventEnvelope]:
    return [
        EventEnvelope.from_json_value(params["payload_json"])
        for statement, params in connection.executed
        if "INSERT INTO outbox_events" in str(statement)
    ]


def _stream_events(connection: FakeConnection) -> list[dict]:
    return [params for statement, params in connection.executed if "INSERT INTO agent_stream_events" in str(statement)]


if __name__ == "__main__":
    unittest.main()
