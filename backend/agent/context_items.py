from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.db.connections import AsyncDbConnection
from backend.ids import new_uuid7

MODEL_CONTEXT_SOURCE = "model"
TOOL_CONTEXT_SOURCE = "tool"

FUNCTION_CALL_ITEM_TYPE = "function_call"
FUNCTION_CALL_OUTPUT_ITEM_TYPE = "function_call_output"
ASSISTANT_OUTPUT_ITEM_TYPE = "assistant_output"
COMPACTION_ITEM_TYPE = "compaction"


def function_call_payload(*, call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }


def function_call_output_payload(*, call_id: str, output: dict[str, Any] | str) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, sort_keys=True),
    }


def assistant_output_payload(text_value: str) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text_value}],
    }


def model_function_call_idempotency_key(call_id: str) -> str:
    return f"model:function_call:{call_id}"


def tool_output_idempotency_key(call_id: str) -> str:
    return f"tool:function_call_output:{call_id}"


def assistant_output_idempotency_key(response_id: str) -> str:
    return f"model:assistant_output:{response_id}"


def remote_compaction_idempotency_key(compaction_id: str, item_index: int) -> str:
    return f"model:remote_compaction:{compaction_id}:{item_index}"


def canonical_model_item_type(payload: dict[str, Any]) -> str:
    return str(payload.get("type") or "model_output")


def canonical_model_item_idempotency_key(payload: dict[str, Any], *, response_id: str) -> str:
    item_type = canonical_model_item_type(payload)
    if item_type == FUNCTION_CALL_ITEM_TYPE and isinstance(payload.get("call_id"), str):
        return model_function_call_idempotency_key(str(payload["call_id"]))
    item_id = payload.get("id")
    if isinstance(item_id, str) and item_id:
        return f"model:{item_type}:{item_id}"
    return f"model:{item_type}:{response_id}"


async def append_context_item_on_connection(
    connection: AsyncDbConnection,
    *,
    agent_id: UUID,
    turn_id: UUID | None,
    item_type: str,
    payload: dict[str, Any],
    response_id: str | None = None,
    source: str,
    idempotency_key: str | None,
) -> None:
    await connection.scalar(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:agent_id, 0))"),
        {"agent_id": str(agent_id)},
    )
    seq = await connection.scalar(
        text(
            """
            SELECT COALESCE(MAX(seq), 0) + 1
            FROM agent_context_items
            WHERE agent_id = :agent_id
            """
        ),
        {"agent_id": agent_id},
    )
    await connection.execute(
        text(
            """
            INSERT INTO agent_context_items (
                id, agent_id, turn_id, seq, item_type, payload_json,
                response_id, source, idempotency_key, compacted_at, created_at
            )
            VALUES (
                :id, :agent_id, :turn_id, :seq, :item_type, :payload_json,
                :response_id, :source, :idempotency_key, NULL, :created_at
            )
            ON CONFLICT (agent_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
            DO NOTHING
            """
        ).bindparams(bindparam("payload_json", type_=JSONB)),
        {
            "id": new_uuid7(),
            "agent_id": agent_id,
            "turn_id": turn_id,
            "seq": seq,
            "item_type": item_type,
            "payload_json": payload,
            "response_id": response_id,
            "source": source,
            "idempotency_key": idempotency_key,
            "created_at": datetime.now(UTC),
        },
    )
