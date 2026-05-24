from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from backend.documents import DocumentRepository, DocumentService
from backend.execution import PermissionEngine, SourceToolExecutor, ToolExecutionContext
from backend.config import AppConfig, ToolsConfig
from backend.ids import new_uuid7
from backend.storage import InMemoryObjectStorage


class DocumentToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_document_create_update_get_finalize_delete_and_replay(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        create_call_id = new_uuid7()
        update_call_id = new_uuid7()
        storage = InMemoryObjectStorage()
        documents = DocumentRepository()
        executor = SourceToolExecutor(
            repository=FakeSnapshotRepository(),
            storage=storage,
            cache=FakeCache(),
            permission_engine=PermissionEngine(),
            document_service=DocumentService(repository=documents, storage=storage),
        )
        config = AppConfig(
            tools=ToolsConfig(
                enabled=(
                    "document_create",
                    "document_get",
                    "document_update",
                    "document_delete",
                    "document_finalize",
                )
            )
        )

        created = await executor.execute(
            ToolExecutionContext(
                tool_call_id=create_call_id,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
            ),
            "document_create",
            {"title": "Review", "kind": "markdown", "content": "# Draft\n"},
            config=config,
        )
        replayed = await executor.execute(
            ToolExecutionContext(
                tool_call_id=create_call_id,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
            ),
            "document_create",
            {"title": "Review", "kind": "markdown", "content": "# Draft\n"},
            config=config,
        )

        self.assertTrue(created["ok"])
        self.assertEqual(
            created["scope"],
            {
                "type": "analysis_artifact",
                "analysis_id": str(analysis_id),
                "snapshot_id": str(snapshot_id),
                "document_id": created["result"]["document_id"],
            },
        )
        self.assertEqual(created["result"]["version"], 1)
        self.assertEqual(created["result"]["status"], "draft")
        self.assertEqual(
            created["result"]["content_ref"],
            f"documents/{analysis_id}/{created['result']['document_id']}/v1-{create_call_id}.md",
        )
        self.assertEqual(replayed["result"]["document_id"], created["result"]["document_id"])
        self.assertEqual(len(documents.revisions), 1)
        self.assertEqual(storage.objects[created["result"]["content_ref"]], b"# Draft\n")

        updated = await executor.execute(
            ToolExecutionContext(
                tool_call_id=update_call_id,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
            ),
            "document_update",
            {
                "document_id": created["result"]["document_id"],
                "expected_version": 1,
                "content": "# Final Draft\n",
            },
            config=config,
        )

        self.assertTrue(updated["ok"])
        self.assertEqual(updated["result"]["version"], 2)
        self.assertEqual(
            updated["result"]["content_ref"],
            f"documents/{analysis_id}/{created['result']['document_id']}/v2-{update_call_id}.md",
        )
        self.assertEqual(storage.objects[updated["result"]["content_ref"]], b"# Final Draft\n")

        fetched = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
            ),
            "document_get",
            {"document_id": created["result"]["document_id"], "include_content": True},
            config=config,
        )

        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["result"]["content"], "# Final Draft\n")

        finalized = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
            ),
            "document_finalize",
            {"document_id": created["result"]["document_id"], "expected_version": 2},
            config=config,
        )

        self.assertTrue(finalized["ok"])
        self.assertEqual(finalized["result"]["status"], "finalized")
        self.assertEqual(finalized["result"]["version"], 3)

        rejected_update = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
            ),
            "document_update",
            {
                "document_id": created["result"]["document_id"],
                "expected_version": 3,
                "content": "late edit",
            },
            config=config,
        )
        rejected_delete = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
            ),
            "document_delete",
            {"document_id": created["result"]["document_id"], "expected_version": 3},
            config=config,
        )

        self.assertFalse(rejected_update["ok"])
        self.assertEqual(rejected_update["error"]["code"], "DOCUMENT_FINALIZED")
        self.assertFalse(rejected_delete["ok"])
        self.assertEqual(rejected_delete["error"]["code"], "DOCUMENT_FINALIZED")

    async def test_document_tool_call_replay_returns_revision_version_not_current_document(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        create_call_id = new_uuid7()
        update_call_id = new_uuid7()
        second_update_call_id = new_uuid7()
        storage = InMemoryObjectStorage()
        documents = DocumentRepository()
        executor = SourceToolExecutor(
            repository=FakeSnapshotRepository(),
            storage=storage,
            cache=FakeCache(),
            permission_engine=PermissionEngine(),
            document_service=DocumentService(repository=documents, storage=storage),
        )
        config = AppConfig(tools=ToolsConfig(enabled=("document_create", "document_update")))

        created = await executor.execute(
            ToolExecutionContext(create_call_id, agent_id, snapshot_id, analysis_id),
            "document_create",
            {"title": "Review", "kind": "markdown", "content": "# v1\n"},
            config=config,
        )
        first_update = await executor.execute(
            ToolExecutionContext(update_call_id, agent_id, snapshot_id, analysis_id),
            "document_update",
            {"document_id": created["result"]["document_id"], "expected_version": 1, "content": "# v2\n"},
            config=config,
        )
        await executor.execute(
            ToolExecutionContext(second_update_call_id, agent_id, snapshot_id, analysis_id),
            "document_update",
            {"document_id": created["result"]["document_id"], "expected_version": 2, "content": "# v3\n"},
            config=config,
        )

        replayed_first_update = await executor.execute(
            ToolExecutionContext(update_call_id, agent_id, snapshot_id, analysis_id),
            "document_update",
            {"document_id": created["result"]["document_id"], "expected_version": 1, "content": "# v2\n"},
            config=config,
        )

        self.assertEqual(first_update["result"]["version"], 2)
        self.assertEqual(replayed_first_update["result"]["version"], 2)
        self.assertEqual(replayed_first_update["result"]["content_ref"], first_update["result"]["content_ref"])

    async def test_document_finalize_reports_conflict_when_atomic_update_loses_race(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        document_id = new_uuid7()
        now = datetime.now(UTC)
        repository = DocumentRepository()
        repository.documents[document_id] = {
            "id": document_id,
            "analysis_id": analysis_id,
            "agent_id": agent_id,
            "title": "Review",
            "kind": "markdown",
            "status": "draft",
            "current_version": 1,
            "content_ref": "documents/a/doc/v1-call.md",
            "content_hash": "sha256:abc",
            "size_bytes": 12,
            "created_at": now,
            "updated_at": now,
            "finalized_at": None,
        }

        async def losing_update(document_id, updates, revision):
            return None

        repository.update_document_with_revision = losing_update
        service = DocumentService(repository=repository, storage=InMemoryObjectStorage())

        with self.assertRaisesRegex(Exception, "Document version does not match"):
            await service.finalize(
                analysis_id=analysis_id,
                tool_call_id=new_uuid7(),
                document_id=document_id,
                expected_version=1,
            )

    async def test_document_delete_and_finalize_reject_stale_expected_version(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        storage = InMemoryObjectStorage()
        documents = DocumentRepository()
        executor = SourceToolExecutor(
            repository=FakeSnapshotRepository(),
            storage=storage,
            cache=FakeCache(),
            permission_engine=PermissionEngine(),
            document_service=DocumentService(repository=documents, storage=storage),
        )
        config = AppConfig(tools=ToolsConfig(enabled=("document_create", "document_update", "document_delete", "document_finalize")))

        created = await executor.execute(
            ToolExecutionContext(new_uuid7(), agent_id, snapshot_id, analysis_id),
            "document_create",
            {"title": "Review", "kind": "markdown", "content": "# v1\n"},
            config=config,
        )
        await executor.execute(
            ToolExecutionContext(new_uuid7(), agent_id, snapshot_id, analysis_id),
            "document_update",
            {"document_id": created["result"]["document_id"], "expected_version": 1, "content": "# v2\n"},
            config=config,
        )

        stale_delete = await executor.execute(
            ToolExecutionContext(new_uuid7(), agent_id, snapshot_id, analysis_id),
            "document_delete",
            {"document_id": created["result"]["document_id"], "expected_version": 1},
            config=config,
        )
        stale_finalize = await executor.execute(
            ToolExecutionContext(new_uuid7(), agent_id, snapshot_id, analysis_id),
            "document_finalize",
            {"document_id": created["result"]["document_id"], "expected_version": 1},
            config=config,
        )

        self.assertFalse(stale_delete["ok"])
        self.assertEqual(stale_delete["error"]["code"], "DOCUMENT_VERSION_CONFLICT")
        self.assertFalse(stale_finalize["ok"])
        self.assertEqual(stale_finalize["error"]["code"], "DOCUMENT_VERSION_CONFLICT")
        current = await documents.get_document(UUID(created["result"]["document_id"]))
        self.assertEqual(current["status"], "draft")
        self.assertEqual(current["current_version"], 2)

    async def test_document_delete_soft_deletes_draft(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        storage = InMemoryObjectStorage()
        documents = DocumentRepository()
        executor = SourceToolExecutor(
            repository=FakeSnapshotRepository(),
            storage=storage,
            cache=FakeCache(),
            permission_engine=PermissionEngine(),
            document_service=DocumentService(repository=documents, storage=storage),
        )
        config = AppConfig(tools=ToolsConfig(enabled=("document_create", "document_delete", "document_get")))
        context = ToolExecutionContext(
            tool_call_id=new_uuid7(),
            analysis_id=analysis_id,
            agent_id=agent_id,
            snapshot_id=new_uuid7(),
        )

        created = await executor.execute(context, "document_create", {"title": "Scratch", "content": "draft"}, config=config)
        deleted = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=new_uuid7(),
            ),
            "document_delete",
            {"document_id": created["result"]["document_id"], "expected_version": 1},
            config=config,
        )

        self.assertTrue(deleted["ok"])
        self.assertEqual(deleted["result"]["status"], "deleted")

    async def test_document_create_rejects_non_markdown_kind(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        executor = SourceToolExecutor(
            repository=FakeSnapshotRepository(),
            storage=InMemoryObjectStorage(),
            cache=FakeCache(),
            permission_engine=PermissionEngine(),
            document_service=DocumentService(repository=DocumentRepository(), storage=InMemoryObjectStorage()),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=new_uuid7(),
            ),
            "document_create",
            {"title": "Notes", "kind": "html", "content": "<h1>Notes</h1>"},
            config=AppConfig(tools=ToolsConfig(enabled=("document_create",))),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")


class FakeSnapshotRepository:
    pass


class FakeCache:
    pass


if __name__ == "__main__":
    unittest.main()
