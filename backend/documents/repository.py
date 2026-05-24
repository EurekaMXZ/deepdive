from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

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
