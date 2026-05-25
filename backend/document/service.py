from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from backend.document.errors import DocumentToolError
from backend.document.models import (
    coerce_uuid,
    content_hash,
    document_result,
    folder_result,
    revision_payload,
    revision_result,
    status_for_revision,
)
from backend.document.store import DocumentStore
from backend.ids import new_uuid7
from backend.storage import ObjectStorage, document_content_key, document_section_content_key

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
SECTION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")


class DocumentService:
    def __init__(self, *, repository: DocumentStore, storage: ObjectStorage) -> None:
        self._repository = repository
        self._storage = storage

    async def create(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        tool_call_id: UUID,
        title: str,
        kind: str,
        content: str,
        parent_node_id: UUID | None = None,
        slug: str | None = None,
        focus_area: str | None = None,
        sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        agent_id = coerce_uuid(agent_id)
        tool_call_id = coerce_uuid(tool_call_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay

        normalized_sections = _normalize_sections(sections)
        now = datetime.now(UTC)
        document_id = new_uuid7()
        version = 1
        content_text = _render_document_content(title=title, content=content, sections=normalized_sections)
        content_bytes = content_text.encode("utf-8")
        digest = content_hash(content_bytes)
        content_ref = document_content_key(analysis_id, document_id, version, tool_call_id)
        self._storage.put_bytes(content_ref, content_bytes, content_type="text/markdown; charset=utf-8")
        document = {
            "id": document_id,
            "analysis_id": analysis_id,
            "agent_id": agent_id,
            "title": title,
            "kind": kind,
            "status": "draft",
            "current_version": version,
            "content_ref": content_ref,
            "content_hash": digest,
            "size_bytes": len(content_bytes),
            "created_at": now,
            "updated_at": now,
            "finalized_at": None,
        }
        revision = revision_payload(
            document_id, version, tool_call_id, "create", content_ref, digest, len(content_bytes), now
        )
        if parent_node_id is None and slug is None and focus_area is None and not normalized_sections:
            await self._repository.add_document_with_revision(document, revision)
            return document_result(document)
        parent_node = await self._parent_node_for_analysis(analysis_id, parent_node_id)
        node = _document_node(
            analysis_id=analysis_id,
            agent_id=agent_id,
            document_id=document_id,
            parent_node=parent_node,
            title=title,
            slug=slug,
            focus_area=focus_area,
            sort_order=0,
            now=now,
        )
        section_rows, section_revisions = self._section_rows(
            analysis_id=analysis_id,
            document_id=document_id,
            document_revision_id=revision["id"],
            tool_call_id=tool_call_id,
            version=version,
            existing_sections=[],
            sections=normalized_sections,
            now=now,
        )
        await self._repository.add_document_tree_with_revision(document, node, section_rows, revision, section_revisions)
        return self._document_result_with_tree(document, node=node, sections=section_rows)

    async def create_folder(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        title: str,
        slug: str,
        parent_node_id: UUID | None,
        sort_order: int,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        agent_id = coerce_uuid(agent_id)
        parent_node = await self._parent_node_for_analysis(analysis_id, parent_node_id)
        now = datetime.now(UTC)
        node = _folder_node(
            analysis_id=analysis_id,
            agent_id=agent_id,
            parent_node=parent_node,
            title=title,
            slug=slug,
            sort_order=sort_order,
            now=now,
        )
        await self._repository.add_folder_node(node)
        return folder_result(node)

    async def get(
        self,
        *,
        analysis_id: UUID,
        document_id: UUID,
        include_content: bool,
        include_sections: bool = False,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        document_id = coerce_uuid(document_id)
        document = await self._document_for_analysis(analysis_id, document_id)
        result = await self._document_result_with_related(document, include_sections=include_sections)
        if include_content:
            result["content"] = self._storage.get_bytes(document["content_ref"]).decode("utf-8")
        return result

    async def list(self, *, analysis_id: UUID, limit: int = 50, cursor: str | None = None) -> list[dict[str, Any]]:
        analysis_id = coerce_uuid(analysis_id)
        documents = await self._repository.list_documents(analysis_id, limit=limit, cursor=cursor)
        return [document_result(document) for document in documents]

    async def list_revisions(
        self, *, analysis_id: UUID, document_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        analysis_id = coerce_uuid(analysis_id)
        document_id = coerce_uuid(document_id)
        document = await self._document_for_analysis(analysis_id, document_id)
        revisions = await self._repository.list_revisions(UUID(str(document["id"])), limit=limit, cursor=cursor)
        return [revision_result(revision) for revision in revisions]

    async def tree(self, *, analysis_id: UUID) -> list[dict[str, Any]]:
        analysis_id = coerce_uuid(analysis_id)
        nodes = await self._repository.list_nodes(analysis_id)
        return _build_tree(nodes)

    async def update(
        self,
        *,
        analysis_id: UUID,
        tool_call_id: UUID,
        document_id: UUID,
        expected_version: int,
        content: str,
        sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        tool_call_id = coerce_uuid(tool_call_id)
        document_id = coerce_uuid(document_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay

        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")

        normalized_sections = _normalize_sections(sections)
        version = expected_version + 1
        now = datetime.now(UTC)
        existing_sections = await self._repository.list_sections(document_id)
        if normalized_sections:
            existing_sections = [
                {
                    **section,
                    "content": self._storage.get_bytes(section["content_ref"]).decode("utf-8"),
                }
                for section in existing_sections
            ]
        section_rows = _merged_sections(existing_sections=existing_sections, updates=normalized_sections)
        content_text = _render_document_content(
            title=str(document["title"]),
            content=content,
            sections=section_rows,
            fallback_content_ref=document["content_ref"],
            storage=self._storage,
        )
        content_bytes = content_text.encode("utf-8")
        digest = content_hash(content_bytes)
        content_ref = document_content_key(analysis_id, document_id, version, tool_call_id)
        self._storage.put_bytes(content_ref, content_bytes, content_type="text/markdown; charset=utf-8")
        updates = {
            "expected_version": expected_version,
            "expected_status": "draft",
            "status": "draft",
            "current_version": version,
            "content_ref": content_ref,
            "content_hash": digest,
            "size_bytes": len(content_bytes),
            "updated_at": now,
            "finalized_at": None,
        }
        revision = revision_payload(
            document_id, version, tool_call_id, "update", content_ref, digest, len(content_bytes), now
        )
        if normalized_sections:
            persisted_sections, section_revisions = self._section_rows(
                analysis_id=analysis_id,
                document_id=document_id,
                document_revision_id=revision["id"],
                tool_call_id=tool_call_id,
                version=version,
                existing_sections=existing_sections,
                sections=section_rows,
                now=now,
            )
            updated = await self._repository.update_document_tree_with_revision(
                document_id, updates, persisted_sections, revision, section_revisions
            )
        else:
            updated = await self._repository.update_document_with_revision(document_id, updates, revision)
        if updated is None:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        return await self._document_result_with_related(updated, include_sections=bool(normalized_sections))

    async def delete(
        self, *, analysis_id: UUID, tool_call_id: UUID, document_id: UUID, expected_version: int
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        tool_call_id = coerce_uuid(tool_call_id)
        document_id = coerce_uuid(document_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay
        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        now = datetime.now(UTC)
        version = expected_version + 1
        revision = revision_payload(
            document_id,
            version,
            tool_call_id,
            "delete",
            document["content_ref"],
            document["content_hash"],
            int(document["size_bytes"]),
            now,
        )
        updated = await self._repository.update_document_with_revision(
            document_id,
            {
                "expected_version": expected_version,
                "expected_status": "draft",
                "status": "deleted",
                "current_version": version,
                "content_ref": document["content_ref"],
                "content_hash": document["content_hash"],
                "size_bytes": int(document["size_bytes"]),
                "updated_at": now,
                "finalized_at": None,
            },
            revision,
        )
        if updated is None:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        return document_result(updated)

    async def finalize(
        self,
        *,
        analysis_id: UUID,
        tool_call_id: UUID,
        document_id: UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        analysis_id = coerce_uuid(analysis_id)
        tool_call_id = coerce_uuid(tool_call_id)
        document_id = coerce_uuid(document_id)
        replay = await self._replay_result(tool_call_id)
        if replay is not None:
            return replay
        document = await self._document_for_analysis(analysis_id, document_id)
        _ensure_mutable(document)
        if int(document["current_version"]) != expected_version:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        now = datetime.now(UTC)
        version = expected_version + 1
        revision = revision_payload(
            document_id,
            version,
            tool_call_id,
            "finalize",
            document["content_ref"],
            document["content_hash"],
            int(document["size_bytes"]),
            now,
        )
        updated = await self._repository.update_document_with_revision(
            document_id,
            {
                "expected_version": expected_version,
                "expected_status": "draft",
                "status": "finalized",
                "current_version": version,
                "content_ref": document["content_ref"],
                "content_hash": document["content_hash"],
                "size_bytes": int(document["size_bytes"]),
                "updated_at": now,
                "finalized_at": now,
            },
            revision,
        )
        if updated is None:
            raise DocumentToolError("DOCUMENT_VERSION_CONFLICT", "Document version does not match expected_version.")
        return document_result(updated)

    async def _document_for_analysis(self, analysis_id: UUID, document_id: UUID) -> dict[str, Any]:
        document = await self._repository.get_document(document_id)
        if document is None or coerce_uuid(document["analysis_id"]) != analysis_id:
            raise DocumentToolError("DOCUMENT_NOT_FOUND", "Document was not found for this analysis.")
        if document["status"] == "deleted":
            raise DocumentToolError("DOCUMENT_DELETED", "Document has been deleted.")
        return document

    async def _replay_result(self, tool_call_id: UUID) -> dict[str, Any] | None:
        revision = await self._repository.find_revision_by_tool_call(tool_call_id)
        if revision is None:
            return None
        document = await self._repository.get_document(revision["document_id"])
        if document is None:
            return None
        replay_document = dict(document)
        replay_document.update(
            {
                "status": status_for_revision(document, revision),
                "current_version": revision["version"],
                "content_ref": revision["content_ref"],
                "content_hash": revision["content_hash"],
                "size_bytes": revision["size_bytes"],
            }
        )
        return document_result(replay_document)

    async def _parent_node_for_analysis(self, analysis_id: UUID, parent_node_id: UUID | None) -> dict[str, Any] | None:
        if parent_node_id is None:
            return None
        parent_node = await self._repository.get_node(coerce_uuid(parent_node_id))
        if parent_node is None or coerce_uuid(parent_node["analysis_id"]) != analysis_id:
            raise DocumentToolError("DOCUMENT_NODE_NOT_FOUND", "Parent document node was not found.")
        if parent_node["node_type"] != "folder":
            raise DocumentToolError("INVALID_DOCUMENT_TREE", "parent_node_id must point to a folder node.")
        return parent_node

    async def _document_result_with_related(
        self, document: dict[str, Any], *, include_sections: bool
    ) -> dict[str, Any]:
        nodes = await self._repository.list_nodes(coerce_uuid(document["analysis_id"]))
        node = next((node for node in nodes if node.get("document_id") == document["id"]), None)
        sections = await self._repository.list_sections(coerce_uuid(document["id"])) if include_sections else None
        if include_sections:
            sections = [
                {
                    **section,
                    "content": self._storage.get_bytes(section["content_ref"]).decode("utf-8"),
                }
                for section in sections or []
            ]
        return self._document_result_with_tree(document, node=node, sections=sections)

    def _document_result_with_tree(
        self,
        document: dict[str, Any],
        *,
        node: dict[str, Any] | None,
        sections: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        enriched = dict(document)
        if node is not None:
            enriched["node"] = node
            enriched["focus_area"] = node.get("focus_area")
        if sections is not None:
            enriched["sections"] = sections
        return document_result(enriched)

    def _section_rows(
        self,
        *,
        analysis_id: UUID,
        document_id: UUID,
        document_revision_id: UUID,
        tool_call_id: UUID,
        version: int,
        existing_sections: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        now: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        existing_by_stable_id = {str(section["stable_id"]): section for section in existing_sections}
        rows: list[dict[str, Any]] = []
        revisions: list[dict[str, Any]] = []
        for section in sections:
            existing = existing_by_stable_id.get(str(section["stable_id"]))
            section_id = coerce_uuid(existing["id"]) if existing is not None else new_uuid7()
            content_bytes = str(section["content"]).encode("utf-8")
            digest = content_hash(content_bytes)
            content_ref = document_section_content_key(analysis_id, document_id, section_id, version, tool_call_id)
            self._storage.put_bytes(content_ref, content_bytes, content_type="text/markdown; charset=utf-8")
            row = {
                "id": section_id,
                "document_id": document_id,
                "stable_id": section["stable_id"],
                "title": section["title"],
                "sort_order": int(section["sort_order"]),
                "content_ref": content_ref,
                "content_hash": digest,
                "size_bytes": len(content_bytes),
                "created_at": existing.get("created_at", now) if existing is not None else now,
                "updated_at": now,
            }
            rows.append(row)
            revisions.append(
                {
                    "id": new_uuid7(),
                    "section_id": section_id,
                    "document_id": document_id,
                    "document_revision_id": document_revision_id,
                    "version": version,
                    "title": section["title"],
                    "sort_order": int(section["sort_order"]),
                    "content_ref": content_ref,
                    "content_hash": digest,
                    "size_bytes": len(content_bytes),
                    "created_at": now,
                }
            )
        return rows, revisions


def _ensure_mutable(document: dict[str, Any]) -> None:
    if document["status"] == "finalized":
        raise DocumentToolError("DOCUMENT_FINALIZED", "Finalized documents cannot be updated or deleted.")
    if document["status"] == "deleted":
        raise DocumentToolError("DOCUMENT_DELETED", "Deleted documents cannot be updated.")


def _normalize_sections(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not value:
        return []
    if len(value) > 20:
        raise DocumentToolError("INVALID_DOCUMENT_SECTIONS", "sections must contain at most 20 items.")
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_section in value:
        stable_id = str(raw_section.get("stable_id") or "").strip()
        title = str(raw_section.get("title") or "").strip()
        content = str(raw_section.get("content") or "")
        sort_order = int(raw_section.get("sort_order") or 0)
        if not SECTION_ID_PATTERN.fullmatch(stable_id):
            raise DocumentToolError("INVALID_DOCUMENT_SECTIONS", "section stable_id must be a lowercase slug.")
        if stable_id in seen:
            raise DocumentToolError("INVALID_DOCUMENT_SECTIONS", f"duplicate section stable_id: {stable_id}")
        if not title or len(title) > 200:
            raise DocumentToolError("INVALID_DOCUMENT_SECTIONS", "section title must be 1-200 characters.")
        seen.add(stable_id)
        sections.append({"stable_id": stable_id, "title": title, "content": content, "sort_order": sort_order})
    return sorted(sections, key=lambda section: (int(section["sort_order"]), str(section["stable_id"])))


def _folder_node(
    *,
    analysis_id: UUID,
    agent_id: UUID,
    parent_node: dict[str, Any] | None,
    title: str,
    slug: str,
    sort_order: int,
    now: datetime,
) -> dict[str, Any]:
    slug = _normalize_slug(slug)
    return {
        "id": new_uuid7(),
        "analysis_id": analysis_id,
        "agent_id": agent_id,
        "parent_id": parent_node["id"] if parent_node is not None else None,
        "node_type": "folder",
        "document_id": None,
        "title": title,
        "slug": slug,
        "path": _node_path(parent_node, slug),
        "focus_area": None,
        "sort_order": sort_order,
        "created_at": now,
        "updated_at": now,
    }


def _document_node(
    *,
    analysis_id: UUID,
    agent_id: UUID,
    document_id: UUID,
    parent_node: dict[str, Any] | None,
    title: str,
    slug: str | None,
    focus_area: str | None,
    sort_order: int,
    now: datetime,
) -> dict[str, Any]:
    slug = _normalize_slug(slug or _slugify(title))
    return {
        "id": new_uuid7(),
        "analysis_id": analysis_id,
        "agent_id": agent_id,
        "parent_id": parent_node["id"] if parent_node is not None else None,
        "node_type": "document",
        "document_id": document_id,
        "title": title,
        "slug": slug,
        "path": _node_path(parent_node, slug),
        "focus_area": focus_area,
        "sort_order": sort_order,
        "created_at": now,
        "updated_at": now,
    }


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    if not SLUG_PATTERN.fullmatch(slug):
        raise DocumentToolError("INVALID_DOCUMENT_TREE", "document node slug must be a lowercase slug.")
    return slug


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "document"


def _node_path(parent_node: dict[str, Any] | None, slug: str) -> str:
    if parent_node is None:
        return slug
    return f"{parent_node['path']}/{slug}"


def _render_document_content(
    *,
    title: str,
    content: str | None,
    sections: list[dict[str, Any]],
    fallback_content_ref: str | None = None,
    storage: ObjectStorage | None = None,
) -> str:
    if sections:
        lines = [f"# {title}", ""]
        for section in sections:
            lines.extend([f"## {section['title']}", "", str(section.get("content") or ""), ""])
        return "\n".join(lines).rstrip() + "\n"
    if content is not None:
        return content
    if fallback_content_ref is not None and storage is not None:
        return storage.get_bytes(fallback_content_ref).decode("utf-8")
    return ""


def _merged_sections(
    *, existing_sections: list[dict[str, Any]], updates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for section in existing_sections:
        merged[str(section["stable_id"])] = dict(section)
    for section in updates:
        merged[str(section["stable_id"])] = dict(section)
    merged_sections: list[dict[str, Any]] = []
    for section in merged.values():
        item = dict(section)
        if "content" not in item:
            item["content"] = ""
        merged_sections.append(item)
    return sorted(merged_sections, key=lambda section: (int(section["sort_order"]), str(section["stable_id"])))


def _build_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[UUID, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for node in sorted(nodes, key=lambda item: (str(item.get("path") or ""), int(item.get("sort_order") or 0))):
        children: list[dict[str, Any]] = []
        item: dict[str, Any] = {
            **folder_result(node),
            "status": node.get("status"),
            "version": int(node["current_version"]) if node.get("current_version") is not None else None,
            "section_count": int(node.get("section_count") or 0),
            "children": children,
        }
        by_id[coerce_uuid(node["id"])] = item
        parent_id = node.get("parent_id")
        if parent_id is None or coerce_uuid(parent_id) not in by_id:
            roots.append(item)
        else:
            by_id[coerce_uuid(parent_id)]["children"].append(item)
    return roots
