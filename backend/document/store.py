from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class DocumentStore(Protocol):
    async def get_document(self, document_id: UUID) -> dict[str, Any] | None: ...

    async def list_documents(
        self, analysis_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def list_revisions(
        self, document_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def find_revision_by_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None: ...

    async def add_document_with_revision(self, document: dict[str, Any], revision: dict[str, Any]) -> None: ...

    async def update_document_with_revision(
        self, document_id: UUID, updates: dict[str, Any], revision: dict[str, Any]
    ) -> dict[str, Any] | None: ...
