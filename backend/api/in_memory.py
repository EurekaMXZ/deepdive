from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from backend.api.pagination import cursor_offset, decode_list_cursor
from backend.api.records import AgentStreamEventRecord, AnalysisRecord, RepositorySearchRecord
from backend.api.repository_query import parse_repository_suggestion_query
from backend.api.repository_search import (
    RepositoryIndexEntry,
    canonicalize_repository_url,
    repository_record_from_entry,
    repository_search_score,
)
from backend.events import EventEnvelope, EventType
from backend.ids import new_uuid7


class OutboxSink(Protocol):
    def add(self, event: EventEnvelope) -> None: ...


class NullOutboxSink:
    def add(self, event: EventEnvelope) -> None:
        del event


class InMemoryAnalysisService:
    supports_live_events = False

    def __init__(self, *, outbox: OutboxSink | None = None) -> None:
        self._records: dict[UUID, AnalysisRecord] = {}
        self._outbox = outbox or NullOutboxSink()

    def create(
        self,
        *,
        repository_url: str,
        requested_ref: str,
        analysis_profile_id: UUID | None = None,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord:
        del analysis_profile_id
        now = datetime.now(UTC)
        record = AnalysisRecord(
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
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
        self._records[record.analysis_id] = record
        self._outbox.add(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_REQUESTED,
                analysis_id=record.analysis_id,
                agent_id=record.agent_id,
                payload={
                    "repository_url": record.repository_url,
                    "requested_ref": record.requested_ref,
                },
            )
        )
        return record

    def search_repositories(
        self,
        *,
        query: str,
        limit: int = 8,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[RepositorySearchRecord]:
        entries: dict[str, RepositoryIndexEntry] = {}
        for record in self._records.values():
            if not _record_matches_scope(record, tenant_id, created_by_user_id):
                continue
            canonical = canonicalize_repository_url(record.repository_url)
            key = canonical.repository_url
            entry = entries.get(key)
            if entry is None:
                entries[key] = RepositoryIndexEntry(
                    canonical=canonical,
                    latest_analysis=record,
                    analysis_count=1,
                    completed_analysis_count=1 if record.status == "completed" else 0,
                )
                continue
            entry.analysis_count += 1
            if record.status == "completed":
                entry.completed_analysis_count += 1
            if (record.updated_at, record.analysis_id) > (
                entry.latest_analysis.updated_at,
                entry.latest_analysis.analysis_id,
            ):
                entry.latest_analysis = record

        scored_records = [
            (score, search_record)
            for search_record in (repository_record_from_entry(entry) for entry in entries.values())
            if (score := repository_search_score(search_record, query)) > 0
        ]
        scored_records.sort(key=lambda item: (item[0], item[1].last_analyzed_at), reverse=True)
        return [record for _, record in scored_records[:limit]]

    def list(
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
        del repository_url_hash, created_after, created_before
        records: Iterable[AnalysisRecord] = self._records.values()
        if status is not None:
            records = (record for record in records if record.status == status)
        if tenant_id is not None:
            records = (record for record in records if record.tenant_id == tenant_id)
        if created_by_user_id is not None:
            records = (record for record in records if record.created_by_user_id == created_by_user_id)
        sorted_records = sorted(records, key=lambda record: (record.created_at, record.analysis_id), reverse=True)
        cursor_values = decode_list_cursor(cursor)
        if cursor_values is not None:
            cursor_created_at, cursor_id = cursor_values
            sorted_records = [
                record
                for record in sorted_records
                if (record.created_at, record.analysis_id) < (cursor_created_at, cursor_id)
            ]
            return sorted_records[:limit]
        offset = cursor_offset(cursor)
        return sorted_records[offset : offset + limit]

    def suggest(
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
        records = [
            record
            for record in self._records.values()
            if _record_matches_repository_query(record, parsed_query.repository_url, parsed_query.repository_url_prefix)
            and _record_matches_scope(record, tenant_id, created_by_user_id)
        ]
        records.sort(key=lambda record: (record.updated_at, record.created_at, record.analysis_id), reverse=True)
        return records[:limit]

    def get(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord | None:
        record = self._records.get(analysis_id)
        if record is None or not _record_matches_scope(record, tenant_id, created_by_user_id):
            return None
        return record

    def cancel(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord | None:
        record = self.get(analysis_id, tenant_id=tenant_id, created_by_user_id=created_by_user_id)
        if record is None:
            return None
        if record.status not in {"completed", "failed", "cancelled"}:
            record.status = "cancelling"
        record.updated_at = datetime.now(UTC)
        self._outbox.add(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_CANCEL_REQUESTED,
                analysis_id=record.analysis_id,
                agent_id=record.agent_id,
                payload={},
            )
        )
        return record

    def stream_events(
        self,
        analysis_id: UUID,
        *,
        after_seq: int = 0,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[AgentStreamEventRecord]:
        record = self.get(analysis_id, tenant_id=tenant_id, created_by_user_id=created_by_user_id)
        if record is None:
            return []
        return [
            AgentStreamEventRecord(
                seq=1,
                event_type="status",
                payload_json={"status": record.status},
            )
        ][after_seq:]

    def analysis_status(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> str | None:
        record = self.get(analysis_id, tenant_id=tenant_id, created_by_user_id=created_by_user_id)
        return record.status if record is not None else None


def _record_matches_scope(
    record: AnalysisRecord,
    tenant_id: UUID | None,
    created_by_user_id: UUID | None,
) -> bool:
    return (tenant_id is None or record.tenant_id == tenant_id) and (
        created_by_user_id is None or record.created_by_user_id == created_by_user_id
    )


def _record_matches_repository_query(
    record: AnalysisRecord, repository_url: str | None, repository_url_prefix: str | None
) -> bool:
    if repository_url is not None:
        return record.repository_url == repository_url
    return repository_url_prefix is not None and record.repository_url.startswith(repository_url_prefix)
