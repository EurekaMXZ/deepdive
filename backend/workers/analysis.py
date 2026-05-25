from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.db.connections import AsyncDbConnection
from backend.events import EventEnvelope, EventType
from backend.events.repositories import DbOutboxSink
from backend.ids import new_uuid7


class AnalysisCommandHandler:
    def __init__(self, connection: AsyncDbConnection) -> None:
        self._connection = connection

    async def __call__(self, event: EventEnvelope) -> None:
        if event.event_type == EventType.ANALYSIS_REQUESTED:
            await self._handle_analysis_requested(event)
            return
        if event.event_type == EventType.ANALYSIS_CANCEL_REQUESTED:
            await self._handle_analysis_cancel_requested(event)
            return
        raise ValueError(f"Unsupported analysis command event: {event.event_type}")

    async def _handle_analysis_requested(self, event: EventEnvelope) -> None:
        if event.analysis_id is None or event.agent_id is None:
            raise ValueError("AnalysisRequested requires analysis_id and agent_id")

        now = datetime.now(UTC)
        result = await self._connection.execute(
            text(
                """
                UPDATE analyses
                SET status = :status, updated_at = :updated_at
                WHERE id = :analysis_id
                  AND status = 'queued'
                RETURNING id
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "status": "snapshotting",
                "updated_at": now,
            },
        )
        if result.mappings().first() is None:
            return

        await self._connection.execute(
            text(
                """
                UPDATE analysis_batch_items
                SET status = 'snapshotting',
                    updated_at = :updated_at
                WHERE analysis_id = :analysis_id
                  AND status = 'dispatched'
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "updated_at": now,
            },
        )
        await self._connection.execute(
            text(
                """
                UPDATE agent_sessions
                SET status = :status, updated_at = :updated_at
                WHERE id = :agent_id
                  AND analysis_id = :analysis_id
                  AND status = 'queued'
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "agent_id": event.agent_id,
                "status": "queued",
                "updated_at": now,
            },
        )
        await DbOutboxSink(self._connection).add(
            EventEnvelope.new(
                event_type=EventType.SNAPSHOT_REQUESTED,
                analysis_id=event.analysis_id,
                agent_id=event.agent_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "repository_url": event.payload["repository_url"],
                    "requested_ref": event.payload["requested_ref"],
                    "config_snapshot_id": event.payload.get("config_snapshot_id"),
                },
            )
        )

    async def _handle_analysis_cancel_requested(self, event: EventEnvelope) -> None:
        if event.analysis_id is None:
            raise ValueError("AnalysisCancelRequested requires analysis_id")

        now = datetime.now(UTC)
        result = await self._connection.execute(
            text(
                """
                UPDATE analyses
                SET status = :status, updated_at = :updated_at, completed_at = :completed_at
                WHERE id = :analysis_id
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                RETURNING id
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "status": "cancelled",
                "updated_at": now,
                "completed_at": now,
            },
        )
        if result.mappings().first() is None:
            return

        await self._connection.execute(
            text(
                """
                UPDATE agent_sessions
                SET status = :status, updated_at = :updated_at
                WHERE analysis_id = :analysis_id
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                """
            ),
            {
                "analysis_id": event.analysis_id,
                "status": "cancelled",
                "updated_at": now,
            },
        )
        await self._connection.execute(
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
            {
                "agent_id": event.agent_id,
                "completed_at": now,
            },
        )
        if event.agent_id is not None:
            await self._add_cancelled_stream_events(analysis_id=event.analysis_id, agent_id=event.agent_id, now=now)
        await DbOutboxSink(self._connection).add(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_CANCELLED,
                analysis_id=event.analysis_id,
                agent_id=event.agent_id,
                snapshot_id=event.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={},
            )
        )

    async def _add_cancelled_stream_events(self, *, analysis_id: UUID, agent_id: UUID, now: datetime) -> None:
        await self._connection.scalar(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:analysis_id, 0))"),
            {"analysis_id": str(analysis_id)},
        )
        next_seq = await self._connection.scalar(
            text(
                """
                SELECT COALESCE(MAX(seq), 0) + 1
                FROM agent_stream_events
                WHERE analysis_id = :analysis_id
                """
            ),
            {"analysis_id": analysis_id},
        )
        for offset, event_type in enumerate(("status", "done")):
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
                    "seq": int(next_seq or 1) + offset,
                    "event_type": event_type,
                    "payload_json": {"status": "cancelled"},
                    "created_at": now,
                },
            )
