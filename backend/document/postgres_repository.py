from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from backend.api.pagination import cursor_offset
from backend.db.connections import AsyncDbConnection, ConnectionSource, connection_from
from backend.ids import new_uuid7


class PostgresDocumentRepository:
    def __init__(self, connection_or_database: ConnectionSource) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def get_document(self, document_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, analysis_id, agent_id, title, kind, status, current_version,
                           content_ref, content_hash, size_bytes, created_at, updated_at, finalized_at
                    FROM documents
                    WHERE id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def list_documents(
        self, analysis_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        offset = cursor_offset(cursor)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, analysis_id, agent_id, title, kind, status, current_version,
                           content_ref, content_hash, size_bytes, created_at, updated_at, finalized_at
                    FROM documents
                    WHERE analysis_id = :analysis_id
                      AND status <> 'deleted'
                    ORDER BY created_at, id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"analysis_id": analysis_id, "limit": limit, "offset": offset},
            )
        return [dict(row) for row in result.mappings().all()]

    async def list_revisions(
        self, document_id: UUID, *, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        offset = cursor_offset(cursor)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, document_id, version, tool_call_id, operation,
                           content_ref, content_hash, size_bytes, created_at
                    FROM document_revisions
                    WHERE document_id = :document_id
                    ORDER BY version
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"document_id": document_id, "limit": limit, "offset": offset},
            )
        return [dict(row) for row in result.mappings().all()]

    async def list_nodes(self, analysis_id: UUID) -> list[dict[str, Any]]:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT
                        n.id, n.analysis_id, n.agent_id, n.parent_id, n.node_type,
                        n.document_id, n.title, n.slug, n.path, n.focus_area, n.sort_order,
                        n.created_at, n.updated_at,
                        d.status, d.current_version,
                        COALESCE(section_counts.section_count, 0) AS section_count
                    FROM document_nodes n
                    LEFT JOIN documents d ON d.id = n.document_id
                    LEFT JOIN (
                        SELECT document_id, COUNT(*) AS section_count
                        FROM document_sections
                        GROUP BY document_id
                    ) section_counts ON section_counts.document_id = n.document_id
                    WHERE n.analysis_id = :analysis_id
                      AND (n.node_type <> 'document' OR d.status <> 'deleted')
                    ORDER BY n.path, n.sort_order, n.id
                    """
                ),
                {"analysis_id": analysis_id},
            )
        return [dict(row) for row in result.mappings().all()]

    async def list_sections(self, document_id: UUID) -> list[dict[str, Any]]:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, document_id, stable_id, title, sort_order,
                           content_ref, content_hash, size_bytes, created_at, updated_at
                    FROM document_sections
                    WHERE document_id = :document_id
                    ORDER BY sort_order, stable_id
                    """
                ),
                {"document_id": document_id},
            )
        return [dict(row) for row in result.mappings().all()]

    async def get_node(self, node_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, analysis_id, agent_id, parent_id, node_type, document_id,
                           title, slug, path, focus_area, sort_order, created_at, updated_at
                    FROM document_nodes
                    WHERE id = :node_id
                    """
                ),
                {"node_id": node_id},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def find_revision_by_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, document_id, version, tool_call_id, operation,
                           content_ref, content_hash, size_bytes, created_at
                    FROM document_revisions
                    WHERE tool_call_id = :tool_call_id
                    """
                ),
                {"tool_call_id": tool_call_id},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def add_folder_node(self, node: dict[str, Any]) -> None:
        async with self._connection() as connection:
            await self._insert_node(connection, node)

    async def add_document_with_revision(self, document: dict[str, Any], revision: dict[str, Any]) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO documents (
                        id, analysis_id, agent_id, title, kind, status, current_version,
                        content_ref, content_hash, size_bytes, created_at, updated_at, finalized_at
                    )
                    VALUES (
                        :id, :analysis_id, :agent_id, :title, :kind, :status, :current_version,
                        :content_ref, :content_hash, :size_bytes, :created_at, :updated_at, :finalized_at
                    )
                    """
                ),
                document,
            )
            await self._insert_revision(connection, revision)

    async def add_document_tree_with_revision(
        self,
        document: dict[str, Any],
        node: dict[str, Any],
        sections: list[dict[str, Any]],
        revision: dict[str, Any],
        section_revisions: list[dict[str, Any]],
    ) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO documents (
                        id, analysis_id, agent_id, title, kind, status, current_version,
                        content_ref, content_hash, size_bytes, created_at, updated_at, finalized_at
                    )
                    VALUES (
                        :id, :analysis_id, :agent_id, :title, :kind, :status, :current_version,
                        :content_ref, :content_hash, :size_bytes, :created_at, :updated_at, :finalized_at
                    )
                    """
                ),
                document,
            )
            await self._insert_node(connection, node)
            await self._insert_revision(connection, revision)
            for section in sections:
                await self._upsert_section(connection, section)
            for section_revision in section_revisions:
                await self._insert_section_revision(connection, section_revision)

    async def update_document_with_revision(
        self, document_id: UUID, updates: dict[str, Any], revision: dict[str, Any]
    ) -> dict[str, Any] | None:
        payload = dict(updates)
        expected_version = payload.pop("expected_version", None)
        expected_status = payload.pop("expected_status", None)
        if expected_version is None or expected_status is None:
            raise ValueError("document updates must include expected_version and expected_status")
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE documents
                    SET status = :status,
                        current_version = :current_version,
                        content_ref = :content_ref,
                        content_hash = :content_hash,
                        size_bytes = :size_bytes,
                        updated_at = :updated_at,
                        finalized_at = :finalized_at
                    WHERE id = :id
                      AND current_version = :expected_version
                      AND status = :expected_status
                    RETURNING id, analysis_id, agent_id, title, kind, status, current_version,
                              content_ref, content_hash, size_bytes, created_at, updated_at, finalized_at
                    """
                ),
                {
                    "id": document_id,
                    "expected_version": expected_version,
                    "expected_status": expected_status,
                    "status": payload["status"],
                    "current_version": payload["current_version"],
                    "content_ref": payload["content_ref"],
                    "content_hash": payload["content_hash"],
                    "size_bytes": payload["size_bytes"],
                    "updated_at": payload.get("updated_at") or datetime.now(UTC),
                    "finalized_at": payload.get("finalized_at"),
                },
            )
            row = result.mappings().first()
            if row is None:
                return None
            await self._insert_revision(connection, revision)
        return dict(row)

    async def update_document_tree_with_revision(
        self,
        document_id: UUID,
        updates: dict[str, Any],
        sections: list[dict[str, Any]],
        revision: dict[str, Any],
        section_revisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        payload = dict(updates)
        expected_version = payload.pop("expected_version", None)
        expected_status = payload.pop("expected_status", None)
        if expected_version is None or expected_status is None:
            raise ValueError("document updates must include expected_version and expected_status")
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE documents
                    SET status = :status,
                        current_version = :current_version,
                        content_ref = :content_ref,
                        content_hash = :content_hash,
                        size_bytes = :size_bytes,
                        updated_at = :updated_at,
                        finalized_at = :finalized_at
                    WHERE id = :id
                      AND current_version = :expected_version
                      AND status = :expected_status
                    RETURNING id, analysis_id, agent_id, title, kind, status, current_version,
                              content_ref, content_hash, size_bytes, created_at, updated_at, finalized_at
                    """
                ),
                {
                    "id": document_id,
                    "expected_version": expected_version,
                    "expected_status": expected_status,
                    "status": payload["status"],
                    "current_version": payload["current_version"],
                    "content_ref": payload["content_ref"],
                    "content_hash": payload["content_hash"],
                    "size_bytes": payload["size_bytes"],
                    "updated_at": payload.get("updated_at") or datetime.now(UTC),
                    "finalized_at": payload.get("finalized_at"),
                },
            )
            row = result.mappings().first()
            if row is None:
                return None
            await self._insert_revision(connection, revision)
            for section in sections:
                await self._upsert_section(connection, section)
            for section_revision in section_revisions:
                await self._insert_section_revision(connection, section_revision)
        return dict(row)

    async def _insert_revision(self, connection: AsyncDbConnection, revision: dict[str, Any]) -> None:
        payload = dict(revision)
        payload.setdefault("id", new_uuid7())
        await connection.execute(
            text(
                """
                INSERT INTO document_revisions (
                    id, document_id, version, tool_call_id, operation,
                    content_ref, content_hash, size_bytes, created_at
                )
                VALUES (
                    :id, :document_id, :version, :tool_call_id, :operation,
                    :content_ref, :content_hash, :size_bytes, :created_at
                )
                """
            ).bindparams(bindparam("tool_call_id", type_=PG_UUID(as_uuid=True))),
            payload,
        )

    async def _insert_node(self, connection: AsyncDbConnection, node: dict[str, Any]) -> None:
        await connection.execute(
            text(
                """
                INSERT INTO document_nodes (
                    id, analysis_id, agent_id, parent_id, node_type, document_id,
                    title, slug, path, focus_area, sort_order, created_at, updated_at
                )
                VALUES (
                    :id, :analysis_id, :agent_id, :parent_id, :node_type, :document_id,
                    :title, :slug, :path, :focus_area, :sort_order, :created_at, :updated_at
                )
                """
            ).bindparams(bindparam("document_id", type_=PG_UUID(as_uuid=True))),
            node,
        )

    async def _upsert_section(self, connection: AsyncDbConnection, section: dict[str, Any]) -> None:
        await connection.execute(
            text(
                """
                INSERT INTO document_sections (
                    id, document_id, stable_id, title, sort_order,
                    content_ref, content_hash, size_bytes, created_at, updated_at
                )
                VALUES (
                    :id, :document_id, :stable_id, :title, :sort_order,
                    :content_ref, :content_hash, :size_bytes, :created_at, :updated_at
                )
                ON CONFLICT (document_id, stable_id) DO UPDATE
                SET title = EXCLUDED.title,
                    sort_order = EXCLUDED.sort_order,
                    content_ref = EXCLUDED.content_ref,
                    content_hash = EXCLUDED.content_hash,
                    size_bytes = EXCLUDED.size_bytes,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            section,
        )

    async def _insert_section_revision(
        self, connection: AsyncDbConnection, section_revision: dict[str, Any]
    ) -> None:
        await connection.execute(
            text(
                """
                INSERT INTO document_section_revisions (
                    id, section_id, document_id, document_revision_id, version,
                    title, sort_order, content_ref, content_hash, size_bytes, created_at
                )
                VALUES (
                    :id, :section_id, :document_id, :document_revision_id, :version,
                    :title, :sort_order, :content_ref, :content_hash, :size_bytes, :created_at
                )
                """
            ),
            section_revision,
        )
