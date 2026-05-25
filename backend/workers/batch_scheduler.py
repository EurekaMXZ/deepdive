from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.db.connections import AsyncDbConnection, DbRow
from backend.events import EventEnvelope, EventType
from backend.events.repositories import DbOutboxSink

TERMINAL_EVENT_STATUSES: dict[EventType, str] = {
    EventType.ANALYSIS_COMPLETED: "completed",
    EventType.ANALYSIS_FAILED: "failed",
    EventType.ANALYSIS_CANCELLED: "cancelled",
}


class AnalysisBatchSchedulerHandler:
    def __init__(self, connection: AsyncDbConnection) -> None:
        self._connection = connection

    async def __call__(self, event: EventEnvelope) -> None:
        if event.event_type in {EventType.ANALYSIS_BATCH_SUBMITTED, EventType.ANALYSIS_BATCH_SLOT_AVAILABLE}:
            await self._schedule_batch(_batch_id_from_payload(event))
            return
        if event.event_type in TERMINAL_EVENT_STATUSES:
            await self._handle_terminal_analysis_event(event)
            return
        raise ValueError(f"Unsupported analysis batch scheduler event: {event.event_type}")

    async def _handle_terminal_analysis_event(self, event: EventEnvelope) -> None:
        if event.analysis_id is None:
            raise ValueError(f"{event.event_type.value} requires analysis_id")
        terminal_status = TERMINAL_EVENT_STATUSES[event.event_type]
        now = datetime.now(UTC)
        result = await self._connection.execute(
            text(
                """
                UPDATE analysis_batch_items
                SET status = :terminal_status,
                    completed_at = :completed_at,
                    updated_at = :updated_at,
                    error_code = COALESCE(:error_code, error_code),
                    error_message = COALESCE(:error_message, error_message)
                WHERE analysis_id = :analysis_id
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                RETURNING batch_id, status AS previous_status
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "terminal_status": terminal_status,
                "completed_at": now,
                "updated_at": now,
                "error_code": _optional_str(event.payload.get("error_code")),
                "error_message": _optional_str(event.payload.get("error_message")),
            },
        )
        row = result.mappings().first()
        if row is None:
            return
        await self._refresh_batch_counts(batch_id=_uuid_from_row(row, "batch_id"), now=now)
        await self._schedule_batch(_uuid_from_row(row, "batch_id"), causation_id=event.event_id)

    async def _schedule_batch(self, batch_id: UUID, *, causation_id: UUID | None = None) -> None:
        batch = await self._lock_batch(batch_id)
        if batch is None:
            return
        max_parallel = int(batch["max_parallel"])
        active_count = int(batch["active_count"])
        pending_count = int(batch["pending_count"])
        if pending_count <= 0:
            await self._finish_batch_if_terminal(batch_id=batch_id)
            return
        available_slots = max_parallel - active_count
        if available_slots <= 0:
            return

        claimed_items = await self._claim_pending_items(batch_id=batch_id, limit=available_slots)
        if not claimed_items:
            return

        now = datetime.now(UTC)
        await self._refresh_batch_counts(batch_id=batch_id, now=now)
        outbox = DbOutboxSink(self._connection)
        for item in claimed_items:
            analysis_id = _uuid_from_row(item, "analysis_id")
            agent_id = _uuid_from_row(item, "agent_id")
            await outbox.add(
                EventEnvelope.new(
                    event_type=EventType.ANALYSIS_REQUESTED,
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    correlation_id=batch_id,
                    causation_id=causation_id,
                    payload={
                        "batch_id": str(batch_id),
                        "batch_item_id": str(_uuid_from_row(item, "batch_item_id")),
                        "repository_url": str(item["repository_url"]),
                        "requested_ref": str(item["requested_ref"]),
                        "analysis_profile_id": _optional_str(item.get("analysis_profile_id")),
                        "config_snapshot_id": _optional_str(item.get("config_snapshot_id")),
                    },
                )
            )

    async def _lock_batch(self, batch_id: UUID) -> DbRow | None:
        result = await self._connection.execute(
            text(
                """
                SELECT id, max_parallel, active_count, pending_count
                FROM analysis_batches
                WHERE id = :batch_id
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                FOR UPDATE
                """
            ),
            {"batch_id": batch_id},
        )
        return result.mappings().first()

    async def _claim_pending_items(self, *, batch_id: UUID, limit: int) -> list[DbRow]:
        result = await self._connection.execute(
            text(
                """
                WITH claimable AS (
                    SELECT id
                    FROM analysis_batch_items
                    WHERE batch_id = :batch_id
                      AND status = 'pending'
                    ORDER BY sort_order
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE analysis_batch_items item
                SET status = 'dispatched',
                    dispatch_owner = :dispatch_owner,
                    dispatched_at = :dispatched_at,
                    updated_at = :updated_at
                FROM claimable
                WHERE item.id = claimable.id
                RETURNING
                    item.id AS batch_item_id,
                    item.analysis_id AS analysis_id,
                    item.agent_id AS agent_id,
                    item.repository_url AS repository_url,
                    item.requested_ref AS requested_ref,
                    item.analysis_profile_id AS analysis_profile_id,
                    item.config_snapshot_id AS config_snapshot_id
                """
            ),
            {
                "batch_id": batch_id,
                "limit": limit,
                "dispatch_owner": "analysis-batch-scheduler",
                "dispatched_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        )
        return list(result.mappings().all())

    async def _refresh_batch_counts(self, *, batch_id: UUID, now: datetime) -> None:
        await self._connection.execute(
            text(
                """
                WITH counts AS (
                    SELECT
                        count(*) FILTER (WHERE status = 'pending') AS pending_count,
                        count(*) FILTER (WHERE status IN ('dispatched', 'snapshotting', 'running')) AS active_count,
                        count(*) FILTER (WHERE status = 'completed') AS completed_count,
                        count(*) FILTER (WHERE status = 'failed') AS failed_count,
                        count(*) FILTER (WHERE status = 'cancelled') AS cancelled_count
                    FROM analysis_batch_items
                    WHERE batch_id = :batch_id
                )
                UPDATE analysis_batches batch
                SET pending_count = counts.pending_count,
                    active_count = counts.active_count,
                    completed_count = counts.completed_count,
                    failed_count = counts.failed_count,
                    cancelled_count = counts.cancelled_count,
                    status = CASE
                        WHEN counts.pending_count = 0 AND counts.active_count = 0 AND counts.failed_count > 0 THEN 'failed'
                        WHEN counts.pending_count = 0 AND counts.active_count = 0 THEN 'completed'
                        WHEN counts.active_count > 0 THEN 'running'
                        ELSE batch.status
                    END,
                    completed_at = CASE
                        WHEN counts.pending_count = 0 AND counts.active_count = 0 THEN :updated_at
                        ELSE batch.completed_at
                    END,
                    updated_at = :updated_at
                FROM counts
                WHERE batch.id = :batch_id
                """
            ),
            {"batch_id": batch_id, "updated_at": now},
        )

    async def _finish_batch_if_terminal(self, *, batch_id: UUID) -> None:
        await self._refresh_batch_counts(batch_id=batch_id, now=datetime.now(UTC))


def _batch_id_from_payload(event: EventEnvelope) -> UUID:
    value = event.payload.get("batch_id")
    if not isinstance(value, str):
        raise ValueError(f"{event.event_type.value} requires payload.batch_id")
    return UUID(value)


def _uuid_from_row(row: DbRow, key: str) -> UUID:
    value = row[key]
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
