from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.agent import AgentSessionState
from backend.agent.repository_context import AgentContextStore
from backend.agent.repository_stream import AgentStreamStore, add_stream_event_on_connection
from backend.db.connections import connection_from
from backend.events import EventEnvelope
from backend.events.repositories import DbOutboxSink
from backend.ids import new_uuid7


class PostgresAgentRepository:
    def __init__(self, connection_or_database) -> None:
        self._connection_or_database = connection_or_database
        self._context_store = AgentContextStore(connection_or_database)
        self._stream_store = AgentStreamStore(connection_or_database)

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def get_session(self, agent_id: UUID) -> AgentSessionState | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT
                        a.id AS analysis_id,
                        s.id AS agent_id,
                        s.snapshot_id AS snapshot_id,
                        s.config_snapshot_id AS config_snapshot_id,
                        s.status AS status,
                        s.effective_model AS effective_model,
                        s.latest_response_id AS latest_response_id,
                        s.turn_count AS turn_count,
                        s.max_turns AS max_turns,
                        s.effective_limits_json AS effective_limits_json,
                        s.effective_runtime_json AS effective_runtime_json
                    FROM agent_sessions s
                    JOIN analyses a ON a.id = s.analysis_id
                    WHERE s.id = :agent_id
                    """
                ),
                {"agent_id": agent_id},
            )
        row = result.mappings().first()
        if row is None:
            return None
        return AgentSessionState(
            analysis_id=row["analysis_id"],
            agent_id=row["agent_id"],
            snapshot_id=row["snapshot_id"],
            config_snapshot_id=row["config_snapshot_id"],
            status=row["status"],
            effective_model=row["effective_model"],
            latest_response_id=row["latest_response_id"],
            turn_count=row["turn_count"],
            max_turns=row["max_turns"],
            effective_limits_json=row["effective_limits_json"],
            effective_runtime_json=row["effective_runtime_json"],
        )

    async def start_turn(
        self,
        *,
        session: AgentSessionState,
        trigger_event_id: UUID | None = None,
        trigger_domain_key: str | None = None,
    ) -> UUID:
        turn_id = new_uuid7()
        now = datetime.now(UTC)
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO agent_turns (
                        id, agent_id, turn_index, trigger_event_id, trigger_domain_key,
                        status, previous_response_id, created_at
                    )
                    VALUES (
                        :id, :agent_id, :turn_index, :trigger_event_id, :trigger_domain_key,
                        :status, :previous_response_id, :created_at
                    )
                    """
                ),
                {
                    "id": turn_id,
                    "agent_id": session.agent_id,
                    "turn_index": session.turn_count + 1,
                    "trigger_event_id": trigger_event_id,
                    "trigger_domain_key": trigger_domain_key,
                    "status": "calling_model",
                    "previous_response_id": session.latest_response_id,
                    "created_at": now,
                },
            )
        return turn_id

    async def has_turn_for_event(self, *, agent_id: UUID, event_id: UUID) -> bool:
        async with self._connection() as connection:
            value = await connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM agent_turns
                        WHERE agent_id = :agent_id
                          AND trigger_event_id = :event_id
                    )
                    """
                ),
                {"agent_id": agent_id, "event_id": event_id},
            )
        return bool(value)

    async def get_turn_for_event(self, *, agent_id: UUID, event_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, status
                    FROM agent_turns
                    WHERE agent_id = :agent_id
                      AND trigger_event_id = :event_id
                    """
                ),
                {"agent_id": agent_id, "event_id": event_id},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def get_turn_for_domain_key(self, *, agent_id: UUID, trigger_domain_key: str) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, status
                    FROM agent_turns
                    WHERE agent_id = :agent_id
                      AND trigger_domain_key = :trigger_domain_key
                    """
                ),
                {"agent_id": agent_id, "trigger_domain_key": trigger_domain_key},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def get_pending_tool_call_for_turn(self, *, turn_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, snapshot_id, openai_call_id, tool_name, arguments_json, status
                    FROM tool_calls
                    WHERE turn_id = :turn_id
                      AND status IN ('queued', 'running')
                    ORDER BY created_at
                    LIMIT 1
                    """
                ),
                {"turn_id": turn_id},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def load_context_items(self, *, session: AgentSessionState) -> list[dict[str, Any]]:
        return await self._context_store.load_context_items(session=session)

    async def load_instruction_files(self, *, session: AgentSessionState) -> list[dict[str, Any]]:
        return await self._context_store.load_instruction_files(session=session)

    async def load_config_snapshot(self, *, session: AgentSessionState) -> dict[str, Any] | None:
        return await self._context_store.load_config_snapshot(session=session)

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
        await self._stream_store.add_stream_event(
            analysis_id=analysis_id,
            agent_id=agent_id,
            event_type=event_type,
            payload=payload,
            turn_id=turn_id,
            attempt=attempt,
            response_id=response_id,
            state=state,
        )

    async def _add_stream_event_on_connection(
        self,
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

    async def update_session_status(self, *, agent_id: UUID, status: str) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE agent_sessions
                    SET status = :status, updated_at = :updated_at
                    WHERE id = :agent_id
                      AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                    """
                ),
                {"agent_id": agent_id, "status": status, "updated_at": datetime.now(UTC)},
            )

    async def save_context_assembly(self, **kwargs) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO context_assemblies (
                        id, agent_id, turn_id, config_snapshot_id, source_refs_json,
                        input_ref, instructions_hash, tool_schema_hash, token_estimate, created_at
                    )
                    VALUES (
                        :id, :agent_id, :turn_id, :config_snapshot_id, :source_refs_json,
                        :input_ref, :instructions_hash, :tool_schema_hash, :token_estimate, :created_at
                    )
                    """
                ).bindparams(bindparam("source_refs_json", type_=JSONB)),
                {
                    "id": new_uuid7(),
                    "created_at": datetime.now(UTC),
                    **kwargs,
                },
            )

    async def complete_turn(self, **kwargs) -> None:
        async with self._connection() as connection:
            await self._complete_turn_on_connection(connection, **kwargs)

    async def _complete_turn_on_connection(self, connection, **kwargs) -> None:
        usage = kwargs.get("usage") or {}
        await connection.execute(
            text(
                """
                UPDATE agent_turns
                SET status = :status,
                    response_id = :response_id,
                    previous_response_id = :previous_response_id,
                    input_ref = :input_ref,
                    output_ref = :output_ref,
                    input_token_count = :input_token_count,
                    output_token_count = :output_token_count,
                    total_token_count = :total_token_count,
                    completed_at = :completed_at
                WHERE id = :turn_id
                """
            ),
            {
                "turn_id": kwargs["turn_id"],
                "status": "completed",
                "response_id": kwargs.get("response_id"),
                "previous_response_id": kwargs.get("previous_response_id"),
                "input_ref": kwargs.get("input_ref"),
                "output_ref": kwargs.get("output_ref"),
                "input_token_count": usage.get("input_tokens"),
                "output_token_count": usage.get("output_tokens"),
                "total_token_count": usage.get("total_tokens"),
                "completed_at": datetime.now(UTC),
            },
        )

    async def fail_turn(self, *, turn_id: UUID, error_code: str, error_message: str) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE agent_turns
                    SET status = 'failed',
                        completed_at = :completed_at
                    WHERE id = :turn_id
                    """
                ),
                {
                    "turn_id": turn_id,
                    "completed_at": datetime.now(UTC),
                },
            )
        del error_code, error_message

    async def update_latest_response(self, *, agent_id: UUID, response_id: str) -> None:
        async with self._connection() as connection:
            await self._update_latest_response_on_connection(connection, agent_id=agent_id, response_id=response_id)

    async def _update_latest_response_on_connection(self, connection, *, agent_id: UUID, response_id: str) -> None:
        await connection.execute(
            text(
                """
                UPDATE agent_sessions
                SET latest_response_id = :response_id,
                    turn_count = turn_count + 1,
                    updated_at = :updated_at
                WHERE id = :agent_id
                """
            ),
            {"agent_id": agent_id, "response_id": response_id, "updated_at": datetime.now(UTC)},
        )

    async def create_tool_call(self, **kwargs) -> UUID:
        async with self._connection() as connection:
            return await self._create_tool_call_on_connection(connection, **kwargs)

    async def request_tool_call(
        self,
        *,
        tool_call_kwargs: dict[str, Any],
        analysis_id: UUID,
        agent_id: UUID,
        stream_event_type: str,
        stream_payload: dict[str, Any],
        event: EventEnvelope,
    ) -> UUID:
        async with self._connection() as connection:
            can_create = await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)
            if not can_create:
                raise RuntimeError("Cannot request tool call for terminal or cancelling analysis")
            tool_call_id = await self._create_tool_call_on_connection(connection, **tool_call_kwargs)
            payload = dict(stream_payload)
            payload["tool_call_id"] = str(tool_call_id)
            await self._add_stream_event_on_connection(
                connection,
                analysis_id=analysis_id,
                agent_id=agent_id,
                event_type=stream_event_type,
                payload=payload,
                turn_id=tool_call_kwargs.get("turn_id"),
                state="completed",
            )
            event.payload["tool_call_id"] = str(tool_call_id)
            await DbOutboxSink(connection).add(event)
        return tool_call_id

    async def complete_turn_with_tool_call(
        self,
        *,
        turn_id: UUID,
        response_id: str,
        previous_response_id: str | None,
        input_ref: str,
        output_ref: str,
        usage: dict[str, int],
        latest_response_agent_id: UUID,
        tool_call_kwargs: dict[str, Any],
        analysis_id: UUID,
        agent_id: UUID,
        stream_event_type: str,
        stream_payload: dict[str, Any],
        event: EventEnvelope,
    ) -> UUID:
        async with self._connection() as connection:
            can_create = await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)
            if not can_create:
                raise RuntimeError("Cannot request tool call for terminal or cancelling analysis")
            await self._update_latest_response_on_connection(connection, agent_id=latest_response_agent_id, response_id=response_id)
            await self._complete_turn_on_connection(
                connection,
                turn_id=turn_id,
                response_id=response_id,
                previous_response_id=previous_response_id,
                input_ref=input_ref,
                output_ref=output_ref,
                usage=usage,
            )
            tool_call_id = await self._create_tool_call_on_connection(connection, **tool_call_kwargs)
            payload = dict(stream_payload)
            payload["tool_call_id"] = str(tool_call_id)
            await self._add_stream_event_on_connection(
                connection,
                analysis_id=analysis_id,
                agent_id=agent_id,
                event_type=stream_event_type,
                payload=payload,
                turn_id=turn_id,
                response_id=response_id,
                state="completed",
            )
            event.payload["tool_call_id"] = str(tool_call_id)
            await DbOutboxSink(connection).add(event)
        return tool_call_id

    async def complete_turn_with_final_answer(
        self,
        *,
        turn_id: UUID,
        response_id: str,
        previous_response_id: str | None,
        input_ref: str,
        output_ref: str,
        usage: dict[str, int],
        latest_response_agent_id: UUID,
        analysis_id: UUID,
        agent_id: UUID,
        output_text: str,
        stream_payload: dict[str, Any],
        event: EventEnvelope,
        final_delta_payload: dict[str, Any] | None = None,
        final_output_payload: dict[str, Any] | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            can_complete = await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)
            if not can_complete:
                return False
            await self._update_latest_response_on_connection(connection, agent_id=latest_response_agent_id, response_id=response_id)
            await self._complete_turn_on_connection(
                connection,
                turn_id=turn_id,
                response_id=response_id,
                previous_response_id=previous_response_id,
                input_ref=input_ref,
                output_ref=output_ref,
                usage=usage,
            )
            result = await connection.execute(
                text(
                    """
                    UPDATE analyses
                    SET status = 'completed', updated_at = :now, completed_at = :now
                    WHERE id = :analysis_id
                      AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                    """
                ),
                {"analysis_id": analysis_id, "now": now},
            )
            await connection.execute(
                text(
                    """
                    UPDATE agent_sessions
                    SET status = 'completed', updated_at = :now
                    WHERE id = :agent_id
                      AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                    """
                ),
                {"agent_id": agent_id, "now": now},
            )
            if int(getattr(result, "rowcount", 0) or 0) <= 0:
                return False
            if final_delta_payload is not None:
                await self._add_stream_event_on_connection(
                    connection,
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    event_type="delta",
                    payload=final_delta_payload,
                    turn_id=turn_id,
                    response_id=response_id,
                    state="streaming",
                )
            await self._add_stream_event_on_connection(
                connection,
                analysis_id=analysis_id,
                agent_id=agent_id,
                event_type="done",
                payload=stream_payload,
                turn_id=turn_id,
                response_id=response_id,
                state="completed",
            )
            await DbOutboxSink(connection).add(event)
        del output_text, final_output_payload
        return True

    async def _can_continue(self, connection, *, analysis_id: UUID, agent_id: UUID) -> bool:
        return await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)

    async def _lock_continuable_session(self, connection, *, analysis_id: UUID, agent_id: UUID) -> bool:
        result = await connection.execute(
            text(
                """
                SELECT a.id
                FROM analyses a
                JOIN agent_sessions s ON s.analysis_id = a.id
                WHERE a.id = :analysis_id
                  AND s.id = :agent_id
                  AND a.status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                  AND s.status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                FOR UPDATE OF a, s
                """
            ),
            {"analysis_id": analysis_id, "agent_id": agent_id},
        )
        return result.mappings().first() is not None

    async def _create_tool_call_on_connection(self, connection, **kwargs) -> UUID:
        tool_call_id = new_uuid7()
        result = await connection.execute(
            text(
                """
                INSERT INTO tool_calls (
                    id, agent_id, turn_id, snapshot_id, openai_call_id, tool_name,
                    arguments_json, tool_registry_version, tool_schema_hash,
                    tool_policy_hash, status, result_ref, result_summary, completed_at, created_at
                )
                VALUES (
                    :id, :agent_id, :turn_id, :snapshot_id, :openai_call_id, :tool_name,
                    :arguments_json, :tool_registry_version, :tool_schema_hash,
                    :tool_policy_hash, :status, :result_ref, :result_summary, :completed_at, :created_at
                )
                ON CONFLICT (agent_id, openai_call_id)
                DO UPDATE SET id = tool_calls.id
                RETURNING id
                """
            ).bindparams(bindparam("arguments_json", type_=JSONB)),
            {
                "id": tool_call_id,
                "result_ref": kwargs.pop("result_ref", None),
                "result_summary": _json_or_none(kwargs.pop("result_summary", None)),
                "completed_at": datetime.now(UTC) if kwargs.get("status") == "completed" else None,
                "created_at": datetime.now(UTC),
                **kwargs,
            },
        )
        row = result.mappings().first()
        return row["id"] if row is not None else tool_call_id

    async def find_completed_tool_call(self, *, agent_id: UUID, tool_name: str, arguments_json: dict[str, Any]) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, openai_call_id, tool_name, arguments_json, result_ref, result_summary
                    FROM tool_calls
                    WHERE agent_id = :agent_id
                      AND tool_name = :tool_name
                      AND arguments_json = :arguments_json
                      AND status = 'completed'
                    ORDER BY completed_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
                    """
                ).bindparams(bindparam("arguments_json", type_=JSONB)),
                {"agent_id": agent_id, "tool_name": tool_name, "arguments_json": arguments_json},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def count_tool_calls(self, *, agent_id: UUID) -> int:
        async with self._connection() as connection:
            value = await connection.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM tool_calls
                    WHERE agent_id = :agent_id
                    """
                ),
                {"agent_id": agent_id},
            )
        return int(value or 0)

    async def get_pending_tool_output(self, *, tool_call_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT tc.openai_call_id, tc.tool_name, tc.arguments_json, tc.result_summary, at.output_ref
                    FROM tool_calls tc
                    JOIN agent_turns at ON at.id = tc.turn_id
                    WHERE tc.id = :tool_call_id
                      AND tc.status IN ('completed', 'failed', 'denied')
                    """
                ),
                {"tool_call_id": tool_call_id},
            )
        row = result.mappings().first()
        if row is None:
            return None
        return {
            "call_id": row["openai_call_id"],
            "name": row["tool_name"],
            "arguments": row["arguments_json"],
            "output": row["result_summary"] or "{}",
            "output_ref": row["output_ref"],
        }

    async def complete_analysis(self, *, analysis_id: UUID, agent_id: UUID, output_text: str) -> bool:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE analyses
                    SET status = 'completed', updated_at = :now, completed_at = :now
                    WHERE id = :analysis_id
                      AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                    """
                ),
                {"analysis_id": analysis_id, "now": now},
            )
            await connection.execute(
                text(
                    """
                    UPDATE agent_sessions
                    SET status = 'completed', updated_at = :now
                    WHERE id = :agent_id
                      AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                    """
                ),
                {"agent_id": agent_id, "now": now},
            )
        del output_text
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def fail_analysis(self, *, analysis_id: UUID, agent_id: UUID, error_code: str, error_message: str) -> bool:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE analyses
                    SET status = 'failed', updated_at = :now, completed_at = :now,
                        error_code = :error_code, error_message = :error_message
                    WHERE id = :analysis_id
                      AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                    """
                ),
                {"analysis_id": analysis_id, "now": now, "error_code": error_code, "error_message": error_message[:4096]},
            )
            await connection.execute(
                text(
                    """
                    UPDATE agent_sessions
                    SET status = 'failed', updated_at = :now
                    WHERE id = :agent_id
                      AND status NOT IN ('completed', 'failed', 'cancelled', 'cancelling')
                    """
                ),
                {"agent_id": agent_id, "now": now},
            )
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def add_memory_summary(self, **kwargs) -> None:
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO memory_summaries (
                        id, agent_id, compacted_until_turn, summary_json, evidence_ids_json,
                        focus_paths_json, next_action, created_at
                    )
                    VALUES (
                        :id, :agent_id, :compacted_until_turn, :summary_json, :evidence_ids_json,
                        :focus_paths_json, :next_action, :created_at
                    )
                    """
                ).bindparams(
                    bindparam("summary_json", type_=JSONB),
                    bindparam("evidence_ids_json", type_=JSONB),
                    bindparam("focus_paths_json", type_=JSONB),
                ),
                {"id": new_uuid7(), "created_at": datetime.now(UTC), **kwargs},
            )

    async def add_outbox(self, event: EventEnvelope) -> None:
        async with self._connection() as connection:
            await DbOutboxSink(connection).add(event)

def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
