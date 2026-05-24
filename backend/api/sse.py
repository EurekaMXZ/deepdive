from __future__ import annotations

import json
from typing import Any, Protocol, cast

from backend.api.stream_schemas import TERMINAL_ANALYSIS_STATUSES, TERMINAL_STREAM_EVENT_TYPES

SENSITIVE_DISPLAY_KEYS = frozenset(
    {
        "config_json",
        "context",
        "developer",
        "input",
        "input_ref",
        "instructions",
        "messages",
        "openai_call_id",
        "prompt",
        "response",
        "snapshot_id",
        "source_refs",
        "system",
        "tool_policy_hash",
        "tool_registry_version",
        "tool_schema",
        "tool_schema_hash",
    }
)


def format_sse_event(event: Any) -> str:
    event_type = event_type_of(event)
    payload = json.dumps(
        display_event_payload(event_type, event_payload(event)), ensure_ascii=False, separators=(",", ":")
    )
    return f"id: {event_seq(event)}\nevent: {event_type}\ndata: {payload}\n\n"


class StreamEvent(Protocol):
    seq: int
    event_type: str
    payload_json: dict[str, Any]


def event_seq(event: StreamEvent | dict[str, Any]) -> int:
    return int(event["seq"] if isinstance(event, dict) else event.seq)


def event_type_of(event: StreamEvent | dict[str, Any]) -> str:
    return str(event["event_type"] if isinstance(event, dict) else event.event_type)


def event_payload(event: StreamEvent | dict[str, Any]) -> dict[str, Any]:
    payload = event["payload_json"] if isinstance(event, dict) else event.payload_json
    return cast(dict[str, Any], payload) if isinstance(payload, dict) else {}


def display_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type == "status":
        return _only_keys(payload, ("status",))
    if event_type == "tool_call":
        return _only_keys(payload, ("tool_call_id", "tool_name", "arguments"))
    if event_type == "tool_result":
        return _tool_result_display_payload(payload)
    if event_type == "done":
        return _only_keys(payload, ("status", "response_id", "output_ref"))
    if event_type in {"error", "analysis_error"}:
        return _only_keys(payload, ("error", "error_code", "error_message", "retryable"))
    return _strip_sensitive_display_fields(payload)


def is_terminal_stream_event(event: Any) -> bool:
    if event_type_of(event) in TERMINAL_STREAM_EVENT_TYPES:
        return True
    status_value = event_payload(event).get("status")
    return status_value in TERMINAL_ANALYSIS_STATUSES


def parse_last_event_id(value: str | None) -> int:
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _tool_result_display_payload(payload: dict[str, Any]) -> dict[str, Any]:
    display: dict[str, Any] = {}
    for key in ("tool_call_id", "tool_name", "ok"):
        if key in payload:
            display[key] = _strip_sensitive_display_fields(payload[key])
    if "result" in payload:
        display["result"] = _strip_sensitive_display_fields(payload["result"])
    if "error" in payload:
        display["error"] = _strip_sensitive_display_fields(payload["error"])
    for key in ("result_ref", "evidence_ids", "truncated", "next_cursor"):
        if key in payload and payload[key] is not None:
            display[key] = _strip_sensitive_display_fields(payload[key])
    return display


def _only_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: _strip_sensitive_display_fields(payload[key]) for key in keys if key in payload}


def _strip_sensitive_display_fields(value: Any) -> Any:
    if isinstance(value, dict):
        value = cast(dict[Any, Any], value)
        display: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() not in SENSITIVE_DISPLAY_KEYS:
                display[key_text] = _strip_sensitive_display_fields(item)
        return display
    if isinstance(value, list):
        return [_strip_sensitive_display_fields(item) for item in cast(list[Any], value)]
    return value
