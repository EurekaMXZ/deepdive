from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class TodoStore(Protocol):
    async def add_todo_list(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        turn_id: UUID | None,
        tool_call_id: UUID,
        items: list[dict[str, str]],
        note: str | None,
    ) -> dict[str, Any]: ...

    async def latest_todo_list(self, *, agent_id: UUID) -> dict[str, Any] | None: ...
