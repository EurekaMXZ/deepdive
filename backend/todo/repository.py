from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.db.connections import AsyncDbConnection, ConnectionSource, connection_from
from backend.ids import new_uuid7


class PostgresTodoRepository:
    def __init__(self, connection_or_database: ConnectionSource) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def add_todo_list(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        turn_id: UUID | None,
        tool_call_id: UUID,
        items: list[dict[str, str]],
        note: str | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            await connection.scalar(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:agent_id, 0))"),
                {"agent_id": str(agent_id)},
            )
            replay = await connection.execute(
                text(
                    """
                    SELECT version, items_json, note
                    FROM agent_todo_lists
                    WHERE tool_call_id = :tool_call_id
                    """
                ),
                {"tool_call_id": tool_call_id},
            )
            replay_row = replay.mappings().first()
            if replay_row is not None:
                return _todo_result(dict(replay_row))
            version = await connection.scalar(
                text(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM agent_todo_lists
                    WHERE agent_id = :agent_id
                    """
                ),
                {"agent_id": agent_id},
            )
            result = {"version": int(version or 1), "items": [dict(item) for item in items], "note": note}
            await connection.execute(
                text(
                    """
                    INSERT INTO agent_todo_lists (
                        id, analysis_id, agent_id, turn_id, tool_call_id,
                        version, items_json, note, created_at
                    )
                    VALUES (
                        :id, :analysis_id, :agent_id, :turn_id, :tool_call_id,
                        :version, :items_json, :note, :created_at
                    )
                    """
                ).bindparams(bindparam("items_json", type_=JSONB)),
                {
                    "id": new_uuid7(),
                    "analysis_id": analysis_id,
                    "agent_id": agent_id,
                    "turn_id": turn_id,
                    "tool_call_id": tool_call_id,
                    "version": result["version"],
                    "items_json": result["items"],
                    "note": note,
                    "created_at": now,
                },
            )
            await _add_stream_event_on_connection(
                connection,
                analysis_id=analysis_id,
                agent_id=agent_id,
                turn_id=turn_id,
                event_type="todo_update",
                payload=result,
                state="completed",
            )
        return result

    async def latest_todo_list(self, *, agent_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT version, items_json, note
                    FROM agent_todo_lists
                    WHERE agent_id = :agent_id
                    ORDER BY version DESC
                    LIMIT 1
                    """
                ),
                {"agent_id": agent_id},
            )
        row = result.mappings().first()
        return _todo_result(dict(row)) if row is not None else None


def _todo_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": int(row["version"]),
        "items": [dict(item) for item in row["items_json"]],
        "note": row.get("note"),
    }


async def _add_stream_event_on_connection(
    connection: AsyncDbConnection,
    *,
    analysis_id: UUID,
    agent_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    turn_id: UUID | None = None,
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
            "attempt": None,
            "response_id": None,
            "state": state,
            "created_at": datetime.now(UTC),
        },
    )
