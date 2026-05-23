from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from backend.agent import ModelResponse, ModelToolCall
from backend.events.live_stream import (
    completed_live_payload,
    model_reasoning_summary_live_payloads,
    model_reasoning_summary_text_live_payload,
)


class IncompleteResponseStreamError(RuntimeError):
    pass


def _capture_delta_error(loop, delta_error_future, delta_closed: threading.Event, cancel_event: threading.Event):
    def callback(future) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc is None:
            return
        delta_closed.set()
        cancel_event.set()
        if not delta_error_future.done():
            loop.call_soon_threadsafe(delta_error_future.set_exception, exc)

    return callback


@dataclass(frozen=True)
class OpenAIResponsesRunner:
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 300
    total_timeout_seconds: float | None = None
    user_agent: str = "DeepDive/1.0"

    async def create_response(self, request: dict[str, Any]) -> ModelResponse:
        import asyncio

        loop = asyncio.get_running_loop()
        pending_stream_writes = []
        request_for_thread = dict(request)
        on_delta = request_for_thread.pop("on_delta", None)
        on_raw_sse_event = request_for_thread.pop("on_raw_sse_event", None)
        stream_closed = threading.Event()
        cancel_event = threading.Event()
        stream_error_future = loop.create_future()

        def emit_delta(text: str) -> None:
            if on_delta is not None and not stream_closed.is_set():
                future = asyncio.run_coroutine_threadsafe(on_delta(text), loop)
                pending_stream_writes.append(future)
                future.add_done_callback(_capture_delta_error(loop, stream_error_future, stream_closed, cancel_event))

        def emit_raw_sse_event(event_name: str, payload: dict[str, Any]) -> None:
            if on_raw_sse_event is not None and not stream_closed.is_set():
                future = asyncio.run_coroutine_threadsafe(on_raw_sse_event(event_name, payload), loop)
                pending_stream_writes.append(future)
                future.add_done_callback(_capture_delta_error(loop, stream_error_future, stream_closed, cancel_event))

        response_future = asyncio.to_thread(
            self._create_response_sync_with_cancel,
            request_for_thread,
            emit_delta,
            emit_raw_sse_event if on_raw_sse_event is not None else None,
            cancel_event,
        )
        try:
            response_task = asyncio.create_task(response_future)
            try:
                if self.total_timeout_seconds is not None and self.total_timeout_seconds > 0:
                    done, pending = await asyncio.wait(
                        {response_task, stream_error_future},
                        timeout=self.total_timeout_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        raise TimeoutError()
                else:
                    done, pending = await asyncio.wait(
                        {response_task, stream_error_future},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                if stream_error_future in done:
                    response_task.cancel()
                    raise stream_error_future.result()
                response = response_task.result()
            finally:
                stream_error_future.cancel()
            stream_closed.set()
            for future in pending_stream_writes:
                await asyncio.wrap_future(future)
            return response
        except BaseException:
            stream_closed.set()
            cancel_event.set()
            for future in pending_stream_writes:
                future.cancel()
            raise

    def _create_response_sync_with_cancel(
        self,
        request: dict[str, Any],
        emit_delta=None,
        emit_raw_sse_event=None,
        cancel_event: threading.Event | None = None,
    ) -> ModelResponse:
        kwargs = {"emit_delta": emit_delta}
        if emit_raw_sse_event is not None:
            kwargs["emit_raw_sse_event"] = emit_raw_sse_event
        if cancel_event is not None:
            kwargs["cancel_event"] = cancel_event
        try:
            return self._create_response_sync(request, **kwargs)
        except TypeError as exc:
            message = str(exc)
            if "cancel_event" in message:
                kwargs.pop("cancel_event", None)
                return self._create_response_sync(request, **kwargs)
            if "emit_raw_sse_event" in message:
                kwargs.pop("emit_raw_sse_event", None)
                return self._create_response_sync(request, **kwargs)
            if "cancel_event" not in message:
                raise
            raise

    def _create_response_sync(
        self,
        request: dict[str, Any],
        emit_delta=None,
        emit_raw_sse_event=None,
        cancel_event: threading.Event | None = None,
    ) -> ModelResponse:
        body = dict(request)
        body["stream"] = True
        url = self.base_url.rstrip("/") + "/responses"
        http_request = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                if response.headers.get("content-type", "").split(";")[0] == "text/event-stream":
                    return self._parse_stream_response(
                        response,
                        emit_delta=emit_delta,
                        emit_raw_sse_event=emit_raw_sse_event,
                        cancel_event=cancel_event,
                    )
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"OpenAI Responses API failed: {exc.code} {detail}") from exc
        return parse_response_payload(payload)

    def _parse_stream_response(
        self,
        response,
        *,
        emit_delta,
        emit_raw_sse_event=None,
        cancel_event: threading.Event | None = None,
    ) -> ModelResponse:
        output_text: list[str] = []
        tool_calls: list[ModelToolCall] = []
        completed: ModelResponse | None = None
        accumulator = StreamingResponseAccumulator()
        event_name: str | None = None
        data_lines: list[str] = []
        for raw_line in response:
            if cancel_event is not None and cancel_event.is_set():
                close = getattr(response, "close", None)
                if close is not None:
                    close()
                raise TimeoutError("OpenAI Responses stream was cancelled")
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                parsed = _flush_stream_event(event_name, data_lines)
                event_name = None
                data_lines = []
                if parsed is None:
                    continue
                parsed_event_name, payload = parsed
                item = accumulator.accept(parsed_event_name, payload)
                if emit_raw_sse_event is not None:
                    for live_event_name, live_payload in _live_events_for_sse_event(
                        parsed_event_name,
                        payload,
                    ):
                        emit_raw_sse_event(live_event_name, live_payload)
                if item["kind"] == "delta":
                    text = item["text"]
                    output_text.append(text)
                    if emit_delta is not None:
                        emit_delta(text)
                elif item["kind"] == "tool_call":
                    tool_calls.append(item["tool_call"])
                elif item["kind"] == "completed":
                    completed = item["response"]
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())

        if completed is not None:
            if not completed.response_id:
                raise RuntimeError("OpenAI Responses stream completed without response id")
            if output_text and not completed.output_text:
                return ModelResponse(
                    response_id=completed.response_id,
                    output_text="".join(output_text),
                    tool_calls=tool_calls or completed.tool_calls,
                    usage=completed.usage,
                    output_items=completed.output_items,
                )
            if tool_calls and not completed.tool_calls:
                return ModelResponse(
                    response_id=completed.response_id,
                    output_text=completed.output_text,
                    tool_calls=tool_calls,
                    usage=completed.usage,
                    output_items=completed.output_items,
                )
            return completed
        raise IncompleteResponseStreamError("OpenAI Responses stream ended before response.completed")


def parse_response_payload(payload: dict[str, Any]) -> ModelResponse:
    output_text_parts: list[str] = []
    tool_calls: list[ModelToolCall] = []
    for item in payload.get("output", []):
        item_type = item.get("type")
        if item_type == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    output_text_parts.append(part.get("text", ""))
        if item_type == "function_call":
            arguments = item.get("arguments") or "{}"
            tool_calls.append(
                ModelToolCall(
                    call_id=item["call_id"],
                    name=item["name"],
                    arguments=json.loads(arguments),
                )
            )
    usage = payload.get("usage") or {}
    return ModelResponse(
        response_id=payload["id"],
        output_text="".join(output_text_parts),
        tool_calls=tool_calls,
        usage={
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        output_items=[dict(item) for item in payload.get("output", []) if isinstance(item, dict)],
    )


def parse_stream_event(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_name == "response.output_text.delta":
        return {"kind": "delta", "text": payload.get("delta", "")}
    if event_name == "response.function_call_arguments.done":
        item = payload.get("item") or payload
        if not item.get("call_id"):
            return {"kind": "tool_call_delta_done", "payload": payload}
        return {
            "kind": "tool_call",
            "tool_call": ModelToolCall(
                call_id=item["call_id"],
                name=item["name"],
                arguments=json.loads(item.get("arguments") or "{}"),
            ),
        }
    if event_name == "response.completed":
        return {"kind": "completed", "response": parse_response_payload(payload["response"])}
    return {"kind": "ignored"}


class StreamingResponseAccumulator:
    def __init__(self) -> None:
        self._function_items: dict[str, dict[str, Any]] = {}
        self._function_argument_fragments: dict[str, list[str]] = {}
        self._function_arguments_done: set[str] = set()

    def accept(self, event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_name == "response.output_item.added":
            item = payload.get("item") or {}
            if item.get("type") == "function_call":
                self._function_items[item["id"]] = dict(item)
            return {"kind": "ignored"}
        if event_name == "response.function_call_arguments.delta":
            item_id = payload.get("item_id")
            delta = payload.get("delta", "")
            if item_id and delta:
                self._function_argument_fragments.setdefault(str(item_id), []).append(delta)
            return {"kind": "ignored"}
        if event_name == "response.output_item.done":
            item = payload.get("item") or {}
            if item.get("type") != "function_call":
                return {"kind": "ignored"}
            return _tool_call_item(item)

        parsed = parse_stream_event(event_name, payload)
        if parsed["kind"] != "tool_call_delta_done":
            if parsed["kind"] == "tool_call":
                done_item_id = _function_event_item_id(payload)
                if done_item_id:
                    self._function_arguments_done.add(done_item_id)
            return parsed

        done_payload = parsed["payload"]
        item_id = done_payload.get("item_id")
        item = dict(self._function_items.get(str(item_id), {}))
        item.update(done_payload.get("item") or {})
        if "arguments" in done_payload:
            item["arguments"] = done_payload["arguments"]
        elif str(item_id) in self._function_argument_fragments:
            item["arguments"] = "".join(self._function_argument_fragments[str(item_id)])
        if not item.get("call_id") or not item.get("name"):
            return {"kind": "ignored"}
        if item_id:
            self._function_arguments_done.add(str(item_id))
        return _tool_call_item(item)

def _tool_call_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "tool_call",
        "tool_call": ModelToolCall(
            call_id=item["call_id"],
            name=item["name"],
            arguments=json.loads(item.get("arguments") or "{}"),
        ),
    }


def _live_payload_for_sse_event(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_name == "response.completed":
        return completed_live_payload(payload)
    return payload


def _live_events_for_sse_event(
    event_name: str,
    payload: dict[str, Any],
    *,
    include_completed_reasoning_summary: bool = True,
) -> list[tuple[str, dict[str, Any]]]:
    summary_payload = model_reasoning_summary_text_live_payload(event_name, payload)
    if summary_payload is not None:
        return [summary_payload]
    if event_name == "response.completed":
        events = []
        if include_completed_reasoning_summary:
            events.extend(
                ("model_reasoning_summary", summary)
                for summary in model_reasoning_summary_live_payloads(payload)
            )
        events.append(("response.completed", completed_live_payload(payload)))
        return events
    return [(event_name, payload)]


def _function_event_item_id(payload: dict[str, Any]) -> str | None:
    item_id = payload.get("item_id")
    if item_id is not None:
        return str(item_id)
    item = payload.get("item") or {}
    if item.get("id") is not None:
        return str(item["id"])
    return None


def _flush_stream_event(event_name: str | None, data_lines: list[str]) -> tuple[str, dict[str, Any]] | None:
    if event_name is None or not data_lines:
        return None
    return event_name, json.loads("\n".join(data_lines))
