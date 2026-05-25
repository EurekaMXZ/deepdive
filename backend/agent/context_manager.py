from __future__ import annotations

from typing import Any, Protocol, cast

from backend.agent.models import AgentSessionState

REPLAYABLE_MESSAGE_ROLES = frozenset({"assistant", "user", "developer", "system"})
TOOL_CALL_TYPES = frozenset({"function_call", "custom_tool_call"})
TOOL_OUTPUT_TYPES = frozenset({"function_call_output", "custom_tool_call_output"})
GENERATED_ITEM_TYPES = frozenset(
    {
        "assistant_output",
        "custom_tool_call",
        "custom_tool_call_output",
        "function_call",
        "function_call_output",
        "reasoning",
    }
)


class ContextHistoryRepository(Protocol):
    async def load_uncompacted_context_items(self, *, agent_id: Any, limit: int = 12) -> list[dict[str, Any]]: ...


class AgentContextManager:
    def __init__(self, *, repository: ContextHistoryRepository, replay_limit: int = 200) -> None:
        self._repository = repository
        self._replay_limit = replay_limit

    async def for_prompt(
        self,
        *,
        session: AgentSessionState,
        extra_items: list[dict[str, Any]] | None = None,
        exclude_call_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows = await self._repository.load_uncompacted_context_items(
            agent_id=session.agent_id,
            limit=self._replay_limit,
        )
        payloads = _payloads_from_rows(rows)
        payloads = _prune_before_latest_compaction(payloads)
        payloads.extend(extra_items or [])
        if exclude_call_ids:
            payloads = [item for item in payloads if _item_call_id(item) not in exclude_call_ids]
        return normalize_response_items(payloads)


def normalize_response_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replayable = [item for item in items if _is_replayable_response_item(item)]
    call_ids = {_item_call_id(item) for item in replayable if _item_type(item) in TOOL_CALL_TYPES}
    output_ids = {_item_call_id(item) for item in replayable if _item_type(item) in TOOL_OUTPUT_TYPES}
    paired_call_ids = {call_id for call_id in call_ids.intersection(output_ids) if call_id}

    normalized: list[dict[str, Any]] = []
    for item in replayable:
        item_type = _item_type(item)
        call_id = _item_call_id(item)
        if item_type in TOOL_CALL_TYPES and call_id not in paired_call_ids:
            continue
        if item_type in TOOL_OUTPUT_TYPES and call_id not in paired_call_ids:
            continue
        normalized.append(item)
    return normalized


def _payloads_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload_json")
        if isinstance(payload, dict):
            payloads.append(cast(dict[str, Any], payload))
    return payloads


def _prune_before_latest_compaction(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_compaction_index = _latest_compaction_index(items)
    if latest_compaction_index is None:
        return items

    retained: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if index >= latest_compaction_index:
            retained.append(item)
            continue
        if _is_true_context_message(item):
            retained.append(item)
    return retained


def _latest_compaction_index(items: list[dict[str, Any]]) -> int | None:
    for index in range(len(items) - 1, -1, -1):
        if _item_type(items[index]) == "compaction":
            return index
    return None


def _is_true_context_message(item: dict[str, Any]) -> bool:
    if _item_type(item) != "message":
        return False
    return item.get("role") in {"user", "developer", "system"}


def _is_replayable_response_item(item: dict[str, Any]) -> bool:
    item_type = _item_type(item)
    if item_type in TOOL_CALL_TYPES or item_type in TOOL_OUTPUT_TYPES:
        return bool(_item_call_id(item))
    if item_type in {"compaction", "reasoning"}:
        return True
    if item_type == "message":
        return item.get("role") in REPLAYABLE_MESSAGE_ROLES
    return False


def _item_type(item: dict[str, Any]) -> str:
    return str(item.get("type") or "")


def _item_call_id(item: dict[str, Any]) -> str | None:
    call_id = item.get("call_id")
    return call_id if isinstance(call_id, str) and call_id else None
