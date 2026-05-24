from __future__ import annotations

from typing import Any, cast


def completed_response_stream_payload(payload: dict[str, Any]) -> dict[str, Any]:
    response = _json_object(payload.get("response"))
    response_id = response.get("id") if response is not None else payload.get("response_id")
    result = {"type": "response.completed"}
    if response_id:
        result["response_id"] = response_id
    return result


def model_reasoning_summary_text_stream_payload(
    event_name: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if event_name == "response.reasoning_summary_text.delta":
        event_type = "model_reasoning_summary.delta"
        text = payload.get("delta")
    elif event_name == "response.reasoning_summary_text.done":
        event_type = "model_reasoning_summary.done"
        text = payload.get("text")
    else:
        return None
    if not isinstance(text, str) or not text:
        return None

    stream_payload: dict[str, Any] = {
        "type": event_type,
        "text": text,
    }
    for key in ("item_id", "response_id", "summary_index"):
        if payload.get(key) is not None:
            stream_payload[key] = payload[key]
    return event_type, stream_payload


def model_reasoning_summary_stream_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = _json_object(payload.get("response"))
    if response is None:
        return []
    response_id = response.get("id") if response.get("id") is not None else payload.get("response_id")
    output = _json_list(response.get("output"))
    if not output:
        return []

    summaries: list[dict[str, Any]] = []
    for item in output:
        item_object = _json_object(item)
        if item_object is None or item_object.get("type") != "reasoning":
            continue
        summary_parts = _json_list(item_object.get("summary"))
        if not summary_parts:
            continue
        for summary in summary_parts:
            summary_object = _json_object(summary)
            if summary_object is None or summary_object.get("type") != "summary_text":
                continue
            text = summary_object.get("text")
            if not isinstance(text, str) or not text:
                continue
            stream_payload: dict[str, Any] = {
                "type": "model_reasoning_summary",
                "text": text,
            }
            if item_object.get("id") is not None:
                stream_payload["item_id"] = str(item_object["id"])
            if response_id is not None:
                stream_payload["response_id"] = str(response_id)
            summaries.append(stream_payload)
    return summaries


def _json_object(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _json_list(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []
