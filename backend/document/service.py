from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from backend.document.errors import DocumentToolError
from backend.document.models import (
    coerce_uuid,
    content_hash,
    document_result,
    revision_payload,
    revision_result,
    status_for_revision,
)
from backend.document.store import DocumentStore
from backend.ids import new_uuid7
from backend.storage import ObjectStorage, document_content_key


class DocumentService:
    def __init__(self, *, repository: DocumentStore, storage: ObjectStorage) -> None:
        self._repository = repository
        self._storage = storage

    async def create(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        tool_call_id: UUID,
        title: str,
        kind: str,
        content: str,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        agent_id = coerce_uuid(agent_id)
        tool_call_id = coerce_uuid(tool_call_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay

        now = datetime.now(UTC)
        document_id = new_uuid7()
        version = 1
        content_bytes = content.encode("utf-8")
        digest = content_hash(content_bytes)
        content_ref = document_content_key(analysis_id, document_id, version, tool_call_id)
        self._storage.put_bytes(content_ref, content_bytes, content_type="text/markdown; charset=utf-8")
        document = {
            "id": document_id,
            "analysis_id": analysis_id,
            "agent_id": agent_id,
            "title": title,
            "kind": kind,
            "status": "draft",
            "current_version": version,
            "content_ref": content_ref,
            "content_hash": digest,
            "size_bytes": len(content_bytes),
            "created_at": now,
            "updated_at": now,
            "finalized_at": None,
        }
        revision = revision_payload(
            document_id, version, tool_call_id, "create", content_ref, digest, len(content_bytes), now
        )
        await self._repository.add_document_with_revision(document, revision)
        return document_result(document)

    async def get(self, *, analysis_id: UUID, document_id: UUID, include_content: bool) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        document_id = coerce_uuid(document_id)
        document = await self._document_for_analysis(analysis_id, document_id)
        result = document_result(document)
        if include_content:
            result["content"] = self._storage.get_bytes(document["content_ref"]).decode("utf-8")
        return result

    async def list(self, *, analysis_id: UUID, limit: int = 50, cursor: str | None = None) -> list[dict[str, Any]]:
        analysis_id = coerce_uuid(analysis_id)
        documents = await self._repository.list_documents(analysis_id, limit=limit, cursor=cursor)
        return [document_result(document) for document in documents]

    async def list_revisions(
        self, *, analysis_id: UUID, document_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        analysis_id = coerce_uuid(analysis_id)
        document_id = coerce_uuid(document_id)
        document = await self._document_for_analysis(analysis_id, document_id)
        revisions = await self._repository.list_revisions(UUID(str(document["id"])), limit=limit, cursor=cursor)
        return [revision_result(revision) for revision in revisions]

    async def update(
        self,
        *,
        analysis_id: UUID,
        tool_call_id: UUID,
        document_id: UUID,
        expected_version: int,
        content: str,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        tool_call_id = coerce_uuid(tool_call_id)
        document_id = coerce_uuid(document_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay

        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")

        version = expected_version + 1
        now = datetime.now(UTC)
        content_bytes = content.encode("utf-8")
        digest = content_hash(content_bytes)
        content_ref = document_content_key(analysis_id, document_id, version, tool_call_id)
        self._storage.put_bytes(content_ref, content_bytes, content_type="text/markdown; charset=utf-8")
        updates = {
            "expected_version": expected_version,
            "expected_status": "draft",
            "status": "draft",
            "current_version": version,
            "content_ref": content_ref,
            "content_hash": digest,
            "size_bytes": len(content_bytes),
            "updated_at": now,
            "finalized_at": None,
        }
        revision = revision_payload(
            document_id, version, tool_call_id, "update", content_ref, digest, len(content_bytes), now
        )
        updated = await self._repository.update_document_with_revision(document_id, updates, revision)
        if updated is None:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        return document_result(updated)

    async def delete(
        self, *, analysis_id: UUID, tool_call_id: UUID, document_id: UUID, expected_version: int
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        tool_call_id = coerce_uuid(tool_call_id)
        document_id = coerce_uuid(document_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay
        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        now = datetime.now(UTC)
        version = expected_version + 1
        revision = revision_payload(
            document_id,
            version,
            tool_call_id,
            "delete",
            document["content_ref"],
            document["content_hash"],
            int(document["size_bytes"]),
            now,
        )
        updated = await self._repository.update_document_with_revision(
            document_id,
            {
                "expected_version": expected_version,
                "expected_status": "draft",
                "status": "deleted",
                "current_version": version,
                "content_ref": document["content_ref"],
                "content_hash": document["content_hash"],
                "size_bytes": int(document["size_bytes"]),
                "updated_at": now,
                "finalized_at": None,
            },
            revision,
        )
        if updated is None:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        return document_result(updated)

    async def finalize(
        self,
        *,
        analysis_id: UUID,
        tool_call_id: UUID,
        document_id: UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        tool_call_id = coerce_uuid(tool_call_id)
        document_id = coerce_uuid(document_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay
        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        now = datetime.now(UTC)
        version = expected_version + 1
        revision = revision_payload(
            document_id,
            version,
            tool_call_id,
            "finalize",
            document["content_ref"],
            document["content_hash"],
            int(document["size_bytes"]),
            now,
        )
        updated = await self._repository.update_document_with_revision(
            document_id,
            {
                "expected_version": expected_version,
                "expected_status": "draft",
                "status": "finalized",
                "current_version": version,
                "content_ref": document["content_ref"],
                "content_hash": document["content_hash"],
                "size_bytes": int(document["size_bytes"]),
                "updated_at": now,
                "finalized_at": now,
            },
            revision,
        )
        if updated is None:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        return document_result(updated)

    async def _document_for_analysis(self, analysis_id: UUID, document_id: UUID) -> dict[str, Any]:
        document = await self._repository.get_document(document_id)
        if document is None or coerce_uuid(document["analysis_id"]) != analysis_id:
            raise DocumentToolError("DOCUMENT_NOT_FOUND", "Document was not found for this analysis.")
        if document["status"] == "deleted":
            raise DocumentToolError("DOCUMENT_DELETED", "Document has been deleted.")
        return document

    async def _replay_result(self, tool_call_id: UUID) -> dict[str, Any] | None:
        revision = await self._repository.find_revision_by_tool_call(tool_call_id)
        if revision is None:
            return None
        document = await self._repository.get_document(revision["document_id"])
        if document is None:
            return None
        replay_document = dict(document)
        replay_document.update(
            {
                "status": status_for_revision(document, revision),
                "current_version": revision["version"],
                "content_ref": revision["content_ref"],
                "content_hash": revision["content_hash"],
                "size_bytes": revision["size_bytes"],
            }
        )
        return document_result(replay_document)


def _ensure_mutable(document: dict[str, Any]) -> None:
    if document["status"] == "finalized":
        raise DocumentToolError("DOCUMENT_FINALIZED", "Finalized documents cannot be updated or deleted.")
    if document["status"] == "deleted":
        raise DocumentToolError("DOCUMENT_DELETED", "Deleted documents cannot be updated.")
