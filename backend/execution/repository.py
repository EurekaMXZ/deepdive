from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.agent.context_items import (
    FUNCTION_CALL_OUTPUT_ITEM_TYPE,
    TOOL_CONTEXT_SOURCE,
    append_context_item_on_connection,
    function_call_output_payload,
    tool_output_idempotency_key,
)
from backend.db.connections import AsyncDbConnection, ConnectionSource, connection_from
from backend.events import EventEnvelope
from backend.events.repositories import DbOutboxSink
from backend.execution import SnapshotToolRepository
from backend.ids import new_uuid7
from backend.security import visible_path_sql


class PostgresSnapshotToolRepository(SnapshotToolRepository):
    def __init__(self, connection_or_database: ConnectionSource) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def get_file(self, snapshot_id: UUID, path: str) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT path, parent_path, name, entry_kind, content_key, content_hash,
                           size_bytes, line_count, is_binary, is_large
                    FROM snapshot_files
                    WHERE snapshot_id = :snapshot_id
                      AND path = :path
                    """
                ),
                {"snapshot_id": snapshot_id, "path": path},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

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
        if recursive:
            where = "path LIKE :prefix ESCAPE '\\'"
            params = {"prefix": _escape_like(path.rstrip("/")) + "/%" if path else "%"}
        else:
            where = "parent_path IS NOT DISTINCT FROM :parent_path"
            params = {"parent_path": path}
        glob_clause = "AND path LIKE :glob_pattern ESCAPE '\\'" if glob else ""
        offset = _cursor_offset(cursor)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT path, parent_path, name, entry_kind, content_key, content_hash,
                           size_bytes, line_count, is_binary, is_large
                    FROM snapshot_files
                    WHERE snapshot_id = :snapshot_id
                      AND {where}
                      AND {_visible_path_sql()}
                      {glob_clause}
                    ORDER BY path
                    LIMIT :limit
                    OFFSET :offset
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "limit": max_results,
                    "offset": offset,
                    "glob_pattern": _glob_to_like(glob),
                    **params,
                },
            )
        return [dict(row) for row in result.mappings().all()]

    async def search_files(
        self,
        snapshot_id: UUID,
        *,
        query: str,
        max_results: int,
        glob: str | None = None,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        glob_clause = "AND path LIKE :glob_pattern ESCAPE '\\'" if glob else ""
        offset = _cursor_offset(cursor)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT path, parent_path, name, entry_kind, content_key, content_hash,
                           size_bytes, line_count, is_binary, is_large
                    FROM snapshot_files
                    WHERE snapshot_id = :snapshot_id
                      AND lower(path) LIKE :query ESCAPE '\\'
                      AND {_visible_path_sql()}
                      {glob_clause}
                    ORDER BY path
                    LIMIT :limit
                    OFFSET :offset
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "query": "%" + _escape_like(query.lower()) + "%",
                    "limit": max_results,
                    "offset": offset,
                    "glob_pattern": _glob_to_like(glob),
                },
            )
        return [dict(row) for row in result.mappings().all()]

    async def text_files_under_prefix(self, snapshot_id: UUID, prefix: str) -> list[dict[str, Any]]:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT path, parent_path, name, entry_kind, content_key, content_hash,
                           size_bytes, line_count, is_binary, is_large
                    FROM snapshot_files
                    WHERE snapshot_id = :snapshot_id
                      AND path LIKE :prefix ESCAPE '\\'
                      AND entry_kind = 'file'
                      AND content_key IS NOT NULL
                      AND is_binary = false
                      AND is_large = false
                      AND {_visible_path_sql()}
                    ORDER BY path
                    """
                ),
                {"snapshot_id": snapshot_id, "prefix": _escape_like(prefix) + "%"},
            )
        return [dict(row) for row in result.mappings().all()]

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
        evidence_id = evidence_id or new_uuid7()
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO evidence (
                        id, agent_id, snapshot_id, tool_call_id, path, start_line,
                        end_line, content_hash, snippet_ref, created_at
                    )
                    VALUES (
                        :id, :agent_id, :snapshot_id, :tool_call_id, :path, :start_line,
                        :end_line, :content_hash, :snippet_ref, :created_at
                    )
                    """
                ),
                {
                    "id": evidence_id,
                    "agent_id": agent_id,
                    "snapshot_id": snapshot_id,
                    "tool_call_id": tool_call_id,
                    "path": path,
                    "start_line": start_line,
                    "end_line": end_line,
                    "content_hash": content_hash,
                    "snippet_ref": snippet_ref or (snippet[:4096] if snippet is not None else None),
                    "created_at": datetime.now(UTC),
                },
            )
        return str(evidence_id)


class PostgresToolCallRepository:
    claim_ttl_seconds = 900

    def __init__(self, connection_or_database: ConnectionSource) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def claim_queued_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        claim_expires_at = now + timedelta(seconds=self.claim_ttl_seconds)
        claim_owner = secrets.token_urlsafe(24)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE tool_calls
                    SET status = 'running',
                        claimed_at = :now,
                        claim_expires_at = :claim_expires_at,
                        claim_owner = :claim_owner
                    WHERE id = :tool_call_id
                      AND (
                          status = 'queued'
                          OR (
                              status = 'running'
                              AND claim_expires_at < :now
                          )
                      )
                    RETURNING
                        id,
                        agent_id,
                        snapshot_id,
                        openai_call_id,
                        tool_name,
                        arguments_json,
                        claim_owner,
                        status,
                        (
                            SELECT cs.config_json
                            FROM agent_sessions s
                            JOIN config_snapshots cs ON cs.id = s.config_snapshot_id
                            WHERE s.id = tool_calls.agent_id
                        ) AS config_json
                    """
                ),
                {
                    "tool_call_id": tool_call_id,
                    "now": now,
                    "claim_expires_at": claim_expires_at,
                    "claim_owner": claim_owner,
                },
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def renew_tool_call_claim(self, *, tool_call_id: UUID, claim_owner: str) -> bool:
        now = datetime.now(UTC)
        claim_expires_at = now + timedelta(seconds=self.claim_ttl_seconds)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE tool_calls
                    SET claimed_at = :now,
                        claim_expires_at = :claim_expires_at
                    WHERE id = :tool_call_id
                      AND status = 'running'
                      AND claim_owner = :claim_owner
                    RETURNING id
                    """
                ),
                {
                    "tool_call_id": tool_call_id,
                    "claim_owner": claim_owner,
                    "now": now,
                    "claim_expires_at": claim_expires_at,
                },
            )
        return result.mappings().first() is not None

    async def release_tool_call_claim(self, *, tool_call_id: UUID, claim_owner: str) -> bool:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE tool_calls
                    SET status = 'queued',
                        claimed_at = NULL,
                        claim_expires_at = NULL,
                        claim_owner = NULL
                    WHERE id = :tool_call_id
                      AND status = 'running'
                      AND claim_owner = :claim_owner
                    RETURNING id
                    """
                ),
                {"tool_call_id": tool_call_id, "claim_owner": claim_owner},
            )
        return result.mappings().first() is not None

    async def get_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT
                        id,
                        agent_id,
                        snapshot_id,
                        openai_call_id,
                        tool_name,
                        arguments_json,
                        status,
                        result_summary,
                        error_code,
                        error_message
                    FROM tool_calls
                    WHERE id = :tool_call_id
                    """
                ),
                {"tool_call_id": tool_call_id},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def get_analysis_status(self, analysis_id: UUID) -> str | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT status
                    FROM analyses
                    WHERE id = :analysis_id
                    """
                ),
                {"analysis_id": analysis_id},
            )
        row = result.mappings().first()
        return str(row["status"]) if row is not None else None

    async def mark_started(self, tool_call_id: UUID) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE tool_calls
                    SET status = 'running',
                        claimed_at = :claimed_at,
                        claim_expires_at = :claim_expires_at,
                        claim_owner = :claim_owner
                    WHERE id = :tool_call_id
                      AND status = 'queued'
                    """
                ),
                {
                    "tool_call_id": tool_call_id,
                    "claimed_at": datetime.now(UTC),
                    "claim_expires_at": datetime.now(UTC) + timedelta(seconds=self.claim_ttl_seconds),
                    "claim_owner": secrets.token_urlsafe(24),
                },
            )

    async def mark_completed(
        self,
        *,
        tool_call_id: UUID,
        result: dict[str, Any],
        result_ref: str | None = None,
        duration_ms: int,
        permission_decision: str = "allow",
    ) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE tool_calls
                    SET status = 'completed',
                        permission_decision = :permission_decision,
                        result_ref = :result_ref,
                        result_summary = :result_summary,
                        duration_ms = :duration_ms,
                        claimed_at = NULL,
                        claim_expires_at = NULL,
                        claim_owner = NULL,
                        completed_at = :completed_at
                    WHERE id = :tool_call_id
                      AND status <> 'cancelled'
                    """
                ),
                {
                    "tool_call_id": tool_call_id,
                    "permission_decision": permission_decision,
                    "result_ref": result_ref,
                    "result_summary": json.dumps(result, ensure_ascii=False),
                    "duration_ms": duration_ms,
                    "completed_at": datetime.now(UTC),
                },
            )

    async def mark_failed(
        self,
        *,
        tool_call_id: UUID,
        status: str,
        error_code: str,
        error_message: str,
        duration_ms: int,
        result: dict[str, Any] | None = None,
        result_ref: str | None = None,
        permission_decision: str | None = None,
    ) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE tool_calls
                    SET status = :status,
                        permission_decision = :permission_decision,
                        result_ref = :result_ref,
                        result_summary = :result_summary,
                        error_code = :error_code,
                        error_message = :error_message,
                        duration_ms = :duration_ms,
                        claimed_at = NULL,
                        claim_expires_at = NULL,
                        claim_owner = NULL,
                        completed_at = :completed_at
                    WHERE id = :tool_call_id
                      AND status <> 'cancelled'
                    """
                ),
                {
                    "tool_call_id": tool_call_id,
                    "status": status,
                    "permission_decision": permission_decision,
                    "result_ref": result_ref,
                    "result_summary": json.dumps(result, ensure_ascii=False) if result is not None else None,
                    "error_code": error_code,
                    "error_message": error_message[:4096],
                    "duration_ms": duration_ms,
                    "completed_at": datetime.now(UTC),
                },
            )

    async def finalize_tool_call(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        tool_call_id: UUID,
        status: str,
        result: dict[str, Any],
        result_ref: str | None = None,
        duration_ms: int,
        permission_decision: str,
        error_code: str | None,
        error_message: str | None,
        claim_owner: str | None,
        event: EventEnvelope,
    ) -> bool:
        async with self._connection() as connection:
            updated = await _update_terminal_tool_call(
                connection,
                tool_call_id=tool_call_id,
                status=status,
                result=result,
                result_ref=result_ref,
                duration_ms=duration_ms,
                permission_decision=permission_decision,
                error_code=error_code,
                error_message=error_message,
                claim_owner=claim_owner,
            )
            if not updated:
                return False
            await _append_tool_result_context_item(
                connection,
                agent_id=agent_id,
                tool_call_id=tool_call_id,
                result=result,
            )
            await self._add_stream_event_on_connection(
                connection,
                analysis_id=analysis_id,
                agent_id=agent_id,
                event_type="tool_result",
                payload=result,
            )
            await DbOutboxSink(connection).add(event)
        return True

    async def add_stream_event(
        self, *, analysis_id: UUID, agent_id: UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        async with self._connection() as connection:
            await self._add_stream_event_on_connection(
                connection,
                analysis_id=analysis_id,
                agent_id=agent_id,
                event_type=event_type,
                payload=payload,
            )

    async def _add_stream_event_on_connection(
        self,
        connection: AsyncDbConnection,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        await connection.scalar(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:analysis_id, 0))"),
            {"analysis_id": str(analysis_id)},
        )
        seq = await connection.scalar(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_stream_events WHERE analysis_id = :analysis_id"),
            {"analysis_id": analysis_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO agent_stream_events (
                    id, analysis_id, agent_id, turn_id, seq, event_type,
                    payload_json, attempt, response_id, state, created_at
                )
                VALUES (
                    :id, :analysis_id, :agent_id, NULL, :seq, :event_type,
                    :payload_json, NULL, NULL, NULL, :created_at
                )
                """
            ).bindparams(bindparam("payload_json", type_=JSONB)),
            {
                "id": new_uuid7(),
                "analysis_id": analysis_id,
                "agent_id": agent_id,
                "seq": seq,
                "event_type": event_type,
                "payload_json": payload,
                "created_at": datetime.now(UTC),
            },
        )

    async def add_outbox(self, event: EventEnvelope) -> None:
        async with self._connection() as connection:
            await DbOutboxSink(connection).add(event)


async def _update_terminal_tool_call(
    connection: AsyncDbConnection,
    *,
    tool_call_id: UUID,
    status: str,
    result: dict[str, Any],
    result_ref: str | None,
    duration_ms: int,
    permission_decision: str,
    error_code: str | None,
    error_message: str | None,
    claim_owner: str | None,
) -> bool:
    update_result = await connection.execute(
        text(
            """
            UPDATE tool_calls
            SET status = :status,
                permission_decision = :permission_decision,
                result_ref = :result_ref,
                result_summary = :result_summary,
                duration_ms = :duration_ms,
                error_code = :error_code,
                error_message = :error_message,
                claimed_at = NULL,
                claim_expires_at = NULL,
                claim_owner = NULL,
                completed_at = :completed_at
            WHERE id = :tool_call_id
              AND status <> 'cancelled'
              AND (:claim_owner IS NULL OR claim_owner = :claim_owner)
            """
        ).bindparams(bindparam("claim_owner", type_=String())),
        {
            "tool_call_id": tool_call_id,
            "status": status,
            "permission_decision": permission_decision,
            "result_ref": result_ref,
            "result_summary": json.dumps(result, ensure_ascii=False),
            "duration_ms": duration_ms,
            "error_code": error_code,
            "error_message": error_message[:4096] if error_message is not None else None,
            "claim_owner": claim_owner,
            "completed_at": datetime.now(UTC),
        },
    )
    return int(getattr(update_result, "rowcount", 0) or 0) > 0


async def _append_tool_result_context_item(
    connection: AsyncDbConnection,
    *,
    agent_id: UUID,
    tool_call_id: UUID,
    result: dict[str, Any],
) -> None:
    lookup = await connection.execute(
        text(
            """
            SELECT turn_id, openai_call_id
            FROM tool_calls
            WHERE id = :tool_call_id
            """
        ),
        {"tool_call_id": tool_call_id},
    )
    row = lookup.mappings().first()
    if row is None:
        return
    await append_context_item_on_connection(
        connection,
        agent_id=agent_id,
        turn_id=row["turn_id"],
        item_type=FUNCTION_CALL_OUTPUT_ITEM_TYPE,
        payload=function_call_output_payload(call_id=row["openai_call_id"], output=result),
        response_id=None,
        source=TOOL_CONTEXT_SOURCE,
        idempotency_key=tool_output_idempotency_key(row["openai_call_id"]),
    )


def _cursor_offset(value: str | None) -> int:
    if value is None or str(value).strip() == "":
        return 0
    offset = int(str(value))
    if offset < 0:
        raise ValueError("cursor must be non-negative")
    return offset


def _glob_to_like(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.replace("\\", "/")
    normalized = _escape_like(normalized)
    if normalized.startswith("**/"):
        normalized = "%" + normalized[2:]
    normalized = normalized.replace("**", "%").replace("*", "%")
    return normalized


def _visible_path_sql() -> str:
    return visible_path_sql()


def _escape_like(value: str) -> str:
    escaped: list[str] = []
    for char in value:
        if char in {"%", "_", "\\"}:
            escaped.append("\\" + char)
        else:
            escaped.append(char)
    return "".join(escaped)
