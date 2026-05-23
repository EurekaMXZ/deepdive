from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from backend.agent.openai_runner import (
    IncompleteResponseStreamError,
    OpenAIResponsesRunner,
    StreamingResponseAccumulator,
    parse_response_payload,
    parse_stream_event,
)


class OpenAIRunnerTest(unittest.TestCase):
    def test_create_response_sets_configured_user_agent_header(self) -> None:
        captured_requests = []

        def fake_urlopen(request, timeout):
            del timeout
            captured_requests.append(request)
            return FakeJsonResponse(
                {
                    "id": "resp_1",
                    "output": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                }
            )

        runner = OpenAIResponsesRunner(api_key="test-key", user_agent="DeepDive/custom")

        with patch("backend.agent.openai_runner.urllib.request.urlopen", fake_urlopen):
            response = runner._create_response_sync({"model": "test", "input": []})

        self.assertEqual(response.response_id, "resp_1")
        headers = dict(captured_requests[0].header_items())
        self.assertEqual(headers["User-agent"], "DeepDive/custom")

    def test_parse_response_payload_extracts_text_tool_call_and_usage(self) -> None:
        output_items = [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "hello"}],
            },
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": "{\"path\":\"backend/api/app.py\"}",
            },
        ]
        response = parse_response_payload(
            {
                "id": "resp_1",
                "output": output_items,
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            }
        )

        self.assertEqual(response.response_id, "resp_1")
        self.assertEqual(response.output_text, "hello")
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "backend/api/app.py"})
        self.assertEqual(response.usage["total_tokens"], 5)
        self.assertEqual(response.output_items, output_items)

    def test_parse_response_payload_preserves_reasoning_and_phase_output_items(self) -> None:
        output_items = [
            {"id": "rs_1", "type": "reasoning", "summary": [], "phase": "analysis"},
            {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": "{\"path\":\"README.md\"}",
                "status": "completed",
                "phase": "tool_calling",
            },
        ]

        response = parse_response_payload(
            {
                "id": "resp_1",
                "output": output_items,
                "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            }
        )

        self.assertEqual(response.output_items, output_items)
        self.assertEqual(response.output_items[0]["phase"], "analysis")
        self.assertEqual(response.output_items[1]["id"], "fc_1")

    def test_parse_stream_event_extracts_delta_function_call_and_completion(self) -> None:
        delta = parse_stream_event(
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "hi"},
        )
        tool = parse_stream_event(
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": "{\"path\":\"a.py\"}",
                },
            },
        )
        completed = parse_stream_event(
            "response.completed",
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "output": [],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            },
        )

        self.assertEqual(delta, {"kind": "delta", "text": "hi"})
        self.assertEqual(tool["kind"], "tool_call")
        self.assertEqual(tool["tool_call"].arguments, {"path": "a.py"})
        self.assertEqual(completed["kind"], "completed")
        self.assertEqual(completed["response"].response_id, "resp_1")

    def test_parse_stream_event_accepts_flat_function_call_done_payload(self) -> None:
        tool = parse_stream_event(
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "call_id": "call_1",
                "name": "search_file",
                "arguments": "{\"query\":\"api\"}",
            },
        )

        self.assertEqual(tool["kind"], "tool_call")
        self.assertEqual(tool["tool_call"].name, "search_file")
        self.assertEqual(tool["tool_call"].arguments, {"query": "api"})

    def test_streaming_accumulator_combines_output_item_with_arguments_done(self) -> None:
        accumulator = StreamingResponseAccumulator()
        accumulator.accept(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "item": {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": "",
                },
            },
        )
        item = accumulator.accept(
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "arguments": "{\"path\":\"a.py\"}",
            },
        )

        self.assertEqual(item["kind"], "tool_call")
        self.assertEqual(item["tool_call"].call_id, "call_1")
        self.assertEqual(item["tool_call"].name, "read_file")
        self.assertEqual(item["tool_call"].arguments, {"path": "a.py"})

    def test_streaming_accumulator_extracts_function_call_from_output_item_done(self) -> None:
        accumulator = StreamingResponseAccumulator()

        item = accumulator.accept(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "search_file",
                    "arguments": "{\"query\":\"api\"}",
                    "status": "completed",
                },
            },
        )

        self.assertEqual(item["kind"], "tool_call")
        self.assertEqual(item["tool_call"].call_id, "call_1")
        self.assertEqual(item["tool_call"].name, "search_file")
        self.assertEqual(item["tool_call"].arguments, {"query": "api"})

    def test_stream_parser_raises_retryable_incomplete_stream_without_completed_event(self) -> None:
        runner = OpenAIResponsesRunner(api_key="test-key")

        with self.assertRaisesRegex(IncompleteResponseStreamError, "ended before response.completed"):
            runner._parse_stream_response(
                FakeSseResponse(
                    [
                        b"event: response.created\n",
                        b"data: {\"type\":\"response.created\",\"response\":{\"id\":\"resp_partial\"}}\n",
                        b"\n",
                        b"event: response.output_text.delta\n",
                        b"data: {\"type\":\"response.output_text.delta\",\"delta\":\"partial\"}\n",
                        b"\n",
                    ]
                ),
                emit_delta=None,
            )

    def test_stream_parser_emits_delta_from_crlf_delimited_sse(self) -> None:
        runner = OpenAIResponsesRunner(api_key="test-key")
        emitted_deltas: list[str] = []

        response = runner._parse_stream_response(
            FakeSseResponse(
                [
                    b"event: response.output_text.delta\r\n",
                    b"data: {\"type\":\"response.output_text.delta\",\"delta\":\"hello\"}\r\n",
                    b"\r\n",
                    b"event: response.completed\r\n",
                    (
                        b"data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_1\","
                        b"\"output\":[],\"usage\":{\"input_tokens\":1,\"output_tokens\":1,\"total_tokens\":2}}}\r\n"
                    ),
                    b"\r\n",
                ]
            ),
            emit_delta=emitted_deltas.append,
        )

        self.assertEqual(emitted_deltas, ["hello"])
        self.assertEqual(response.response_id, "resp_1")
        self.assertEqual(response.output_text, "hello")

    def test_stream_parser_emits_raw_sse_events_for_text_and_function_calls(self) -> None:
        runner = OpenAIResponsesRunner(api_key="test-key")
        emitted_deltas: list[str] = []
        emitted_raw_events: list[tuple[str, dict]] = []

        response = runner._parse_stream_response(
            FakeSseResponse(
                [
                    b"event: response.output_item.added\n",
                    (
                        b"data: {\"type\":\"response.output_item.added\",\"response_id\":\"resp_1\","
                        b"\"output_index\":0,\"item\":{\"id\":\"fc_1\",\"type\":\"function_call\","
                        b"\"call_id\":\"call_1\",\"name\":\"read_file\",\"arguments\":\"\"}}\n"
                    ),
                    b"\n",
                    b"event: response.function_call_arguments.delta\n",
                    (
                        b"data: {\"type\":\"response.function_call_arguments.delta\","
                        b"\"response_id\":\"resp_1\",\"item_id\":\"fc_1\",\"output_index\":0,"
                        b"\"delta\":\"{\\\"path\\\":\"}\n"
                    ),
                    b"\n",
                    b"event: response.function_call_arguments.delta\n",
                    (
                        b"data: {\"type\":\"response.function_call_arguments.delta\","
                        b"\"response_id\":\"resp_1\",\"item_id\":\"fc_1\",\"output_index\":0,"
                        b"\"delta\":\"\\\"README.md\\\"}\"}\n"
                    ),
                    b"\n",
                    b"event: response.function_call_arguments.done\n",
                    (
                        b"data: {\"type\":\"response.function_call_arguments.done\","
                        b"\"response_id\":\"resp_1\",\"item_id\":\"fc_1\",\"output_index\":0,"
                        b"\"arguments\":\"{\\\"path\\\":\\\"README.md\\\"}\"}\n"
                    ),
                    b"\n",
                    b"event: response.output_text.delta\n",
                    (
                        "data: {\"type\":\"response.output_text.delta\",\"response_id\":\"resp_1\","
                        "\"item_id\":\"msg_1\",\"output_index\":1,\"content_index\":0,\"delta\":\"分析\"}\n"
                    ).encode(),
                    b"\n",
                    b"event: response.output_text.done\n",
                    (
                        "data: {\"type\":\"response.output_text.done\",\"response_id\":\"resp_1\","
                        "\"item_id\":\"msg_1\",\"output_index\":1,\"content_index\":0,\"text\":\"分析\"}\n"
                    ).encode(),
                    b"\n",
                    b"event: response.completed\n",
                    (
                        "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_1\","
                        "\"output\":[{\"type\":\"function_call\",\"call_id\":\"call_1\","
                        "\"name\":\"read_file\",\"arguments\":\"{\\\"path\\\":\\\"README.md\\\"}\"},"
                        "{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"分析\"}]}],"
                        "\"usage\":{\"input_tokens\":1,\"output_tokens\":2,\"total_tokens\":3}}}\n"
                    ).encode(),
                    b"\n",
                ]
            ),
            emit_delta=emitted_deltas.append,
            emit_raw_sse_event=lambda event_name, payload: emitted_raw_events.append((event_name, payload)),
        )

        self.assertEqual(emitted_deltas, ["分析"])
        self.assertEqual(response.output_text, "分析")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "README.md"})
        event_types = [event_name for event_name, _ in emitted_raw_events]
        self.assertEqual(
            event_types,
            [
                "response.output_item.added",
                "response.function_call_arguments.delta",
                "response.function_call_arguments.delta",
                "response.function_call_arguments.done",
                "response.output_text.delta",
                "response.output_text.done",
                "response.completed",
            ],
        )
        self.assertEqual(emitted_raw_events[0][1]["item"]["name"], "read_file")
        self.assertEqual(emitted_raw_events[1][1]["delta"], "{\"path\":")
        self.assertEqual(emitted_raw_events[3][1]["arguments"], "{\"path\":\"README.md\"}")
        self.assertEqual(emitted_raw_events[4][1]["delta"], "分析")
        self.assertEqual(emitted_raw_events[6][1], {"type": "response.completed", "response_id": "resp_1"})

    def test_stream_parser_emits_reasoning_summary_delta_as_model_summary_event(self) -> None:
        runner = OpenAIResponsesRunner(api_key="test-key")
        emitted_raw_events: list[tuple[str, dict]] = []

        response = runner._parse_stream_response(
            FakeSseResponse(
                [
                    b"event: response.reasoning_summary_text.delta\n",
                    (
                        "data: {\"type\":\"response.reasoning_summary_text.delta\","
                        "\"response_id\":\"resp_1\",\"item_id\":\"rs_1\",\"output_index\":0,"
                        "\"summary_index\":0,\"delta\":\"我将读取\"}\n"
                    ).encode(),
                    b"\n",
                    b"event: response.reasoning_summary_text.delta\n",
                    (
                        "data: {\"type\":\"response.reasoning_summary_text.delta\","
                        "\"response_id\":\"resp_1\",\"item_id\":\"rs_1\",\"output_index\":0,"
                        "\"summary_index\":0,\"delta\":\"当前目录。\"}\n"
                    ).encode(),
                    b"\n",
                    b"event: response.reasoning_summary_text.done\n",
                    (
                        "data: {\"type\":\"response.reasoning_summary_text.done\","
                        "\"response_id\":\"resp_1\",\"item_id\":\"rs_1\",\"output_index\":0,"
                        "\"summary_index\":0,\"text\":\"我将读取当前目录。\"}\n"
                    ).encode(),
                    b"\n",
                    b"event: response.completed\n",
                    (
                        "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_1\","
                        "\"output\":[{\"id\":\"rs_1\",\"type\":\"reasoning\","
                        "\"summary\":[{\"type\":\"summary_text\",\"text\":\"我将读取当前目录。\"}]}],"
                        "\"usage\":{\"input_tokens\":1,\"output_tokens\":2,\"total_tokens\":3}}}\n"
                    ).encode(),
                    b"\n",
                ]
            ),
            emit_delta=None,
            emit_raw_sse_event=lambda event_name, payload: emitted_raw_events.append((event_name, payload)),
        )

        self.assertEqual(response.response_id, "resp_1")
        self.assertEqual(
            [event_name for event_name, _ in emitted_raw_events],
            [
                "model_reasoning_summary.delta",
                "model_reasoning_summary.delta",
                "model_reasoning_summary.done",
                "model_reasoning_summary",
                "response.completed",
            ],
        )
        self.assertEqual(emitted_raw_events[0][1]["text"], "我将读取")
        self.assertEqual(emitted_raw_events[1][1]["text"], "当前目录。")
        self.assertEqual(emitted_raw_events[2][1]["text"], "我将读取当前目录。")
        self.assertEqual(
            emitted_raw_events[3][1],
            {
                "type": "model_reasoning_summary",
                "text": "我将读取当前目录。",
                "item_id": "rs_1",
                "response_id": "resp_1",
            },
        )
        self.assertEqual(emitted_raw_events[4][1], {"type": "response.completed", "response_id": "resp_1"})

    def test_stream_parser_derives_reasoning_summary_from_completed_payload_when_no_summary_stream_events(self) -> None:
        runner = OpenAIResponsesRunner(api_key="test-key")
        emitted_raw_events: list[tuple[str, dict]] = []

        runner._parse_stream_response(
            FakeSseResponse(
                [
                    b"event: response.completed\n",
                    (
                        "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_1\","
                        "\"output\":[{\"id\":\"rs_1\",\"type\":\"reasoning\","
                        "\"summary\":[{\"type\":\"summary_text\",\"text\":\"我将读取当前目录。\"}]}],"
                        "\"usage\":{\"input_tokens\":1,\"output_tokens\":2,\"total_tokens\":3}}}\n"
                    ).encode(),
                    b"\n",
                ]
            ),
            emit_delta=None,
            emit_raw_sse_event=lambda event_name, payload: emitted_raw_events.append((event_name, payload)),
        )

        self.assertEqual(
            emitted_raw_events,
            [
                (
                    "model_reasoning_summary",
                    {
                        "type": "model_reasoning_summary",
                        "text": "我将读取当前目录。",
                        "item_id": "rs_1",
                        "response_id": "resp_1",
                    },
                ),
                ("response.completed", {"type": "response.completed", "response_id": "resp_1"}),
            ],
        )

    def test_create_response_applies_total_timeout(self) -> None:
        class SlowRunner(OpenAIResponsesRunner):
            def _create_response_sync(self, request, emit_delta=None):
                del request, emit_delta
                import time

                time.sleep(0.2)
                return parse_response_payload({"id": "resp_1", "output": [], "usage": {}})

        async def run_test():
            runner = SlowRunner(api_key="test-key", timeout_seconds=5, total_timeout_seconds=0.01)
            with self.assertRaises(TimeoutError):
                await runner.create_response({"model": "test", "input": []})

        asyncio.run(run_test())

    def test_create_response_signals_cancel_to_sync_runner_after_total_timeout(self) -> None:
        class CancellableRunner(OpenAIResponsesRunner):
            def __init__(self):
                super().__init__(api_key="test-key", timeout_seconds=5, total_timeout_seconds=0.01)
                self.cancel_event_seen = None
                self.cancelled_in_thread = False

            def _create_response_sync(self, request, emit_delta=None, cancel_event=None):
                del request, emit_delta
                import time

                self.cancel_event_seen = cancel_event
                for _ in range(50):
                    if cancel_event is not None and cancel_event.is_set():
                        self.cancelled_in_thread = True
                        return parse_response_payload({"id": "resp_cancelled", "output": [], "usage": {}})
                    time.sleep(0.01)
                return parse_response_payload({"id": "resp_1", "output": [], "usage": {}})

        async def run_test():
            runner = CancellableRunner()
            with self.assertRaises(TimeoutError):
                await runner.create_response({"model": "test", "input": []})
            await asyncio.sleep(0.08)
            self.assertIsNotNone(runner.cancel_event_seen)
            self.assertTrue(runner.cancel_event_seen.is_set())
            self.assertTrue(runner.cancelled_in_thread)

        asyncio.run(run_test())

    def test_create_response_ignores_late_delta_after_total_timeout(self) -> None:
        class SlowDeltaRunner(OpenAIResponsesRunner):
            def _create_response_sync(self, request, emit_delta=None):
                del request
                import time

                time.sleep(0.05)
                if emit_delta is not None:
                    emit_delta("late")
                time.sleep(0.05)
                return parse_response_payload({"id": "resp_1", "output": [], "usage": {}})

        async def run_test():
            deltas = []

            async def on_delta(text):
                deltas.append(text)

            runner = SlowDeltaRunner(api_key="test-key", timeout_seconds=5, total_timeout_seconds=0.01)
            with self.assertRaises(TimeoutError):
                await runner.create_response({"model": "test", "input": [], "on_delta": on_delta})
            await asyncio.sleep(0.15)
            self.assertEqual(deltas, [])

        asyncio.run(run_test())

    def test_create_response_cancels_stream_when_delta_callback_fails(self) -> None:
        class DeltaFailureRunner(OpenAIResponsesRunner):
            def __init__(self):
                super().__init__(api_key="test-key", timeout_seconds=5)
                self.cancel_event_seen = None
                self.cancelled_in_thread = False
                self.emitted_after_cancel = False

            def _create_response_sync(self, request, emit_delta=None, cancel_event=None):
                del request
                import time

                self.cancel_event_seen = cancel_event
                if emit_delta is not None:
                    emit_delta("first")
                for _ in range(50):
                    if cancel_event is not None and cancel_event.is_set():
                        self.cancelled_in_thread = True
                        if emit_delta is not None:
                            emit_delta("late")
                            self.emitted_after_cancel = True
                        return parse_response_payload({"id": "resp_cancelled", "output": [], "usage": {}})
                    time.sleep(0.01)
                return parse_response_payload({"id": "resp_1", "output": [], "usage": {}})

        async def run_test():
            deltas = []

            async def on_delta(text):
                deltas.append(text)
                raise RuntimeError("analysis was cancelled")

            runner = DeltaFailureRunner()
            with self.assertRaisesRegex(RuntimeError, "analysis was cancelled"):
                await runner.create_response({"model": "test", "input": [], "on_delta": on_delta})
            await asyncio.sleep(0.08)
            self.assertEqual(deltas, ["first"])
            self.assertIsNotNone(runner.cancel_event_seen)
            self.assertTrue(runner.cancel_event_seen.is_set())
            self.assertTrue(runner.cancelled_in_thread)
            self.assertTrue(runner.emitted_after_cancel)

        asyncio.run(run_test())


class FakeSseResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class FakeJsonResponse:
    def __init__(self, payload: dict) -> None:
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


if __name__ == "__main__":
    unittest.main()
