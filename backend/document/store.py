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

    async def list_nodes(self, analysis_id: UUID) -> list[dict[str, Any]]: ...

    async def list_sections(self, document_id: UUID) -> list[dict[str, Any]]: ...

    async def get_node(self, node_id: UUID) -> dict[str, Any] | None: ...

    async def find_revision_by_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None: ...

    async def add_folder_node(self, node: dict[str, Any]) -> None: ...

    async def add_document_with_revision(self, document: dict[str, Any], revision: dict[str, Any]) -> None: ...

    async def add_document_tree_with_revision(
        self,
        document: dict[str, Any],
        node: dict[str, Any],
        sections: list[dict[str, Any]],
        revision: dict[str, Any],
        section_revisions: list[dict[str, Any]],
    ) -> None: ...

    async def update_document_with_revision(
        self, document_id: UUID, updates: dict[str, Any], revision: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def update_document_tree_with_revision(
        self,
        document_id: UUID,
        updates: dict[str, Any],
        sections: list[dict[str, Any]],
        revision: dict[str, Any],
        section_revisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None: ...
