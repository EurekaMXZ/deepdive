from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.api.pagination import decode_list_cursor
from backend.api.records import AgentStreamEventRecord, AnalysisRecord, RepositorySearchRecord
from backend.api.repository_query import parse_repository_suggestion_query
from backend.api.repository_search import canonicalize_repository_url, normalize_repository_search_query
from backend.config import DEFAULT_CONFIG_VERSION, AppConfig, create_config_snapshot
from backend.db.connections import AsyncDbConnection
from backend.events import EventEnvelope, EventType
from backend.events.repositories import DbOutboxSink
from backend.execution.tool_registry import DEFAULT_TOOL_REGISTRY_VERSION
from backend.ids import new_uuid7


class AnalysisDatabase(Protocol):
    def begin(self) -> AbstractAsyncContextManager[AsyncDbConnection]: ...


class PostgresAnalysisService:
    supports_live_events = True

    def __init__(
        self,
        database: AnalysisDatabase,
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
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord:
        now = datetime.now(UTC)
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        config_snapshot = create_config_snapshot(self._config, config_version=self._config_version)
        canonical_repository = canonicalize_repository_url(repository_url)
        repository_url = canonical_repository.repository_url
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
                        created_by_user_id,
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
                        :created_by_user_id,
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
                    "tenant_id": tenant_id,
                    "created_by_user_id": created_by_user_id,
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
            if tenant_id is not None and created_by_user_id is not None:
                await connection.execute(
                    text(
                        """
                        INSERT INTO analysis_repositories (
                            id,
                            tenant_id,
                            created_by_user_id,
                            repository_url,
                            repository_url_hash,
                            repository_host,
                            repository_owner,
                            repository_name,
                            repository_label,
                            search_text,
                            latest_analysis_id,
                            latest_status,
                            latest_requested_ref,
                            latest_resolved_commit_sha,
                            analysis_count,
                            completed_analysis_count,
                            last_analyzed_at,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :id,
                            :tenant_id,
                            :created_by_user_id,
                            :repository_url,
                            :repository_url_hash,
                            :repository_host,
                            :repository_owner,
                            :repository_name,
                            :repository_label,
                            :search_text,
                            :latest_analysis_id,
                            :latest_status,
                            :latest_requested_ref,
                            :latest_resolved_commit_sha,
                            :analysis_count,
                            :completed_analysis_count,
                            :last_analyzed_at,
                            :created_at,
                            :updated_at
                        )
                        ON CONFLICT (tenant_id, created_by_user_id, repository_url_hash) DO UPDATE
                        SET repository_url = EXCLUDED.repository_url,
                            repository_host = EXCLUDED.repository_host,
                            repository_owner = EXCLUDED.repository_owner,
                            repository_name = EXCLUDED.repository_name,
                            repository_label = EXCLUDED.repository_label,
                            search_text = EXCLUDED.search_text,
                            latest_analysis_id = EXCLUDED.latest_analysis_id,
                            latest_status = EXCLUDED.latest_status,
                            latest_requested_ref = EXCLUDED.latest_requested_ref,
                            latest_resolved_commit_sha = EXCLUDED.latest_resolved_commit_sha,
                            analysis_count = analysis_repositories.analysis_count + 1,
                            completed_analysis_count = analysis_repositories.completed_analysis_count,
                            last_analyzed_at = EXCLUDED.last_analyzed_at,
                            updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "id": new_uuid7(),
                        "tenant_id": tenant_id,
                        "created_by_user_id": created_by_user_id,
                        "repository_url": canonical_repository.repository_url,
                        "repository_url_hash": repository_url_hash,
                        "repository_host": canonical_repository.repository_host,
                        "repository_owner": canonical_repository.repository_owner,
                        "repository_name": canonical_repository.repository_name,
                        "repository_label": canonical_repository.repository_label,
                        "search_text": canonical_repository.search_text,
                        "latest_analysis_id": analysis_id,
                        "latest_status": "queued",
                        "latest_requested_ref": requested_ref,
                        "latest_resolved_commit_sha": None,
                        "analysis_count": 1,
                        "completed_analysis_count": 0,
                        "last_analyzed_at": now,
                        "created_at": now,
                        "updated_at": now,
                    },
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
            tenant_id=tenant_id,
            created_by_user_id=created_by_user_id,
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
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[AnalysisRecord]:
        params: dict[str, str | datetime | UUID | int | None] = {
            "status": status,
            "repository_url_hash": repository_url_hash,
            "created_after": created_after,
            "created_before": created_before,
            "limit": limit,
            "tenant_id": tenant_id,
            "created_by_user_id": created_by_user_id,
        }
        clauses: list[str] = []
        if status is not None:
            clauses.append("a.status = :status")
        if repository_url_hash is not None:
            clauses.append("a.repository_url_hash = :repository_url_hash")
        if created_after is not None:
            clauses.append("a.created_at >= :created_after")
        if created_before is not None:
            clauses.append("a.created_at < :created_before")
        if tenant_id is not None:
            clauses.append("a.tenant_id = :tenant_id")
        if created_by_user_id is not None:
            clauses.append("a.created_by_user_id = :created_by_user_id")
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
                        a.tenant_id AS tenant_id,
                        a.created_by_user_id AS created_by_user_id,
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

    async def suggest(
        self,
        *,
        repository_query: str,
        limit: int = 6,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[AnalysisRecord]:
        parsed_query = parse_repository_suggestion_query(repository_query)
        if parsed_query is None:
            return []
        params: dict[str, str | UUID | int | None] = {
            "repository_url_hash": _sha256_text(parsed_query.repository_url) if parsed_query.repository_url else None,
            "repository_url_prefix": f"{parsed_query.repository_url_prefix}%"
            if parsed_query.repository_url_prefix
            else None,
            "limit": limit,
            "tenant_id": tenant_id,
            "created_by_user_id": created_by_user_id,
        }
        clauses = (
            ["a.repository_url_hash = :repository_url_hash"]
            if parsed_query.repository_url
            else ["a.repository_url LIKE :repository_url_prefix"]
        )
        if tenant_id is not None:
            clauses.append("a.tenant_id = :tenant_id")
        if created_by_user_id is not None:
            clauses.append("a.created_by_user_id = :created_by_user_id")
        where = "WHERE " + " AND ".join(clauses)
        async with self._database.begin() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT
                        a.id AS analysis_id,
                        s.id AS agent_id,
                        s.snapshot_id AS snapshot_id,
                        a.status AS status,
                        a.tenant_id AS tenant_id,
                        a.created_by_user_id AS created_by_user_id,
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
                    ORDER BY a.updated_at DESC, a.created_at DESC, a.id DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
            return [_record_from_row(row) for row in result.mappings().all()]

    async def search_repositories(
        self,
        *,
        query: str,
        limit: int = 8,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[RepositorySearchRecord]:
        normalized_query = normalize_repository_search_query(query)
        if not normalized_query or tenant_id is None or created_by_user_id is None:
            return []
        search_pattern = f"%{normalized_query}%"
        prefix_pattern = f"{normalized_query}%"
        async with self._database.begin() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT
                        repository_url,
                        repository_label,
                        latest_analysis_id,
                        latest_status,
                        latest_requested_ref,
                        latest_resolved_commit_sha,
                        analysis_count,
                        completed_analysis_count,
                        last_analyzed_at,
                        CASE
                            WHEN lower(repository_label) = :query THEN 100
                            WHEN lower(repository_label) LIKE :prefix_pattern THEN 90
                            WHEN lower(coalesce(repository_name, '')) = :query THEN 85
                            WHEN lower(coalesce(repository_name, '')) LIKE :prefix_pattern THEN 80
                            WHEN search_text LIKE :search_pattern THEN 70
                            ELSE 50 + similarity(search_text, :query) * 30
                        END AS rank
                    FROM analysis_repositories
                    WHERE tenant_id = :tenant_id
                      AND created_by_user_id = :created_by_user_id
                      AND (
                          search_text LIKE :search_pattern
                          OR repository_label % :query
                          OR search_text % :query
                      )
                    ORDER BY rank DESC, last_analyzed_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "query": normalized_query,
                    "search_pattern": search_pattern,
                    "prefix_pattern": prefix_pattern,
                    "limit": limit,
                    "tenant_id": tenant_id,
                    "created_by_user_id": created_by_user_id,
                },
            )
        return [_repository_search_record_from_row(row) for row in result.mappings().all()]

    async def get(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord | None:
        async with self._database.begin() as connection:
            return await _fetch_analysis_record(
                connection,
                analysis_id,
                tenant_id=tenant_id,
                created_by_user_id=created_by_user_id,
            )

    async def cancel(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord | None:
        async with self._database.begin() as connection:
            record = await _fetch_analysis_record(
                connection,
                analysis_id,
                tenant_id=tenant_id,
                created_by_user_id=created_by_user_id,
            )
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
                return await _fetch_analysis_record(
                    connection,
                    analysis_id,
                    tenant_id=tenant_id,
                    created_by_user_id=created_by_user_id,
                )
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

    async def stream_events(
        self,
        analysis_id: UUID,
        *,
        after_seq: int = 0,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[AgentStreamEventRecord]:
        record = await self.get(analysis_id, tenant_id=tenant_id, created_by_user_id=created_by_user_id)
        if record is None:
            return []
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
                    seq=int(row["seq"]),
                    event_type=str(row["event_type"]),
                    payload_json=_mapping_to_dict(row["payload_json"]),
                )
                for row in result.mappings().all()
            ]

    async def analysis_status(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> str | None:
        clauses = ["id = :analysis_id"]
        params = {
            "analysis_id": analysis_id,
            "tenant_id": tenant_id,
            "created_by_user_id": created_by_user_id,
        }
        if tenant_id is not None:
            clauses.append("tenant_id = :tenant_id")
        if created_by_user_id is not None:
            clauses.append("created_by_user_id = :created_by_user_id")
        async with self._database.begin() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT status
                    FROM analyses
                    WHERE {" AND ".join(clauses)}
                    """
                ),
                params,
            )
            row = result.mappings().first()
            return str(row["status"]) if row is not None else None

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
            "transport": self._config.openai.transport,
        }


async def _fetch_analysis_record(
    connection: AsyncDbConnection,
    analysis_id: UUID,
    *,
    tenant_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
) -> AnalysisRecord | None:
    clauses = ["a.id = :analysis_id"]
    params = {
        "analysis_id": analysis_id,
        "tenant_id": tenant_id,
        "created_by_user_id": created_by_user_id,
    }
    if tenant_id is not None:
        clauses.append("a.tenant_id = :tenant_id")
    if created_by_user_id is not None:
        clauses.append("a.created_by_user_id = :created_by_user_id")
    result = await connection.execute(
        text(
            f"""
            SELECT
                a.id AS analysis_id,
                s.id AS agent_id,
                s.snapshot_id AS snapshot_id,
                a.status AS status,
                a.tenant_id AS tenant_id,
                a.created_by_user_id AS created_by_user_id,
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
            WHERE {" AND ".join(clauses)}
            """
        ),
        params,
    )
    row = result.mappings().first()
    return _record_from_row(row) if row is not None else None


def _record_from_row(row: Mapping[Any, Any]) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=cast(UUID, row["analysis_id"]),
        agent_id=cast(UUID, row["agent_id"]),
        snapshot_id=cast(UUID | None, row["snapshot_id"]),
        status=str(row["status"]),
        repository_url=str(row["repository_url"]),
        requested_ref=str(row["requested_ref"]),
        resolved_commit_sha=cast(str | None, row["resolved_commit_sha"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        error_code=cast(str | None, row.get("error_code")),
        error_message=cast(str | None, row.get("error_message")),
        tenant_id=cast(UUID | None, row.get("tenant_id")),
        created_by_user_id=cast(UUID | None, row.get("created_by_user_id")),
    )


def _repository_search_record_from_row(row: Mapping[Any, Any]) -> RepositorySearchRecord:
    return RepositorySearchRecord(
        repository_url=str(row["repository_url"]),
        repository_label=str(row["repository_label"]),
        latest_analysis_id=cast(UUID, row["latest_analysis_id"]),
        latest_status=str(row["latest_status"]),
        latest_requested_ref=str(row["latest_requested_ref"]),
        latest_resolved_commit_sha=cast(str | None, row.get("latest_resolved_commit_sha")),
        analysis_count=int(row["analysis_count"]),
        completed_analysis_count=int(row["completed_analysis_count"]),
        last_analyzed_at=cast(datetime, row["last_analyzed_at"]),
    )


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _mapping_to_dict(value: Any) -> dict[str, Any]:
    return dict(cast(Mapping[str, Any], value)) if isinstance(value, Mapping) else {}
