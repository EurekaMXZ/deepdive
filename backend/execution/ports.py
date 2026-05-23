from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ToolExecutionContext:
    tool_call_id: UUID
    agent_id: UUID
    snapshot_id: UUID


class SnapshotToolRepository:
    async def get_file(self, snapshot_id: UUID, path: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def list_files(
        self,
        snapshot_id: UUID,
        *,
        path: str | None,
        recursive: bool,
        max_results: int,
        glob: str | None = None,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def search_files(
        self,
        snapshot_id: UUID,
        *,
        query: str,
        max_results: int,
        glob: str | None = None,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def text_files_under_prefix(self, snapshot_id: UUID, prefix: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def add_evidence(
        self,
        *,
        agent_id: UUID,
        snapshot_id: UUID,
        tool_call_id: UUID,
        path: str,
        start_line: int | None,
        end_line: int | None,
        content_hash: str | None,
        snippet: str | None = None,
        snippet_ref: str | None = None,
        evidence_id: UUID | None = None,
    ) -> str:
        raise NotImplementedError
