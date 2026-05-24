from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from backend.api.pagination import cursor_offset, decode_list_cursor
from backend.api.records import AgentStreamEventRecord, AnalysisRecord
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

    def list(
        self,
        *,
        status: str | None = None,
        repository_url_hash: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[AnalysisRecord]:
        del repository_url_hash, created_after, created_before
        records: Iterable[AnalysisRecord] = self._records.values()
        if status is not None:
            records = (record for record in records if record.status == status)
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

    def get(self, analysis_id: UUID) -> AnalysisRecord | None:
        return self._records.get(analysis_id)

    def cancel(self, analysis_id: UUID) -> AnalysisRecord | None:
        record = self._records.get(analysis_id)
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

    def stream_events(self, analysis_id: UUID, *, after_seq: int = 0) -> list[AgentStreamEventRecord]:
        record = self._records.get(analysis_id)
        if record is None:
            return []
        return [
            AgentStreamEventRecord(
                seq=1,
                event_type="status",
                payload_json={"status": record.status},
            )
        ][after_seq:]

    def analysis_status(self, analysis_id: UUID) -> str | None:
        record = self._records.get(analysis_id)
        return record.status if record is not None else None
