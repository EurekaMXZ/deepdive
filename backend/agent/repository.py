from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.agent import AgentSessionState
from backend.agent.context_items import (
    ASSISTANT_OUTPUT_ITEM_TYPE,
    COMPACTION_ITEM_TYPE,
    FUNCTION_CALL_ITEM_TYPE,
    FUNCTION_CALL_OUTPUT_ITEM_TYPE,
    MODEL_CONTEXT_SOURCE,
    TOOL_CONTEXT_SOURCE,
    append_context_item_on_connection,
    assistant_output_idempotency_key,
    assistant_output_payload,
    canonical_model_item_idempotency_key,
    canonical_model_item_type,
    function_call_output_payload,
    function_call_payload,
    model_function_call_idempotency_key,
    remote_compaction_idempotency_key,
    tool_output_idempotency_key,
)
from backend.agent.repository_context import AgentContextStore
from backend.agent.repository_stream import AgentStreamStore, add_stream_event_on_connection
from backend.db.connections import AsyncDbConnection, ConnectionSource, connection_from
from backend.events import EventEnvelope
from backend.events.repositories import DbOutboxSink
from backend.ids import new_uuid7


class PostgresAgentRepository:
    def __init__(self, connection_or_database: ConnectionSource) -> None:
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

    async def load_uncompacted_context_items(self, *, agent_id: UUID, limit: int = 12) -> list[dict[str, Any]]:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT seq, item_type, payload_json, source, response_id
                    FROM (
                        SELECT seq, item_type, payload_json, source, response_id
                        FROM agent_context_items
                        WHERE agent_id = :agent_id
                          AND compacted_at IS NULL
                        ORDER BY seq DESC
                        LIMIT :limit
                    ) AS recent
                    ORDER BY recent.seq
                    """
                ),
                {"agent_id": agent_id, "limit": limit},
            )
        return [dict(row) for row in result.mappings().all()]

    async def load_latest_memory_summary(self, *, agent_id: UUID) -> dict[str, Any] | None:
        return await self._context_store.load_latest_memory_summary(agent_id=agent_id)

    async def load_latest_todo_list(self, *, agent_id: UUID) -> dict[str, Any] | None:
        return await self._context_store.load_latest_todo_list(agent_id=agent_id)

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

    async def append_context_item(
        self,
        *,
        agent_id: UUID,
        turn_id: UUID | None,
        item_type: str,
        payload: dict[str, Any],
        response_id: str | None = None,
        source: str,
        idempotency_key: str | None = None,
    ) -> None:
        async with self._connection() as connection:
            await append_context_item_on_connection(
                connection,
                agent_id=agent_id,
                turn_id=turn_id,
                item_type=item_type,
                payload=payload,
                response_id=response_id,
                source=source,
                idempotency_key=idempotency_key,
            )

    async def _append_context_item_on_connection(
        self,
        connection: AsyncDbConnection,
        *,
        agent_id: UUID,
        turn_id: UUID | None,
        item_type: str,
        payload: dict[str, Any],
        response_id: str | None = None,
        source: str,
        idempotency_key: str | None = None,
    ) -> None:
        await append_context_item_on_connection(
            connection,
            agent_id=agent_id,
            turn_id=turn_id,
            item_type=item_type,
            payload=payload,
            response_id=response_id,
            source=source,
            idempotency_key=idempotency_key,
        )

    async def _append_model_output_items_on_connection(
        self,
        connection: AsyncDbConnection,
        *,
        agent_id: UUID,
        turn_id: UUID | None,
        response_id: str,
        output_items: list[dict[str, Any]],
    ) -> None:
        for item in output_items:
            await self._append_context_item_on_connection(
                connection,
                agent_id=agent_id,
                turn_id=turn_id,
                item_type=canonical_model_item_type(item),
                payload=item,
                response_id=response_id,
                source=MODEL_CONTEXT_SOURCE,
                idempotency_key=canonical_model_item_idempotency_key(item, response_id=response_id),
            )

    async def _add_stream_event_on_connection(
        self,
        connection: AsyncDbConnection,
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

    async def save_context_assembly(self, **kwargs: Any) -> None:
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

    async def complete_turn(self, **kwargs: Any) -> None:
        async with self._connection() as connection:
            await self._complete_turn_on_connection(connection, **kwargs)

    async def _complete_turn_on_connection(self, connection: AsyncDbConnection, **kwargs: Any) -> None:
        raw_usage = kwargs.get("usage")
        usage = cast(dict[str, Any], raw_usage) if isinstance(raw_usage, dict) else {}
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

    async def _update_latest_response_on_connection(
        self, connection: AsyncDbConnection, *, agent_id: UUID, response_id: str
    ) -> None:
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

    async def create_tool_call(self, **kwargs: Any) -> UUID:
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
        output_items: list[dict[str, Any]] | None = None,
        event: EventEnvelope,
    ) -> UUID:
        async with self._connection() as connection:
            can_create = await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)
            if not can_create:
                raise RuntimeError("Cannot request tool call for terminal or cancelling analysis")
            context_tool_call_kwargs = dict(tool_call_kwargs)
            await self._update_latest_response_on_connection(
                connection, agent_id=latest_response_agent_id, response_id=response_id
            )
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
            if output_items:
                await self._append_model_output_items_on_connection(
                    connection,
                    agent_id=agent_id,
                    turn_id=turn_id,
                    response_id=response_id,
                    output_items=output_items,
                )
            else:
                await self._append_context_item_on_connection(
                    connection,
                    agent_id=agent_id,
                    turn_id=turn_id,
                    item_type=FUNCTION_CALL_ITEM_TYPE,
                    payload=function_call_payload(
                        call_id=context_tool_call_kwargs["openai_call_id"],
                        name=context_tool_call_kwargs["tool_name"],
                        arguments=context_tool_call_kwargs["arguments_json"],
                    ),
                    response_id=response_id,
                    source=MODEL_CONTEXT_SOURCE,
                    idempotency_key=model_function_call_idempotency_key(context_tool_call_kwargs["openai_call_id"]),
                )
            if (
                context_tool_call_kwargs.get("status") == "completed"
                and context_tool_call_kwargs.get("result_summary") is not None
            ):
                await self._append_context_item_on_connection(
                    connection,
                    agent_id=agent_id,
                    turn_id=turn_id,
                    item_type=FUNCTION_CALL_OUTPUT_ITEM_TYPE,
                    payload=function_call_output_payload(
                        call_id=context_tool_call_kwargs["openai_call_id"],
                        output=_json_or_none(context_tool_call_kwargs.get("result_summary")) or "{}",
                    ),
                    response_id=None,
                    source=TOOL_CONTEXT_SOURCE,
                    idempotency_key=tool_output_idempotency_key(context_tool_call_kwargs["openai_call_id"]),
                )
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

    async def complete_turn_with_tool_calls(
        self,
        *,
        turn_id: UUID,
        response_id: str,
        previous_response_id: str | None,
        input_ref: str,
        output_ref: str,
        usage: dict[str, int],
        latest_response_agent_id: UUID,
        tool_call_requests: list[dict[str, Any]],
        analysis_id: UUID,
        agent_id: UUID,
        output_items: list[dict[str, Any]] | None = None,
    ) -> list[UUID]:
        async with self._connection() as connection:
            can_create = await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)
            if not can_create:
                raise RuntimeError("Cannot request tool calls for terminal or cancelling analysis")
            await self._update_latest_response_on_connection(
                connection, agent_id=latest_response_agent_id, response_id=response_id
            )
            await self._complete_turn_on_connection(
                connection,
                turn_id=turn_id,
                response_id=response_id,
                previous_response_id=previous_response_id,
                input_ref=input_ref,
                output_ref=output_ref,
                usage=usage,
            )
            tool_call_ids: list[UUID] = []
            for request in tool_call_requests:
                tool_call_kwargs = dict(request["tool_call_kwargs"])
                tool_call_id = await self._create_tool_call_on_connection(connection, **tool_call_kwargs)
                tool_call_ids.append(tool_call_id)
            if output_items:
                await self._append_model_output_items_on_connection(
                    connection,
                    agent_id=agent_id,
                    turn_id=turn_id,
                    response_id=response_id,
                    output_items=output_items,
                )
            else:
                for request in tool_call_requests:
                    tool_call_kwargs = dict(request["tool_call_kwargs"])
                    await self._append_context_item_on_connection(
                        connection,
                        agent_id=agent_id,
                        turn_id=turn_id,
                        item_type=FUNCTION_CALL_ITEM_TYPE,
                        payload=function_call_payload(
                            call_id=tool_call_kwargs["openai_call_id"],
                            name=tool_call_kwargs["tool_name"],
                            arguments=tool_call_kwargs["arguments_json"],
                        ),
                        response_id=response_id,
                        source=MODEL_CONTEXT_SOURCE,
                        idempotency_key=model_function_call_idempotency_key(tool_call_kwargs["openai_call_id"]),
                    )
            for index, request in enumerate(tool_call_requests):
                tool_call_id = tool_call_ids[index]
                tool_call_kwargs = dict(request["tool_call_kwargs"])
                if tool_call_kwargs.get("status") == "completed" and tool_call_kwargs.get("result_summary") is not None:
                    await self._append_context_item_on_connection(
                        connection,
                        agent_id=agent_id,
                        turn_id=turn_id,
                        item_type=FUNCTION_CALL_OUTPUT_ITEM_TYPE,
                        payload=function_call_output_payload(
                            call_id=tool_call_kwargs["openai_call_id"],
                            output=_json_or_none(tool_call_kwargs.get("result_summary")) or "{}",
                        ),
                        response_id=None,
                        source=TOOL_CONTEXT_SOURCE,
                        idempotency_key=tool_output_idempotency_key(tool_call_kwargs["openai_call_id"]),
                    )
                payload = dict(request["stream_payload"])
                payload["tool_call_id"] = str(tool_call_id)
                await self._add_stream_event_on_connection(
                    connection,
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    event_type=request["stream_event_type"],
                    payload=payload,
                    turn_id=turn_id,
                    response_id=response_id,
                    state="completed",
                )
                event = request["event"]
                event.payload["tool_call_id"] = str(tool_call_id)
                await DbOutboxSink(connection).add(event)
        return tool_call_ids

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
        output_items: list[dict[str, Any]] | None = None,
        final_delta_payload: dict[str, Any] | None = None,
        final_output_payload: dict[str, Any] | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            can_complete = await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)
            if not can_complete:
                return False
            await self._update_latest_response_on_connection(
                connection, agent_id=latest_response_agent_id, response_id=response_id
            )
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
            if output_items:
                await self._append_model_output_items_on_connection(
                    connection,
                    agent_id=agent_id,
                    turn_id=turn_id,
                    response_id=response_id,
                    output_items=output_items,
                )
            elif output_text:
                await self._append_context_item_on_connection(
                    connection,
                    agent_id=agent_id,
                    turn_id=turn_id,
                    item_type=ASSISTANT_OUTPUT_ITEM_TYPE,
                    payload=assistant_output_payload(output_text),
                    response_id=response_id,
                    source=MODEL_CONTEXT_SOURCE,
                    idempotency_key=assistant_output_idempotency_key(response_id),
                )
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
        del final_output_payload
        return True

    async def _can_continue(self, connection: AsyncDbConnection, *, analysis_id: UUID, agent_id: UUID) -> bool:
        return await self._lock_continuable_session(connection, analysis_id=analysis_id, agent_id=agent_id)

    async def _lock_continuable_session(
        self, connection: AsyncDbConnection, *, analysis_id: UUID, agent_id: UUID
    ) -> bool:
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

    async def _create_tool_call_on_connection(self, connection: AsyncDbConnection, **kwargs: Any) -> UUID:
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

    async def find_completed_tool_call(
        self, *, agent_id: UUID, tool_name: str, arguments_json: dict[str, Any]
    ) -> dict[str, Any] | None:
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
                    SELECT tc.id, tc.turn_id, tc.openai_call_id, tc.tool_name, tc.arguments_json,
                           tc.result_summary, at.output_ref
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
            "id": row["id"],
            "turn_id": row["turn_id"],
            "call_id": row["openai_call_id"],
            "name": row["tool_name"],
            "arguments": row["arguments_json"],
            "output": row["result_summary"] or "{}",
            "output_ref": row["output_ref"],
        }

    async def load_ready_tool_outputs_for_turn(self, *, turn_id: UUID) -> list[dict[str, Any]] | None:
        async with self._connection() as connection:
            pending_count = await connection.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM tool_calls
                    WHERE turn_id = :turn_id
                      AND status IN ('queued', 'validating', 'running')
                    """
                ),
                {"turn_id": turn_id},
            )
            if int(pending_count or 0) > 0:
                return None
            result = await connection.execute(
                text(
                    """
                    SELECT tc.id, tc.turn_id, tc.openai_call_id, tc.tool_name, tc.arguments_json,
                           tc.result_summary, at.output_ref
                    FROM tool_calls tc
                    JOIN agent_turns at ON at.id = tc.turn_id
                    WHERE tc.turn_id = :turn_id
                      AND tc.status IN ('completed', 'failed', 'denied')
                    ORDER BY tc.created_at, tc.id
                    """
                ),
                {"turn_id": turn_id},
            )
        outputs: list[dict[str, Any]] = []
        for row in result.mappings().all():
            outputs.append(
                {
                    "id": row["id"],
                    "turn_id": row["turn_id"],
                    "call_id": row["openai_call_id"],
                    "name": row["tool_name"],
                    "arguments": row["arguments_json"],
                    "output": row["result_summary"] or "{}",
                    "output_ref": row["output_ref"],
                }
            )
        return outputs

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
                {
                    "analysis_id": analysis_id,
                    "now": now,
                    "error_code": error_code,
                    "error_message": error_message[:4096],
                },
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

    async def add_memory_summary(self, **kwargs: Any) -> None:
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

    async def compact_context_items(
        self,
        *,
        agent_id: UUID,
        compacted_until_seq: int,
        compacted_until_turn: int,
        summary_json: dict[str, Any],
        evidence_ids_json: list[Any],
        focus_paths_json: list[str],
        next_action: str | None,
    ) -> None:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE agent_context_items
                    SET compacted_at = :compacted_at
                    WHERE agent_id = :agent_id
                      AND seq <= :compacted_until_seq
                      AND compacted_at IS NULL
                    """
                ),
                {
                    "agent_id": agent_id,
                    "compacted_until_seq": compacted_until_seq,
                    "compacted_at": now,
                },
            )
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
                {
                    "id": new_uuid7(),
                    "agent_id": agent_id,
                    "compacted_until_turn": compacted_until_turn,
                    "summary_json": summary_json,
                    "evidence_ids_json": evidence_ids_json,
                    "focus_paths_json": focus_paths_json,
                    "next_action": next_action,
                    "created_at": now,
                },
            )

    async def save_compacted_context_window(
        self,
        *,
        agent_id: UUID,
        turn_id: UUID,
        compacted_until_turn: int,
        compaction_id: str,
        output_json: list[dict[str, Any]],
        usage_json: dict[str, int],
        strategy: str = "remote",
    ) -> None:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE agent_context_items
                    SET compacted_at = :compacted_at
                    WHERE agent_id = :agent_id
                      AND compacted_at IS NULL
                    """
                ),
                {"agent_id": agent_id, "compacted_at": now},
            )
            generation = await connection.scalar(
                text(
                    """
                    SELECT COALESCE(MAX(generation), 0) + 1
                    FROM agent_context_windows
                    WHERE agent_id = :agent_id
                    """
                ),
                {"agent_id": agent_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO agent_context_windows (
                        id, agent_id, turn_id, generation, strategy, compaction_id,
                        compacted_until_turn, output_json, usage_json, created_at
                    )
                    VALUES (
                        :id, :agent_id, :turn_id, :generation, :strategy, :compaction_id,
                        :compacted_until_turn, :output_json, :usage_json, :created_at
                    )
                    """
                ).bindparams(
                    bindparam("output_json", type_=JSONB),
                    bindparam("usage_json", type_=JSONB),
                ),
                {
                    "id": new_uuid7(),
                    "agent_id": agent_id,
                    "turn_id": turn_id,
                    "generation": int(generation or 1),
                    "strategy": strategy,
                    "compaction_id": compaction_id,
                    "compacted_until_turn": compacted_until_turn,
                    "output_json": output_json,
                    "usage_json": usage_json,
                    "created_at": now,
                },
            )
            for item_index, item in enumerate(output_json):
                await self._append_context_item_on_connection(
                    connection,
                    agent_id=agent_id,
                    turn_id=turn_id,
                    item_type=str(item.get("type") or COMPACTION_ITEM_TYPE),
                    payload=item,
                    response_id=compaction_id,
                    source=MODEL_CONTEXT_SOURCE,
                    idempotency_key=remote_compaction_idempotency_key(compaction_id, item_index),
                )

    async def add_outbox(self, event: EventEnvelope) -> None:
        async with self._connection() as connection:
            await DbOutboxSink(connection).add(event)


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    import json

    return json.dumps(value, ensure_ascii=False)
