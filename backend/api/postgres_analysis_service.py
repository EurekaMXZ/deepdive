from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.api.pagination import decode_list_cursor
from backend.api.records import AgentStreamEventRecord, AnalysisRecord
from backend.config import DEFAULT_CONFIG_VERSION, AppConfig, create_config_snapshot
from backend.events import EventEnvelope, EventType
from backend.events.repositories import DbOutboxSink
from backend.execution.tool_registry import DEFAULT_TOOL_REGISTRY_VERSION
from backend.ids import new_uuid7


class PostgresAnalysisService:
    supports_live_events = True

    def __init__(
        self,
        database,
        *,
        config: AppConfig | None = None,
        config_version: str = DEFAULT_CONFIG_VERSION,
    ) -> None:
        self._database = database
        self._config = config or AppConfig.default()
        self._config_version = config_version

    async def create(
        self,
        *,
        repository_url: str,
        requested_ref: str,
        analysis_profile_id: UUID | None = None,
    ) -> AnalysisRecord:
        now = datetime.now(UTC)
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        config_snapshot = create_config_snapshot(self._config, config_version=self._config_version)
        repository_url_hash = _sha256_text(repository_url)

        async with self._database.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO config_snapshots (id, config_version, content_hash, config_json, created_at)
                    VALUES (:id, :config_version, :content_hash, :config_json, :created_at)
                    """
                ).bindparams(bindparam("config_json", type_=JSONB)),
                {
                    "id": config_snapshot.id,
                    "config_version": config_snapshot.config_version,
                    "content_hash": config_snapshot.content_hash,
                    "config_json": config_snapshot.config_json,
                    "created_at": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO analyses (
                        id,
                        tenant_id,
                        repository_url,
                        repository_url_hash,
                        requested_ref,
                        analysis_profile_id,
                        config_snapshot_id,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :id,
                        :tenant_id,
                        :repository_url,
                        :repository_url_hash,
                        :requested_ref,
                        :analysis_profile_id,
                        :config_snapshot_id,
                        :status,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "id": analysis_id,
                    "tenant_id": None,
                    "repository_url": repository_url,
                    "repository_url_hash": repository_url_hash,
                    "requested_ref": requested_ref,
                    "analysis_profile_id": analysis_profile_id,
                    "config_snapshot_id": config_snapshot.id,
                    "status": "queued",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO agent_sessions (
                        id,
                        analysis_id,
                        snapshot_id,
                        parent_agent_id,
                        config_snapshot_id,
                        status,
                        goal_ref,
                        effective_model,
                        effective_prompt_version,
                        effective_tool_registry_version,
                        effective_limits_json,
                        effective_runtime_json,
                        latest_response_id,
                        turn_count,
                        max_turns,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :id,
                        :analysis_id,
                        :snapshot_id,
                        :parent_agent_id,
                        :config_snapshot_id,
                        :status,
                        :goal_ref,
                        :effective_model,
                        :effective_prompt_version,
                        :effective_tool_registry_version,
                        :effective_limits_json,
                        :effective_runtime_json,
                        :latest_response_id,
                        :turn_count,
                        :max_turns,
                        :created_at,
                        :updated_at
                    )
                    """
                ).bindparams(
                    bindparam("effective_limits_json", type_=JSONB),
                    bindparam("effective_runtime_json", type_=JSONB),
                ),
                {
                    "id": agent_id,
                    "analysis_id": analysis_id,
                    "snapshot_id": None,
                    "parent_agent_id": None,
                    "config_snapshot_id": config_snapshot.id,
                    "status": "queued",
                    "goal_ref": self._goal_ref(),
                    "effective_model": self._config.openai.model,
                    "effective_prompt_version": self._config_version,
                    "effective_tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                    "effective_limits_json": self._effective_limits(),
                    "effective_runtime_json": self._effective_runtime(),
                    "latest_response_id": None,
                    "turn_count": 0,
                    "max_turns": self._max_turns(),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await DbOutboxSink(connection).add(
                EventEnvelope.new(
                    event_type=EventType.ANALYSIS_REQUESTED,
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    payload={
                        "repository_url": repository_url,
                        "requested_ref": requested_ref,
                        "analysis_profile_id": str(analysis_profile_id) if analysis_profile_id else None,
                        "config_snapshot_id": str(config_snapshot.id),
                    },
                )
            )

        return AnalysisRecord(
            analysis_id=analysis_id,
            agent_id=agent_id,
            snapshot_id=None,
            status="queued",
            repository_url=repository_url,
            requested_ref=requested_ref,
            resolved_commit_sha=None,
            created_at=now,
            updated_at=now,
        )

    async def list(
        self,
        *,
        status: str | None = None,
        repository_url_hash: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[AnalysisRecord]:
        params = {
            "status": status,
            "repository_url_hash": repository_url_hash,
            "created_after": created_after,
            "created_before": created_before,
            "limit": limit + 1,
        }
        clauses = []
        if status is not None:
            clauses.append("a.status = :status")
        if repository_url_hash is not None:
            clauses.append("a.repository_url_hash = :repository_url_hash")
        if created_after is not None:
            clauses.append("a.created_at >= :created_after")
        if created_before is not None:
            clauses.append("a.created_at < :created_before")
        cursor_values = decode_list_cursor(cursor)
        if cursor_values is not None:
            params["cursor_created_at"] = cursor_values[0]
            params["cursor_id"] = cursor_values[1]
            clauses.append("(a.created_at, a.id) < (:cursor_created_at, :cursor_id)")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        async with self._database.begin() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT
                        a.id AS analysis_id,
                        s.id AS agent_id,
                        s.snapshot_id AS snapshot_id,
                        a.status AS status,
                        a.repository_url AS repository_url,
                        a.requested_ref AS requested_ref,
                        snap.resolved_commit_sha AS resolved_commit_sha,
                        a.error_code AS error_code,
                        a.error_message AS error_message,
                        a.created_at AS created_at,
                        a.updated_at AS updated_at
                    FROM analyses a
                    JOIN agent_sessions s ON s.analysis_id = a.id
                    LEFT JOIN snapshots snap ON snap.id = s.snapshot_id
                    {where}
                    ORDER BY a.created_at DESC, a.id DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
            return [_record_from_row(row) for row in result.mappings().all()]

    async def get(self, analysis_id: UUID) -> AnalysisRecord | None:
        async with self._database.begin() as connection:
            return await _fetch_analysis_record(connection, analysis_id)

    async def cancel(self, analysis_id: UUID) -> AnalysisRecord | None:
        async with self._database.begin() as connection:
            record = await _fetch_analysis_record(connection, analysis_id)
            if record is None:
                return None
            if record.status in {"completed", "failed", "cancelled"}:
                return record

            now = datetime.now(UTC)
            result = await connection.execute(
                text(
                    """
                    UPDATE analyses
                    SET status = :status, updated_at = :updated_at
                    WHERE id = :analysis_id
                      AND status NOT IN ('completed', 'failed', 'cancelled')
                    RETURNING id
                    """
                ),
                {"analysis_id": analysis_id, "status": "cancelling", "updated_at": now},
            )
            if result.mappings().first() is None:
                return await _fetch_analysis_record(connection, analysis_id)
            await connection.execute(
                text(
                    """
                    UPDATE agent_sessions
                    SET status = :status, updated_at = :updated_at
                    WHERE analysis_id = :analysis_id
                      AND status NOT IN ('completed', 'failed', 'cancelled')
                    """
                ),
                {"analysis_id": analysis_id, "status": "cancelled", "updated_at": now},
            )
            await connection.execute(
                text(
                    """
                    UPDATE tool_calls
                    SET status = 'cancelled',
                        permission_decision = 'deny',
                        error_code = 'TOOL_CALL_CANCELLED',
                        error_message = 'Analysis was cancelled before this tool call completed.',
                        claimed_at = NULL,
                        claim_expires_at = NULL,
                        completed_at = :completed_at
                    WHERE agent_id = :agent_id
                      AND status NOT IN ('completed', 'failed', 'denied', 'cancelled')
                    """
                ),
                {"agent_id": record.agent_id, "completed_at": now},
            )
            await DbOutboxSink(connection).add(
                EventEnvelope.new(
                    event_type=EventType.ANALYSIS_CANCEL_REQUESTED,
                    analysis_id=record.analysis_id,
                    agent_id=record.agent_id,
                    snapshot_id=record.snapshot_id,
                    payload={},
                )
            )

            record.status = "cancelling"
            record.updated_at = now
            return record

    async def stream_events(self, analysis_id: UUID, *, after_seq: int = 0) -> list[AgentStreamEventRecord]:
        async with self._database.begin() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT seq, event_type, payload_json
                    FROM agent_stream_events
                    WHERE analysis_id = :analysis_id
                      AND seq > :after_seq
                    ORDER BY seq
                    LIMIT 1000
                    """
                ),
                {"analysis_id": analysis_id, "after_seq": after_seq},
            )
            return [
                AgentStreamEventRecord(
                    seq=row["seq"],
                    event_type=row["event_type"],
                    payload_json=row["payload_json"],
                )
                for row in result.mappings().all()
            ]

    async def analysis_status(self, analysis_id: UUID) -> str | None:
        async with self._database.begin() as connection:
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
            return row["status"] if row is not None else None

    def _goal_ref(self) -> str:
        profile = self._config.analysis.profiles[self._config.analysis.default_profile]
        return profile.goal_file

    def _max_turns(self) -> int:
        profile = self._config.analysis.profiles[self._config.analysis.default_profile]
        return profile.max_turns

    def _effective_limits(self) -> dict[str, int]:
        profile = self._config.analysis.profiles[self._config.analysis.default_profile]
        return {
            "max_turns": profile.max_turns,
            "max_tool_calls": profile.max_tool_calls,
            "auto_compact_threshold_tokens": profile.auto_compact_threshold_tokens,
        }

    def _effective_runtime(self) -> dict[str, object]:
        return {
            "reasoning_effort": self._config.openai.reasoning_effort,
            "reasoning_summary": self._config.openai.reasoning_summary,
            "show_reasoning_summary": self._config.openai.show_reasoning_summary,
            "service_tier": self._config.openai.service_tier,
            "parallel_tool_calls": self._config.openai.parallel_tool_calls,
            "use_previous_response_id": self._config.openai.use_previous_response_id,
        }


async def _fetch_analysis_record(connection, analysis_id: UUID) -> AnalysisRecord | None:
    result = await connection.execute(
        text(
            """
            SELECT
                a.id AS analysis_id,
                s.id AS agent_id,
                s.snapshot_id AS snapshot_id,
                a.status AS status,
                a.repository_url AS repository_url,
                a.requested_ref AS requested_ref,
                snap.resolved_commit_sha AS resolved_commit_sha,
                a.error_code AS error_code,
                a.error_message AS error_message,
                a.created_at AS created_at,
                a.updated_at AS updated_at
            FROM analyses a
            JOIN agent_sessions s ON s.analysis_id = a.id
            LEFT JOIN snapshots snap ON snap.id = s.snapshot_id
            WHERE a.id = :analysis_id
            """
        ),
        {"analysis_id": analysis_id},
    )
    row = result.mappings().first()
    return _record_from_row(row) if row is not None else None


def _record_from_row(row) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=row["analysis_id"],
        agent_id=row["agent_id"],
        snapshot_id=row["snapshot_id"],
        status=row["status"],
        repository_url=row["repository_url"],
        requested_ref=row["requested_ref"],
        resolved_commit_sha=row["resolved_commit_sha"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
    )


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
