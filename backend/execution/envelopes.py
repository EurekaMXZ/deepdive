from __future__ import annotations

from typing import Any
from uuid import UUID


def tool_success_envelope(
    tool_name: str,
    snapshot_id: UUID,
    result: dict[str, Any],
    evidence_ids: list[str],
    truncated: bool,
    next_cursor: Any,
    *,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "tool_name": tool_name,
        "snapshot_id": str(snapshot_id),
        "scope": scope or {"type": "source_snapshot", "snapshot_id": str(snapshot_id)},
        "result": result,
        "evidence_ids": evidence_ids,
        "truncated": truncated,
        "next_cursor": next_cursor,
    }


def tool_error_envelope(tool_name: str, code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "tool_name": tool_name,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
