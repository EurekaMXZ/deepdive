from __future__ import annotations

from typing import Any


def completed_response_stream_payload(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response") if isinstance(payload, dict) else None
    response_id = response.get("id") if isinstance(response, dict) else payload.get("response_id")
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
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        return []
    response_id = response.get("id") if response.get("id") is not None else payload.get("response_id")
    output = response.get("output")
    if not isinstance(output, list):
        return []

    summaries: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "reasoning":
            continue
        summary_parts = item.get("summary")
        if not isinstance(summary_parts, list):
            continue
        for summary in summary_parts:
            if not isinstance(summary, dict) or summary.get("type") != "summary_text":
                continue
            text = summary.get("text")
            if not isinstance(text, str) or not text:
                continue
            stream_payload: dict[str, Any] = {
                "type": "model_reasoning_summary",
                "text": text,
            }
            if item.get("id") is not None:
                stream_payload["item_id"] = str(item["id"])
            if response_id is not None:
                stream_payload["response_id"] = str(response_id)
            summaries.append(stream_payload)
    return summaries
