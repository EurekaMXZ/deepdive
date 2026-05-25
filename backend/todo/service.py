from __future__ import annotations

import re
from typing import Any, cast
from uuid import UUID

from backend.todo.errors import TodoToolError
from backend.todo.store import TodoStore

TODO_STATUSES = ("pending", "in_progress", "completed")
TODO_STATUS_SET = frozenset(TODO_STATUSES)
TODO_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class TodoService:
    def __init__(self, *, repository: TodoStore) -> None:
        self._repository = repository

    async def update(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        tool_call_id: UUID,
        items: Any,
        note: Any,
        turn_id: UUID | None = None,
    ) -> dict[str, Any]:
        normalized_items = normalize_todo_items(items)
        normalized_note = normalize_note(note)
        return await self._repository.add_todo_list(
            analysis_id=analysis_id,
            agent_id=agent_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            items=normalized_items,
            note=normalized_note,
        )

    async def latest(self, *, agent_id: UUID) -> dict[str, Any] | None:
        return await self._repository.latest_todo_list(agent_id=agent_id)


def normalize_todo_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise TodoToolError("INVALID_TODO_STATE", "items must be an array.")
    raw_items = cast(list[Any], value)
    if not raw_items:
        raise TodoToolError("INVALID_TODO_STATE", "items must contain at least one TODO item.")
    if len(raw_items) > 8:
        raise TodoToolError("INVALID_TODO_STATE", "items must contain at most 8 TODO items.")
    items: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise TodoToolError("INVALID_TODO_STATE", "each TODO item must be an object.")
        raw_item = cast(dict[str, object], raw_item)
        item_id = str(raw_item.get("id") or "").strip()
        title = str(raw_item.get("title") or "").strip()
        status = str(raw_item.get("status") or "").strip()
        if not TODO_ID_PATTERN.fullmatch(item_id):
            raise TodoToolError("INVALID_TODO_STATE", "TODO item id must be a stable lowercase slug.")
        if item_id in seen_ids:
            raise TodoToolError("INVALID_TODO_STATE", f"duplicate TODO item id: {item_id}")
        if not title or len(title) > 80:
            raise TodoToolError("INVALID_TODO_STATE", "TODO item title must be 1-80 characters.")
        if status not in TODO_STATUS_SET:
            raise TodoToolError("INVALID_TODO_STATE", "TODO item status must be pending, in_progress, or completed.")
        seen_ids.add(item_id)
        items.append({"id": item_id, "title": title, "status": status})
    in_progress_count = sum(1 for item in items if item["status"] == "in_progress")
    completed_count = sum(1 for item in items if item["status"] == "completed")
    if completed_count == len(items):
        return items
    if in_progress_count != 1:
        raise TodoToolError(
            "INVALID_TODO_STATE",
            "TODO state must have exactly one in_progress item until all items are completed.",
        )
    return items


def normalize_note(value: Any) -> str | None:
    if value is None:
        return None
    note = str(value).strip()
    if not note:
        return None
    if len(note) > 500:
        raise TodoToolError("INVALID_TODO_STATE", "TODO note must be at most 500 characters.")
    return note
