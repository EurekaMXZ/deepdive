from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID

from backend.ids import new_uuid7


def revision_payload(
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


def document_result(document: dict[str, Any]) -> dict[str, Any]:
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


def revision_result(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision_id": str(revision["id"]),
        "document_id": str(revision["document_id"]),
        "version": int(revision["version"]),
        "tool_call_id": str(revision["tool_call_id"]),
        "operation": revision["operation"],
        "content_ref": revision["content_ref"],
        "content_hash": revision["content_hash"],
        "size_bytes": int(revision["size_bytes"]),
        "created_at": revision["created_at"],
    }


def status_for_revision(document: dict[str, Any], revision: dict[str, Any]) -> str:
    del document
    operation = revision.get("operation")
    if operation == "delete":
        return "deleted"
    if operation == "finalize":
        return "finalized"
    return "draft"


def content_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def coerce_uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
