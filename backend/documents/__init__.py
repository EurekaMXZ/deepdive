from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from backend.ids import new_uuid7
from backend.storage import ObjectStorage, document_content_key


class DocumentStore(Protocol):
    async def get_document(self, document_id: UUID) -> dict[str, Any] | None: ...

    async def find_revision_by_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None: ...

    async def add_document_with_revision(self, document: dict[str, Any], revision: dict[str, Any]) -> None: ...

    async def update_document_with_revision(
        self, document_id: UUID, updates: dict[str, Any], revision: dict[str, Any]
    ) -> dict[str, Any] | None: ...


@dataclass
class DocumentRepository:
    documents: dict[UUID, dict[str, Any]] = field(default_factory=dict[UUID, dict[str, Any]])
    revisions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def get_document(self, document_id: UUID) -> dict[str, Any] | None:
        document = self.documents.get(document_id)
        return dict(document) if document is not None else None

    async def find_revision_by_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None:
        for revision in self.revisions:
            if revision["tool_call_id"] == tool_call_id:
                return dict(revision)
        return None

    async def add_document_with_revision(self, document: dict[str, Any], revision: dict[str, Any]) -> None:
        self.documents[document["id"]] = dict(document)
        self.revisions.append(dict(revision))

    async def update_document_with_revision(
        self, document_id: UUID, updates: dict[str, Any], revision: dict[str, Any]
    ) -> dict[str, Any] | None:
        document = dict(self.documents[document_id])
        if "expected_version" in updates and int(document["current_version"]) != int(updates["expected_version"]):
            return None
        if "expected_status" in updates and document["status"] != updates["expected_status"]:
            return None
        updates = {key: value for key, value in updates.items() if key not in {"expected_version", "expected_status"}}
        document.update(updates)
        self.documents[document_id] = document
        self.revisions.append(dict(revision))
        return dict(document)


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
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay

        now = datetime.now(UTC)
        document_id = new_uuid7()
        version = 1
        content_bytes = content.encode("utf-8")
        content_hash = _content_hash(content_bytes)
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
            "content_hash": content_hash,
            "size_bytes": len(content_bytes),
            "created_at": now,
            "updated_at": now,
            "finalized_at": None,
        }
        revision = _revision(
            document_id, version, tool_call_id, "create", content_ref, content_hash, len(content_bytes), now
        )
        await self._repository.add_document_with_revision(document, revision)
        return _document_result(document)

    async def get(self, *, analysis_id: UUID, document_id: UUID, include_content: bool) -> dict[str, Any]:
        document = await self._document_for_analysis(analysis_id, document_id)
        result = _document_result(document)
        if include_content:
            result["content"] = self._storage.get_bytes(document["content_ref"]).decode("utf-8")
        return result

    async def update(
        self,
        *,
        analysis_id: UUID,
        tool_call_id: UUID,
        document_id: UUID,
        expected_version: int,
        content: str,
    ) -> dict[str, Any]:
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
        content_hash = _content_hash(content_bytes)
        content_ref = document_content_key(analysis_id, document_id, version, tool_call_id)
        self._storage.put_bytes(content_ref, content_bytes, content_type="text/markdown; charset=utf-8")
        updates = {
            "expected_version": expected_version,
            "expected_status": "draft",
            "status": "draft",
            "current_version": version,
            "content_ref": content_ref,
            "content_hash": content_hash,
            "size_bytes": len(content_bytes),
            "updated_at": now,
            "finalized_at": None,
        }
        revision = _revision(
            document_id, version, tool_call_id, "update", content_ref, content_hash, len(content_bytes), now
        )
        updated = await self._repository.update_document_with_revision(document_id, updates, revision)
        if updated is None:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        return _document_result(updated)

    async def delete(
        self, *, analysis_id: UUID, tool_call_id: UUID, document_id: UUID, expected_version: int
    ) -> dict[str, Any]:
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay
        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        now = datetime.now(UTC)
        version = expected_version + 1
        revision = _revision(
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
        return _document_result(updated)

    async def finalize(
        self,
        *,
        analysis_id: UUID,
        tool_call_id: UUID,
        document_id: UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay
        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        now = datetime.now(UTC)
        version = expected_version + 1
        revision = _revision(
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
        return _document_result(updated)

    async def _document_for_analysis(self, analysis_id: UUID, document_id: UUID) -> dict[str, Any]:
        document = await self._repository.get_document(document_id)
        if document is None or document["analysis_id"] != analysis_id:
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
                "status": _status_for_revision(document, revision),
                "current_version": revision["version"],
                "content_ref": revision["content_ref"],
                "content_hash": revision["content_hash"],
                "size_bytes": revision["size_bytes"],
            }
        )
        return _document_result(replay_document)


class DocumentToolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _ensure_mutable(document: dict[str, Any]) -> None:
    if document["status"] == "finalized":
        raise DocumentToolError("DOCUMENT_FINALIZED", "Finalized documents cannot be updated or deleted.")
    if document["status"] == "deleted":
        raise DocumentToolError("DOCUMENT_DELETED", "Deleted documents cannot be updated.")


def _revision(
    document_id: UUID,
    version: int,
    tool_call_id: UUID,
    operation: str,
    content_ref: str,
    content_hash: str,
    size_bytes: int,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "id": new_uuid7(),
        "document_id": document_id,
        "version": version,
        "tool_call_id": tool_call_id,
        "operation": operation,
        "content_ref": content_ref,
        "content_hash": content_hash,
        "size_bytes": size_bytes,
        "created_at": created_at,
    }


def _document_result(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": str(document["id"]),
        "analysis_id": str(document["analysis_id"]),
        "agent_id": str(document["agent_id"]),
        "title": document["title"],
        "kind": document["kind"],
        "status": document["status"],
        "version": int(document["current_version"]),
        "content_ref": document["content_ref"],
        "content_hash": document["content_hash"],
        "size_bytes": int(document["size_bytes"]),
    }


def _status_for_revision(document: dict[str, Any], revision: dict[str, Any]) -> str:
    operation = revision.get("operation")
    if operation == "delete":
        return "deleted"
    if operation == "finalize":
        return "finalized"
    return "draft"


def _content_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
