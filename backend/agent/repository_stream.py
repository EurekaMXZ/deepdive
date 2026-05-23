from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.db.connections import connection_from
from backend.ids import new_uuid7


class AgentStreamStore:
    def __init__(self, connection_or_database) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def add_stream_event(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        turn_id: UUID | None = None,
        attempt: int | None = None,
        response_id: str | None = None,
        state: str | None = None,
    ) -> None:
        async with self._connection() as connection:
            await add_stream_event_on_connection(
                connection,
                analysis_id=analysis_id,
                agent_id=agent_id,
                event_type=event_type,
                payload=payload,
                turn_id=turn_id,
                attempt=attempt,
                response_id=response_id,
                state=state,
            )


async def add_stream_event_on_connection(
    connection,
    *,
    analysis_id: UUID,
    agent_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    turn_id: UUID | None = None,
    attempt: int | None = None,
    response_id: str | None = None,
    state: str | None = None,
) -> None:
    await connection.scalar(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:analysis_id, 0))"),
        {"analysis_id": str(analysis_id)},
    )
    seq = await connection.scalar(
        text(
            """
            SELECT COALESCE(MAX(seq), 0) + 1
            FROM agent_stream_events
            WHERE analysis_id = :analysis_id
            """
        ),
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
                :id, :analysis_id, :agent_id, :turn_id, :seq, :event_type,
                :payload_json, :attempt, :response_id, :state, :created_at
            )
            """
        ).bindparams(bindparam("payload_json", type_=JSONB)),
        {
            "id": new_uuid7(),
            "analysis_id": analysis_id,
            "agent_id": agent_id,
            "turn_id": turn_id,
            "seq": seq,
            "event_type": event_type,
            "payload_json": payload,
            "attempt": attempt,
            "response_id": response_id,
            "state": state,
            "created_at": datetime.now(UTC),
        },
    )
