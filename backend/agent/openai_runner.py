from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, cast

from backend.agent import CompactionResponse, ModelResponse, ModelToolCall
from backend.events.model_stream_payloads import (
    completed_response_stream_payload,
    model_reasoning_summary_stream_payloads,
    model_reasoning_summary_text_stream_payload,
)


class IncompleteResponseStreamError(RuntimeError):
    pass


DeltaEmitter = Callable[[str], None]
RawEventEmitter = Callable[[str, dict[str, Any]], None]
AsyncDeltaCallback = Callable[[str], Coroutine[Any, Any, None]]
AsyncRawEventCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class StreamingHttpResponse(Protocol):
    headers: Any

    def __iter__(self) -> Iterator[bytes]: ...

    def read(self) -> bytes: ...

    def close(self) -> None: ...


class ResponsesWebSocket(Protocol):
    def send(self, value: str) -> None: ...

    def recv(self) -> str | bytes | None: ...

    def close(self) -> None: ...


def _optional_delta_callback(value: Any) -> AsyncDeltaCallback | None:
    return cast(AsyncDeltaCallback, value) if callable(value) else None


def _optional_raw_event_callback(value: Any) -> AsyncRawEventCallback | None:
    return cast(AsyncRawEventCallback, value) if callable(value) else None


def _capture_delta_error(
    loop: asyncio.AbstractEventLoop,
    delta_error_future: asyncio.Future[None],
    delta_closed: threading.Event,
    cancel_event: threading.Event,
) -> Callable[[concurrent.futures.Future[None]], None]:
    def callback(future: concurrent.futures.Future[None]) -> None:
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


def _create_websocket_connection(url: str, headers: list[str], timeout_seconds: int) -> ResponsesWebSocket:
    try:
        import websocket
    except ImportError as exc:
        raise RuntimeError("Responses WebSocket mode requires the websocket-client package.") from exc
    websocket_module = cast(Any, websocket)
    factory = cast(Callable[..., ResponsesWebSocket], websocket_module.create_connection)
    return factory(url, header=headers, timeout=timeout_seconds)


def _websocket_url(base_url: str) -> str:
    url = base_url.rstrip("/") + "/responses"
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


@dataclass(frozen=True)
class OpenAIResponsesRunner:
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 300
    total_timeout_seconds: float | None = None
    user_agent: str = "DeepDive/1.0"

    async def create_response(self, request: dict[str, Any]) -> ModelResponse:
        loop = asyncio.get_running_loop()
        pending_stream_writes: list[concurrent.futures.Future[None]] = []
        request_for_thread = dict(request)
        on_delta = _optional_delta_callback(request_for_thread.pop("on_delta", None))
        on_raw_sse_event = _optional_raw_event_callback(request_for_thread.pop("on_raw_sse_event", None))
        stream_closed = threading.Event()
        cancel_event = threading.Event()
        stream_error_future: asyncio.Future[None] = loop.create_future()

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
                    done, _pending = await asyncio.wait(
                        {response_task, stream_error_future},
                        timeout=self.total_timeout_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        raise TimeoutError()
                else:
                    done, _pending = await asyncio.wait(
                        {response_task, stream_error_future},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                if stream_error_future in done:
                    response_task.cancel()
                    exc = stream_error_future.exception()
                    if exc is not None:
                        raise exc
                    raise RuntimeError("Model stream callback failed without an exception")
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

    async def compact_response(self, request: dict[str, Any]) -> CompactionResponse:
        return await asyncio.to_thread(self._compact_response_sync, request)

    def _compact_response_sync(self, request: dict[str, Any]) -> CompactionResponse:
        body = dict(request)
        url = self.base_url.rstrip("/") + "/responses/compact"
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
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"OpenAI Responses compact API failed: {exc.code} {detail}") from exc
        return parse_compaction_payload(payload)

    def _create_response_sync_with_cancel(
        self,
        request: dict[str, Any],
        emit_delta: DeltaEmitter | None = None,
        emit_raw_sse_event: RawEventEmitter | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {"emit_delta": emit_delta}
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
        emit_delta: DeltaEmitter | None = None,
        emit_raw_sse_event: RawEventEmitter | None = None,
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
                response = cast(StreamingHttpResponse, response)
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
        response: StreamingHttpResponse,
        *,
        emit_delta: DeltaEmitter | None,
        emit_raw_sse_event: RawEventEmitter | None = None,
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
                    for stream_event_name, stream_payload in _model_stream_payloads_for_response_event(
                        parsed_event_name,
                        payload,
                    ):
                        emit_raw_sse_event(stream_event_name, stream_payload)
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


@dataclass(frozen=True)
class OpenAIWebSocketResponsesRunner(OpenAIResponsesRunner):
    _websocket: ClassVar[Any | None] = None
    _websocket_lock: ClassVar[threading.Lock] = threading.Lock()

    def __post_init__(self) -> None:
        object.__setattr__(self, "_websocket", None)
        object.__setattr__(self, "_websocket_lock", threading.Lock())

    def _create_response_sync(
        self,
        request: dict[str, Any],
        emit_delta: DeltaEmitter | None = None,
        emit_raw_sse_event: RawEventEmitter | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ModelResponse:
        body = dict(request)
        body.pop("stream", None)
        body.pop("background", None)
        body["type"] = "response.create"

        with self._websocket_lock:
            websocket = self._get_websocket()
            try:
                websocket.send(json.dumps(body))
                return self._parse_websocket_response(
                    websocket,
                    emit_delta=emit_delta,
                    emit_raw_sse_event=emit_raw_sse_event,
                    cancel_event=cancel_event,
                )
            except IncompleteResponseStreamError:
                self._close_websocket_unlocked()
                raise
            except TimeoutError:
                self._close_websocket_unlocked()
                raise
            except Exception:
                self._close_websocket_unlocked()
                raise

    def close(self) -> None:
        with self._websocket_lock:
            self._close_websocket_unlocked()

    def _get_websocket(self) -> ResponsesWebSocket:
        websocket = self._websocket
        if websocket is not None:
            return websocket
        websocket = _create_websocket_connection(
            _websocket_url(self.base_url),
            [
                f"Authorization: Bearer {self.api_key}",
                f"User-Agent: {self.user_agent}",
            ],
            self.timeout_seconds,
        )
        object.__setattr__(self, "_websocket", websocket)
        return websocket

    def _close_websocket_unlocked(self) -> None:
        websocket = self._websocket
        object.__setattr__(self, "_websocket", None)
        if websocket is None:
            return
        close = getattr(websocket, "close", None)
        if close is not None:
            close()

    def _parse_websocket_response(
        self,
        websocket: ResponsesWebSocket,
        *,
        emit_delta: DeltaEmitter | None,
        emit_raw_sse_event: RawEventEmitter | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ModelResponse:
        output_text: list[str] = []
        tool_calls: list[ModelToolCall] = []
        accumulator = StreamingResponseAccumulator()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise TimeoutError("OpenAI Responses websocket stream was cancelled")
            try:
                raw_message = websocket.recv()
            except Exception as exc:
                raise IncompleteResponseStreamError(
                    f"OpenAI Responses websocket stream ended before response.completed: {exc}"
                ) from exc
            payload = _parse_websocket_message(raw_message)
            event_name = str(payload.get("type") or "")
            if event_name == "error":
                raw_error = payload.get("error")
                error = cast(dict[str, Any], raw_error) if isinstance(raw_error, dict) else {}
                code = str(error.get("code") or payload.get("status") or "websocket_error")
                message = str(error.get("message") or json.dumps(payload, ensure_ascii=False))
                raise RuntimeError(f"OpenAI Responses WebSocket failed: {code} {message}") from None
            if emit_raw_sse_event is not None:
                for stream_event_name, stream_payload in _model_stream_payloads_for_response_event(event_name, payload):
                    emit_raw_sse_event(stream_event_name, stream_payload)
            item = accumulator.accept(event_name, payload)
            if item["kind"] == "delta":
                text = item["text"]
                output_text.append(text)
                if emit_delta is not None:
                    emit_delta(text)
            elif item["kind"] == "tool_call":
                tool_calls.append(item["tool_call"])
            elif item["kind"] == "completed":
                completed = item["response"]
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


def _parse_websocket_message(raw_message: str | bytes | None) -> dict[str, Any]:
    if raw_message is None:
        raise IncompleteResponseStreamError("OpenAI Responses websocket stream ended before response.completed")
    raw_text = raw_message.decode("utf-8", errors="replace") if isinstance(raw_message, bytes) else raw_message
    if not raw_text.strip():
        raise IncompleteResponseStreamError("OpenAI Responses websocket stream ended before response.completed")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI Responses WebSocket returned invalid JSON event") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI Responses WebSocket returned non-object JSON event")
    return cast(dict[str, Any], payload)


def create_openai_responses_runner(
    *,
    transport: str = "http",
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    timeout_seconds: int = 300,
    total_timeout_seconds: float | None = None,
    user_agent: str = "DeepDive/1.0",
) -> OpenAIResponsesRunner:
    normalized_transport = transport.strip().lower()
    runner_cls = OpenAIWebSocketResponsesRunner if normalized_transport == "websocket_v2" else OpenAIResponsesRunner
    return runner_cls(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        user_agent=user_agent,
    )


def parse_response_payload(payload: dict[str, Any]) -> ModelResponse:
    output_text_parts: list[str] = []
    tool_calls: list[ModelToolCall] = []
    output = payload.get("output", [])
    output_items = _object_list(output)
    for item in output_items:
        item_type = item.get("type")
        if item_type == "message":
            content = item.get("content", [])
            content_items = _object_list(content)
            for part in content_items:
                if part.get("type") == "output_text":
                    output_text_parts.append(str(part.get("text", "")))
        if item_type == "function_call":
            arguments = item.get("arguments") or "{}"
            tool_calls.append(
                ModelToolCall(
                    call_id=str(item["call_id"]),
                    name=str(item["name"]),
                    arguments=_json_object(arguments),
                )
            )
    usage = _response_usage(payload.get("usage"))
    return ModelResponse(
        response_id=str(payload["id"]),
        output_text="".join(output_text_parts),
        tool_calls=tool_calls,
        usage=usage,
        output_items=output_items,
    )


def parse_compaction_payload(payload: dict[str, Any]) -> CompactionResponse:
    return CompactionResponse(
        compaction_id=str(payload.get("id") or ""),
        output=_object_list(payload.get("output")),
        usage=_response_usage(payload.get("usage")),
    )


def _response_usage(value: Any) -> dict[str, int]:
    usage = _object_or_empty(value)
    input_tokens = _int_usage_value(usage.get("input_tokens"))
    output_tokens = _int_usage_value(usage.get("output_tokens"))
    total_tokens = _int_usage_value(usage.get("total_tokens"))
    input_details = _object_or_empty(usage.get("input_tokens_details"))
    output_details = _object_or_empty(usage.get("output_tokens_details"))
    cached_input_tokens = _int_usage_value(input_details.get("cached_tokens"))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": max(input_tokens - cached_input_tokens, 0),
        "reasoning_tokens": _int_usage_value(output_details.get("reasoning_tokens")),
    }


def _int_usage_value(value: Any) -> int:
    return max(int(value or 0), 0)


def parse_stream_event(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_name == "response.output_text.delta":
        return {"kind": "delta", "text": str(payload.get("delta", ""))}
    if event_name == "response.function_call_arguments.done":
        raw_item = payload.get("item")
        item = cast(dict[str, Any], raw_item) if isinstance(raw_item, dict) else payload
        if not item.get("call_id"):
            return {"kind": "tool_call_delta_done", "payload": payload}
        return {
            "kind": "tool_call",
            "tool_call": ModelToolCall(
                call_id=str(item["call_id"]),
                name=str(item["name"]),
                arguments=_json_object(item.get("arguments") or "{}"),
            ),
        }
    if event_name == "response.completed":
        return {"kind": "completed", "response": parse_response_payload(_json_object(payload["response"]))}
    return {"kind": "ignored"}


class StreamingResponseAccumulator:
    def __init__(self) -> None:
        self._function_items: dict[str, dict[str, Any]] = {}
        self._function_argument_fragments: dict[str, list[str]] = {}
        self._function_arguments_done: set[str] = set()

    def accept(self, event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_name == "response.output_item.added":
            item = _object_or_empty(payload.get("item"))
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
            item = _object_or_empty(payload.get("item"))
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

        done_payload = _json_object(parsed["payload"])
        item_id = done_payload.get("item_id")
        item = dict(self._function_items.get(str(item_id), {}))
        item.update(_object_or_empty(done_payload.get("item")))
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
            call_id=str(item["call_id"]),
            name=str(item["name"]),
            arguments=_json_object(item.get("arguments") or "{}"),
        ),
    }


def _model_stream_payloads_for_response_event(
    event_name: str,
    payload: dict[str, Any],
    *,
    include_completed_reasoning_summary: bool = True,
) -> list[tuple[str, dict[str, Any]]]:
    summary_payload = model_reasoning_summary_text_stream_payload(event_name, payload)
    if summary_payload is not None:
        return [summary_payload]
    if event_name == "response.completed":
        events: list[tuple[str, dict[str, Any]]] = []
        if include_completed_reasoning_summary:
            events.extend(
                ("model_reasoning_summary", summary) for summary in model_reasoning_summary_stream_payloads(payload)
            )
        events.append(("response.completed", completed_response_stream_payload(payload)))
        return events
    return [(event_name, payload)]


def _function_event_item_id(payload: dict[str, Any]) -> str | None:
    item_id = payload.get("item_id")
    if item_id is not None:
        return str(item_id)
    raw_item = payload.get("item")
    item = cast(dict[str, Any], raw_item) if isinstance(raw_item, dict) else {}
    if item.get("id") is not None:
        return str(item["id"])
    return None


def _flush_stream_event(event_name: str | None, data_lines: list[str]) -> tuple[str, dict[str, Any]] | None:
    if event_name is None or not data_lines:
        return None
    return event_name, _json_object("\n".join(data_lines))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise RuntimeError("Expected JSON object")
    return cast(dict[str, Any], parsed)


def _object_or_empty(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in cast(list[Any], value):
        if isinstance(item, dict):
            items.append(cast(dict[str, Any], item))
    return items
