from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from backend.api.pagination import cursor_offset
from backend.document.models import coerce_uuid


@dataclass
class DocumentRepository:
    documents: dict[UUID, dict[str, Any]] = field(default_factory=dict[UUID, dict[str, Any]])
    nodes: dict[UUID, dict[str, Any]] = field(default_factory=dict[UUID, dict[str, Any]])
    sections: dict[UUID, dict[str, Any]] = field(default_factory=dict[UUID, dict[str, Any]])
    revisions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    section_revisions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def get_document(self, document_id: UUID) -> dict[str, Any] | None:
        document = self.documents.get(document_id)
        return dict(document) if document is not None else None

    async def list_documents(
        self, analysis_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        offset = cursor_offset(cursor)
        documents = [
            dict(document)
            for document in self.documents.values()
            if coerce_uuid(document["analysis_id"]) == analysis_id and document["status"] != "deleted"
        ]
        return sorted(documents, key=lambda document: (document["created_at"], document["id"]))[offset : offset + limit]

    async def list_revisions(
        self, document_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        offset = cursor_offset(cursor)
        revisions = [dict(revision) for revision in self.revisions if revision["document_id"] == document_id]
        return sorted(revisions, key=lambda revision: int(revision["version"]))[offset : offset + limit]

    async def list_nodes(self, analysis_id: UUID) -> list[dict[str, Any]]:
        nodes = [
            dict(node)
            for node in self.nodes.values()
            if coerce_uuid(node["analysis_id"]) == analysis_id
            and (node["node_type"] != "document" or self.documents[node["document_id"]]["status"] != "deleted")
        ]
        return sorted(nodes, key=lambda node: (node["path"], node["sort_order"], node["id"]))

    async def list_sections(self, document_id: UUID) -> list[dict[str, Any]]:
        sections = [dict(section) for section in self.sections.values() if section["document_id"] == document_id]
        return sorted(sections, key=lambda section: (int(section["sort_order"]), section["stable_id"]))

    async def get_node(self, node_id: UUID) -> dict[str, Any] | None:
        node = self.nodes.get(node_id)
        return dict(node) if node is not None else None

    async def find_revision_by_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None:
        for revision in self.revisions:
            if revision["tool_call_id"] == tool_call_id:
                return dict(revision)
        return None

    async def add_folder_node(self, node: dict[str, Any]) -> None:
        self.nodes[node["id"]] = dict(node)

    async def add_document_with_revision(self, document: dict[str, Any], revision: dict[str, Any]) -> None:
        self.documents[document["id"]] = dict(document)
        self.revisions.append(dict(revision))

    async def add_document_tree_with_revision(
        self,
        document: dict[str, Any],
        node: dict[str, Any],
        sections: list[dict[str, Any]],
        revision: dict[str, Any],
        section_revisions: list[dict[str, Any]],
    ) -> None:
        await self.add_document_with_revision(document, revision)
        self.nodes[node["id"]] = dict(node)
        for section in sections:
            self.sections[section["id"]] = dict(section)
        self.section_revisions.extend(dict(revision) for revision in section_revisions)

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

    async def update_document_tree_with_revision(
        self,
        document_id: UUID,
        updates: dict[str, Any],
        sections: list[dict[str, Any]],
        revision: dict[str, Any],
        section_revisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        document = await self.update_document_with_revision(document_id, updates, revision)
        if document is None:
            return None
        for section in sections:
            self.sections[section["id"]] = dict(section)
        self.section_revisions.extend(dict(revision) for revision in section_revisions)
        return document
