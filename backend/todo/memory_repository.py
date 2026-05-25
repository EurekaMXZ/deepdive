from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from backend.ids import new_uuid7


@dataclass
class TodoRepository:
    lists: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def add_todo_list(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        turn_id: UUID | None,
        tool_call_id: UUID,
        items: list[dict[str, str]],
        note: str | None,
    ) -> dict[str, Any]:
        replay = next((item for item in self.lists if item["tool_call_id"] == tool_call_id), None)
        if replay is not None:
            return _todo_result(replay)
        version = max((int(item["version"]) for item in self.lists if item["agent_id"] == agent_id), default=0) + 1
        row = {
            "id": new_uuid7(),
            "analysis_id": analysis_id,
            "agent_id": agent_id,
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "version": version,
            "items_json": [dict(item) for item in items],
            "note": note,
            "created_at": datetime.now(UTC),
        }
        self.lists.append(row)
        return _todo_result(row)

    async def latest_todo_list(self, *, agent_id: UUID) -> dict[str, Any] | None:
        rows = [item for item in self.lists if item["agent_id"] == agent_id]
        if not rows:
            return None
        return _todo_result(max(rows, key=lambda item: int(item["version"])))


def _todo_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": int(row["version"]),
        "items": [dict(item) for item in row["items_json"]],
        "note": row.get("note"),
    }
