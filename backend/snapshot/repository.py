from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.db.connections import AsyncDbConnection
from backend.events import EventEnvelope
from backend.events.repositories import DbOutboxSink
from backend.ids import new_uuid7
from backend.snapshot.models import SnapshotBuildResult


@dataclass(frozen=True)
class ExistingSnapshot:
    id: UUID
    manifest_key: str | None
    git_bundle_key: str | None
    resolved_commit_sha: str
    tree_sha: str
    file_count: int | None


class SnapshotRepository:
    def __init__(self, connection: AsyncDbConnection) -> None:
        self._connection = connection

    async def mark_analysis_snapshotting(self, *, analysis_id: UUID, agent_id: UUID, now: datetime) -> bool:
        result = await self._connection.execute(
            text(
                """
                UPDATE analyses a
                SET status = :status, updated_at = :updated_at
                FROM agent_sessions s
                WHERE a.id = :analysis_id
                  AND s.id = :agent_id
                  AND s.analysis_id = a.id
                  AND a.status = 'snapshotting'
                  AND s.snapshot_id IS NULL
                  AND s.status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                RETURNING a.tenant_id
                """
            ),
            {
                "analysis_id": analysis_id,
                "agent_id": agent_id,
                "status": "snapshotting",
                "updated_at": now,
            },
        )
        return result.mappings().first() is not None

    async def find_ready_snapshot(self, result: SnapshotBuildResult) -> ExistingSnapshot | None:
        select_result = await self._connection.execute(
            text(
                """
                SELECT id, manifest_key, git_bundle_key, resolved_commit_sha, tree_sha, file_count
                FROM snapshots
                WHERE repository_url_hash = :repository_url_hash
                  AND resolved_commit_sha = :resolved_commit_sha
                  AND snapshot_policy_hash = :snapshot_policy_hash
                  AND status = 'ready'
                LIMIT 1
                """
            ),
            {
                "repository_url_hash": result.repository_url_hash,
                "resolved_commit_sha": result.resolved_commit_sha,
                "snapshot_policy_hash": result.snapshot_policy_hash,
            },
        )
        row = select_result.mappings().first()
        if row is None:
            return None
        return ExistingSnapshot(
            id=cast(UUID, row["id"]),
            manifest_key=cast(str | None, row["manifest_key"]),
            git_bundle_key=cast(str | None, row["git_bundle_key"]),
            resolved_commit_sha=str(row["resolved_commit_sha"]),
            tree_sha=str(row["tree_sha"]),
            file_count=cast(int | None, row["file_count"]),
        )

    async def insert_snapshot(self, result: SnapshotBuildResult, *, now: datetime) -> bool:
        insert_result = await self._connection.execute(
            text(
                """
                INSERT INTO snapshots (
                    id,
                    tenant_id,
                    repository_url_hash,
                    requested_ref,
                    resolved_commit_sha,
                    tree_sha,
                    snapshot_policy_hash,
                    status,
                    manifest_key,
                    git_bundle_key,
                    file_count,
                    total_bytes,
                    created_at,
                    ready_at
                )
                VALUES (
                    :id,
                    :tenant_id,
                    :repository_url_hash,
                    :requested_ref,
                    :resolved_commit_sha,
                    :tree_sha,
                    :snapshot_policy_hash,
                    :status,
                    :manifest_key,
                    :git_bundle_key,
                    :file_count,
                    :total_bytes,
                    :created_at,
                    :ready_at
                )
                ON CONFLICT (repository_url_hash, resolved_commit_sha, snapshot_policy_hash) DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": result.snapshot_id,
                "tenant_id": None,
                "repository_url_hash": result.repository_url_hash,
                "requested_ref": result.requested_ref,
                "resolved_commit_sha": result.resolved_commit_sha,
                "tree_sha": result.tree_sha,
                "snapshot_policy_hash": result.snapshot_policy_hash,
                "status": "ready",
                "manifest_key": result.manifest_key,
                "git_bundle_key": result.git_bundle_key,
                "file_count": result.file_count,
                "total_bytes": result.total_bytes,
                "created_at": now,
                "ready_at": now,
            },
        )
        row = insert_result.mappings().first()
        if row is not None:
            return True
        return int(cast(Any, getattr(insert_result, "rowcount", 1)) or 0) != 0

    async def insert_snapshot_files(self, result: SnapshotBuildResult, *, now: datetime) -> None:
        for file in result.files:
            await self._connection.execute(
                text(
                    """
                    INSERT INTO snapshot_files (
                        id,
                        snapshot_id,
                        path,
                        path_hash,
                        parent_path,
                        name,
                        entry_kind,
                        git_mode,
                        git_blob_oid,
                        content_key,
                        content_hash,
                        size_bytes,
                        line_count,
                        is_binary,
                        is_large,
                        created_at
                    )
                    VALUES (
                        :id,
                        :snapshot_id,
                        :path,
                        :path_hash,
                        :parent_path,
                        :name,
                        :entry_kind,
                        :git_mode,
                        :git_blob_oid,
                        :content_key,
                        :content_hash,
                        :size_bytes,
                        :line_count,
                        :is_binary,
                        :is_large,
                        :created_at
                    )
                    ON CONFLICT (snapshot_id, path) DO NOTHING
                    """
                ),
                {
                    "id": new_uuid7(),
                    "snapshot_id": result.snapshot_id,
                    "path": file.path,
                    "path_hash": file.path_hash,
                    "parent_path": file.parent_path,
                    "name": file.name,
                    "entry_kind": file.entry_kind,
                    "git_mode": file.git_mode,
                    "git_blob_oid": file.git_blob_oid,
                    "content_key": file.content_key,
                    "content_hash": file.content_hash,
                    "size_bytes": file.size_bytes,
                    "line_count": file.line_count,
                    "is_binary": file.is_binary,
                    "is_large": file.is_large,
                    "created_at": now,
                },
            )

    async def insert_instruction_files(self, result: SnapshotBuildResult, *, now: datetime) -> None:
        for instruction in result.instructions:
            await self._connection.execute(
                text(
                    """
                    INSERT INTO agent_instruction_files (
                        id,
                        snapshot_id,
                        path,
                        scope_path,
                        depth,
                        content_hash,
                        content_ref,
                        created_at
                    )
                    VALUES (
                        :id,
                        :snapshot_id,
                        :path,
                        :scope_path,
                        :depth,
                        :content_hash,
                        :content_ref,
                        :created_at
                    )
                    """
                ),
                {
                    "id": new_uuid7(),
                    "snapshot_id": result.snapshot_id,
                    "path": instruction.path,
                    "scope_path": instruction.scope_path,
                    "depth": instruction.depth,
                    "content_hash": instruction.content_hash,
                    "content_ref": instruction.content_ref,
                    "created_at": now,
                },
            )

    async def associate_snapshot(self, *, event: EventEnvelope, snapshot_id: UUID, now: datetime) -> bool:
        result = await self._connection.execute(
            text(
                """
                UPDATE agent_sessions
                SET snapshot_id = :snapshot_id,
                    status = :status,
                    updated_at = :updated_at
                WHERE id = :agent_id
                  AND analysis_id = :analysis_id
                  AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                RETURNING id
                """
            ),
            {
                "snapshot_id": snapshot_id,
                "status": "queued",
                "updated_at": now,
                "agent_id": event.agent_id,
                "analysis_id": event.analysis_id,
            },
        )
        if result.mappings().first() is None:
            return False
        await self._connection.execute(
            text(
                """
                UPDATE analyses
                SET status = :status,
                    updated_at = :updated_at
                WHERE id = :analysis_id
                  AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                """
            ),
            {
                "status": "running",
                "updated_at": now,
                "analysis_id": event.analysis_id,
            },
        )
        return True

    async def mark_failed(self, *, event: EventEnvelope, error_code: str, error_message: str, now: datetime) -> bool:
        if event.analysis_id is None or event.agent_id is None:
            raise ValueError("Snapshot failure event requires analysis_id and agent_id")
        result = await self._connection.execute(
            text(
                """
                UPDATE analyses
                SET status = :status,
                    updated_at = :updated_at,
                    completed_at = :completed_at,
                    error_code = :error_code,
                    error_message = :error_message
                WHERE id = :analysis_id
                  AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                RETURNING id
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "status": "failed",
                "updated_at": now,
                "completed_at": now,
                "error_code": error_code,
                "error_message": error_message[:4096],
            },
        )
        if result.mappings().first() is None:
            return False
        await self._connection.execute(
            text(
                """
                UPDATE agent_sessions
                SET status = :status,
                    updated_at = :updated_at
                WHERE id = :agent_id
                  AND analysis_id = :analysis_id
                  AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "agent_id": event.agent_id,
                "status": "failed",
                "updated_at": now,
            },
        )
        await self._add_stream_error(
            analysis_id=event.analysis_id,
            agent_id=event.agent_id,
            error_code=error_code,
            error_message=error_message,
            now=now,
        )
        return True

    async def add_outbox(self, envelope: EventEnvelope) -> None:
        await DbOutboxSink(self._connection).add(envelope)

    async def _add_stream_error(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> None:
        await self._connection.scalar(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:analysis_id, 0))"),
            {"analysis_id": str(analysis_id)},
        )
        seq = await self._connection.scalar(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_stream_events WHERE analysis_id = :analysis_id"),
            {"analysis_id": analysis_id},
        )
        await self._connection.execute(
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
                "event_type": "error",
                "payload_json": {
                    "error_code": error_code,
                    "error_message": error_message[:4096],
                },
                "created_at": now,
            },
        )
