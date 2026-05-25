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
    result = {
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
    if document.get("focus_area") is not None:
        result["focus_area"] = document["focus_area"]
    if document.get("node") is not None:
        result["node"] = node_result(document["node"])
    if document.get("sections") is not None:
        result["sections"] = [section_result(section) for section in document["sections"]]
    return result


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


def folder_result(node: dict[str, Any]) -> dict[str, Any]:
    return node_result(node)


def node_result(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": str(node["id"]),
        "analysis_id": str(node["analysis_id"]),
        "agent_id": str(node["agent_id"]),
        "parent_id": str(node["parent_id"]) if node.get("parent_id") is not None else None,
        "node_type": node["node_type"],
        "document_id": str(node["document_id"]) if node.get("document_id") is not None else None,
        "title": node["title"],
        "slug": node["slug"],
        "path": node["path"],
        "focus_area": node.get("focus_area"),
        "sort_order": int(node["sort_order"]),
    }


def section_result(section: dict[str, Any]) -> dict[str, Any]:
    result = {
        "section_id": str(section["id"]),
        "document_id": str(section["document_id"]),
        "stable_id": section["stable_id"],
        "title": section["title"],
        "sort_order": int(section["sort_order"]),
        "content_ref": section["content_ref"],
        "content_hash": section["content_hash"],
        "size_bytes": int(section["size_bytes"]),
    }
    if "content" in section:
        result["content"] = section["content"]
    return result


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
